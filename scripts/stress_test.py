"""逐級加壓測試：以固定速率同時對多台 Game Server 送出 POST /api/tap，找出撐不住的點。

只用於自己的實驗環境。測試會真的增加功德與 tap_requests_total，結束後請在管理頁按「重設功德」。
"""
import argparse
import asyncio
import json
import multiprocessing
import ssl
import statistics
import subprocess
import time
import uuid

import httpx

# The service cgroup counts every Uvicorn worker, not only the main process.
PROBE = (
    "echo \"{\\\"cpu\\\":\\\"$(head -1 /proc/stat)\\\","
    "\\\"usage_usec\\\":$(awk '/^usage_usec/{print $2}' /sys/fs/cgroup/system.slice/{service}/cpu.stat),"
    "\\\"mem\\\":$(free -m | awk '/Mem:/{print $3}'),"
    "\\\"rx\\\":$(cat /sys/class/net/ens33/statistics/rx_bytes),\\\"tx\\\":$(cat /sys/class/net/ens33/statistics/tx_bytes),"
    "\\\"rxp\\\":$(cat /sys/class/net/ens33/statistics/rx_packets),\\\"txp\\\":$(cat /sys/class/net/ens33/statistics/tx_packets)}\""
)


def probe(host: str | None, service: str = "woodfish.service") -> dict | None:
    """以唯讀方式讀取遠端 CPU、RAM、指定服務程序 CPU 與 ens33 計數器。"""
    if not host:
        return None
    try:
        output = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, PROBE.replace("{service}", service)],
            capture_output=True, text=True, timeout=15, check=True,
        ).stdout
        data = json.loads(output)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    data["time"] = time.monotonic()
    cpu = [int(value) for value in data["cpu"].split()[1:]]
    data["cpu_total"], data["cpu_idle"] = sum(cpu), cpu[3] + cpu[4]
    return data


def server_delta(before: dict | None, after: dict | None) -> dict:
    if not before or not after:
        return {}
    elapsed = after["time"] - before["time"]
    total = after["cpu_total"] - before["cpu_total"]
    return {
        "cpu": 100 * (1 - (after["cpu_idle"] - before["cpu_idle"]) / total) if total else 0,
        # 以 1 顆 vCPU = 100% 計算；單一 Uvicorn 程序最多只能用滿 1 顆，多個 worker 會加總。
        "proc_cpu": (after["usage_usec"] - before["usage_usec"]) / 1e4 / elapsed,
        "mem": after["mem"],
        "rx": after["rx"] - before["rx"],
        "tx": after["tx"] - before["tx"],
        "packets": after["rxp"] - before["rxp"] + after["txp"] - before["txp"],
        "elapsed": elapsed,
    }


def worker(url: str, rate: float, duration: float, max_inflight: int, tag: str, engine: str = "httpx") -> dict:
    sender = send_at_rate_raw if engine == "raw" else send_at_rate
    return asyncio.run(sender(url, rate, duration, max_inflight, tag))


async def send_at_rate_raw(url: str, rate: float, duration: float, max_inflight: int, tag: str) -> dict:
    """Minimal HTTP/1.1 keep-alive client; httpx cannot send thousands of requests per second."""
    scheme, rest = url.split("://", 1)
    host_port = rest.split("/", 1)[0]
    host, _, port = host_port.partition(":")
    tls = ssl.create_default_context() if scheme == "https" else None
    port = int(port or (443 if tls else 80))
    result = {"sent": 0, "ok": 0, "errors": {}, "skipped": 0, "latencies": []}
    idle: list[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = []
    inflight = set()

    def add_error(key: str) -> None:
        result["errors"][key] = result["errors"].get(key, 0) + 1

    async def tap(index: int) -> None:
        body = json.dumps({"tap_id": f"stress-{uuid.uuid4().hex}", "player_id": f"stress-{tag}-{index % 200:04d}"}).encode()
        request = (
            f"POST /api/tap HTTP/1.1\r\nHost: {host_port}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n\r\n"
        ).encode() + body
        started = time.perf_counter()
        connection = None
        try:
            connection = idle.pop() if idle else await asyncio.wait_for(
                asyncio.open_connection(host, port, ssl=tls, server_hostname=host if tls else None), 10
            )
            reader, writer = connection
            writer.write(request)
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            status = int(head.split(b" ", 2)[1])
            length = 0
            for line in head.split(b"\r\n")[1:]:
                name, _, value = line.partition(b":")
                if name.strip().lower() == b"content-length":
                    length = int(value)
            if length:
                await asyncio.wait_for(reader.readexactly(length), 10)
            idle.append(connection)
            if status == 200:
                result["ok"] += 1
            else:
                lowered = head.lower()
                blocked = b"cf-mitigated" in lowered or 520 <= status <= 530
                add_error(f"{status}{'（Cloudflare）' if blocked else ''}")
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError, IndexError) as error:
            add_error(type(error).__name__)
            if connection:
                connection[1].close()
        result["latencies"].append((time.perf_counter() - started) * 1000)

    start = time.perf_counter()
    for index in range(int(rate * duration)):
        delay = start + index / rate - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        if len(inflight) >= max_inflight:
            result["skipped"] += 1
            continue
        task = asyncio.create_task(tap(index))
        inflight.add(task)
        task.add_done_callback(inflight.discard)
        result["sent"] += 1
    result["send_seconds"] = time.perf_counter() - start
    if inflight:
        await asyncio.wait(inflight, timeout=15)
    for _, writer in idle:
        writer.close()
    return result


async def send_at_rate(url: str, rate: float, duration: float, max_inflight: int, tag: str) -> dict:
    result = {"sent": 0, "ok": 0, "errors": {}, "skipped": 0, "latencies": []}
    limits = httpx.Limits(max_connections=max_inflight, max_keepalive_connections=max_inflight)
    async with httpx.AsyncClient(base_url=url, timeout=10.0, limits=limits, trust_env=False) as client:
        inflight = set()

        async def tap(index: int) -> None:
            started = time.perf_counter()
            try:
                response = await client.post(
                    "/api/tap",
                    json={"tap_id": f"stress-{uuid.uuid4().hex}", "player_id": f"stress-{tag}-{index % 200:04d}"},
                )
                if response.status_code == 200:
                    result["ok"] += 1
                else:
                    # Separate Cloudflare challenges/rate limits and tunnel errors from the game server's own answers.
                    blocked = "cf-mitigated" in response.headers or 520 <= response.status_code <= 530
                    key = f"{response.status_code}{'（Cloudflare）' if blocked else ''}"
                    result["errors"][key] = result["errors"].get(key, 0) + 1
            except httpx.HTTPError as error:
                key = type(error).__name__
                result["errors"][key] = result["errors"].get(key, 0) + 1
            result["latencies"].append((time.perf_counter() - started) * 1000)

        start = time.perf_counter()
        total = int(rate * duration)
        for index in range(total):
            delay = start + index / rate - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            if len(inflight) >= max_inflight:
                result["skipped"] += 1
                continue
            task = asyncio.create_task(tap(index))
            inflight.add(task)
            task.add_done_callback(inflight.discard)
            result["sent"] += 1
        result["send_seconds"] = time.perf_counter() - start
        if inflight:
            await asyncio.wait(inflight, timeout=15)
    return result


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def main() -> None:
    parser = argparse.ArgumentParser(description="逐級加壓測試（只用於自己的實驗環境）")
    parser.add_argument("--target", action="append", required=True,
                        help="名稱=網址[=SSH 別名]，例如 A=http://192.168.26.133:8000=woodfish-a")
    parser.add_argument("--rates", default="100,200,300,500,750,1000,1500,2000", help="每台每秒點擊數，逗號分隔")
    parser.add_argument("--duration", type=float, default=15, help="每一級秒數")
    parser.add_argument("--cooldown", type=float, default=5, help="每一級之間休息秒數")
    parser.add_argument("--processes", type=int, default=4, help="每台使用幾個送出程序")
    parser.add_argument("--max-inflight", type=int, default=500, help="每個程序同時等待中的請求上限")
    parser.add_argument("--keep-going", action="store_true", help="撐不住後仍繼續下一級")
    parser.add_argument("--engine", choices=("httpx", "raw"), default="httpx",
                        help="raw = 精簡 HTTP/1.1 長連線用戶端（http 或 https），可送出更高速率")
    parser.add_argument("--tunnel", help="經 Cloudflare 測試時，執行 cloudflared 那台的 SSH 別名，例如 woodfish-monitor")
    args = parser.parse_args()

    targets = []
    for item in args.target:
        parts = item.split("=", 2)
        if len(parts) < 2:
            parser.error(f"--target 格式錯誤：{item}")
        targets.append({"name": parts[0], "url": parts[1].rstrip("/"), "ssh": parts[2] if len(parts) > 2 else None})
    rates = [int(value) for value in args.rates.split(",")]

    report = []
    with multiprocessing.Pool(len(targets) * args.processes) as pool:
        for rate in rates:
            print(f"\n=== {time.strftime('%H:%M:%S')} 每台目標 {rate} 次/秒，{args.duration:.0f} 秒 ===", flush=True)
            before = {t["name"]: probe(t["ssh"]) for t in targets}
            tunnel_before = probe(args.tunnel, "cloudflared.service")
            jobs = {
                t["name"]: [
                    pool.apply_async(worker, (t["url"], rate / args.processes, args.duration, args.max_inflight,
                                              f"{t['name']}{n}", args.engine))
                    for n in range(args.processes)
                ]
                for t in targets
            }
            results = {name: [job.get() for job in items] for name, items in jobs.items()}
            after = {t["name"]: probe(t["ssh"]) for t in targets}
            tunnel = server_delta(tunnel_before, probe(args.tunnel, "cloudflared.service"))

            broken = False
            for t in targets:
                parts = results[t["name"]]
                ok = sum(p["ok"] for p in parts)
                attempted = int(rate * args.duration)
                errors = {}
                for p in parts:
                    for key, count in p["errors"].items():
                        errors[key] = errors.get(key, 0) + count
                skipped = sum(p["skipped"] for p in parts)
                latencies = [value for p in parts for value in p["latencies"]]
                send_seconds = max(p["send_seconds"] for p in parts)
                server = server_delta(before[t["name"]], after[t["name"]])
                row = {
                    "target": t["name"], "rate": rate, "ok": ok, "attempted": attempted,
                    "achieved": ok / args.duration, "success": ok / attempted if attempted else 0,
                    "p50": percentile(latencies, .5), "p95": percentile(latencies, .95), "p99": percentile(latencies, .99),
                    "errors": errors, "skipped": skipped, "generator_late": send_seconds > args.duration * 1.1,
                    **server,
                }
                if server and ok:
                    row["bytes_per_tap"] = (server["rx"] + server["tx"]) / ok
                    row["rx_mbps"] = server["rx"] * 8 / server["elapsed"] / 1e6
                    row["tx_mbps"] = server["tx"] * 8 / server["elapsed"] / 1e6
                row["broken"] = row["success"] < .99 or row["p95"] > 1000 or row["achieved"] < rate * .9
                broken = broken or row["broken"]
                report.append(row)
                line = (f"[{t['name']}] 成功 {ok}/{attempted} ({row['success']:.1%})  實際 {row['achieved']:.0f}/秒  "
                        f"延遲 p50 {row['p50']:.0f} / p95 {row['p95']:.0f} / p99 {row['p99']:.0f} ms")
                if server:
                    line += (f"\n     伺服器 CPU {server['cpu']:.0f}%（Woodfish 程序 {server['proc_cpu']:.0f}% / 1 核）  RAM {server['mem']} MB  "
                             f"網卡 收 {row.get('rx_mbps', 0):.2f} / 送 {row.get('tx_mbps', 0):.2f} Mbps  "
                             f"{server['packets'] / server['elapsed']:.0f} pps")
                if errors or skipped:
                    line += f"\n     錯誤 {errors}  產生端略過 {skipped}"
                if row["generator_late"]:
                    line += "\n     ⚠ 產生端送不出設定速率，結果可能受測試電腦限制"
                print(line + ("  ← 撐不住" if row["broken"] else ""), flush=True)
            stage_rows = [row for row in report if row["rate"] == rate]
            if tunnel and all("rx" in row for row in stage_rows):
                # VM1 carries both legs; subtracting the game servers' LAN traffic leaves the Internet leg.
                lan = sum(row["rx"] + row["tx"] for row in stage_rows)
                wan_rx = max(0, tunnel["rx"] - sum(row["tx"] for row in stage_rows))
                wan_tx = max(0, tunnel["tx"] - sum(row["rx"] for row in stage_rows))
                ok_total = sum(row["ok"] for row in stage_rows)
                stage_rows[0]["wan"] = {
                    "rx_mbps": wan_rx * 8 / tunnel["elapsed"] / 1e6,
                    "tx_mbps": wan_tx * 8 / tunnel["elapsed"] / 1e6,
                    "bytes_per_tap": (wan_rx + wan_tx) / ok_total if ok_total else 0,
                    "rx_share": wan_rx / (wan_rx + wan_tx) if wan_rx + wan_tx else 0,
                    "cloudflared_cpu": tunnel["proc_cpu"], "cpu": tunnel["cpu"], "lan_bytes": lan,
                }
                wan = stage_rows[0]["wan"]
                print(f"[VM1] CPU {tunnel['cpu']:.0f}%（cloudflared {tunnel['proc_cpu']:.0f}%）  "
                      f"對外網路 下載 {wan['rx_mbps']:.2f} / 上傳 {wan['tx_mbps']:.2f} Mbps", flush=True)
            if broken and not args.keep_going:
                print("\n已出現撐不住的情況，停止加壓。")
                break
            time.sleep(args.cooldown)

    print("\n=== 摘要 ===")
    for t in targets:
        rows = [row for row in report if row["target"] == t["name"]]
        passed = [row for row in rows if not row["broken"]]
        failed = [row for row in rows if row["broken"]]
        print(f"[{t['name']}] 最高通過：{passed[-1]['rate'] if passed else '無'} 次/秒；"
              f"第一個撐不住：{failed[0]['rate'] if failed else '未出現'} 次/秒")
        measured = [row for row in rows if "bytes_per_tap" in row]
        if measured:
            per_tap = statistics.median(row["bytes_per_tap"] for row in measured)
            rx_share = statistics.median(row["rx"] / (row["rx"] + row["tx"]) for row in measured)
            mbps = per_tap * 2000 * 8 / 1e6
            print(f"     內網：每次點擊實測約 {per_tap:.0f} Bytes（含 HTTP 標頭與 TCP/IP）；"
                  f"每台每秒 2000 次約需 {mbps:.1f} Mbps（收 {mbps * rx_share:.1f} / 送 {mbps * (1 - rx_share):.1f}）")
    wans = [row["wan"] for row in report if "wan" in row and row["wan"]["bytes_per_tap"]]
    if wans:
        per_tap = statistics.median(wan["bytes_per_tap"] for wan in wans)
        rx_share = statistics.median(wan["rx_share"] for wan in wans)
        clicks = 2000 * len(targets)
        mbps = per_tap * clicks * 8 / 1e6
        print(f"[對外網路] 每次點擊實測約 {per_tap:.0f} Bytes（VM1 與 Cloudflare 之間）；"
              f"{len(targets)} 台各每秒 2000 次（共 {clicks} 次/秒）約需 {mbps:.1f} Mbps"
              f"（VM1 下載 {mbps * rx_share:.1f} / 上傳 {mbps * (1 - rx_share):.1f}）")
    with open("stress_test_report.json", "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print("詳細資料已寫入 stress_test_report.json")


if __name__ == "__main__":
    main()
