import argparse
import asyncio
import statistics
import time
import uuid

import httpx


async def run_test(base_url: str, requests: int, concurrency: int) -> None:
    semaphore = asyncio.Semaphore(concurrency)
    latencies = []
    successes = 0

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        async def send_tap(index: int) -> None:
            nonlocal successes
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.post(
                        "/api/tap",
                        json={"tap_id": f"load-{uuid.uuid4().hex}", "player_id": f"load-player-{index % 60}"},
                    )
                    if response.is_success and response.json().get("accepted") is True:
                        successes += 1
                    latencies.append((time.perf_counter() - started) * 1000)
                except httpx.HTTPError:
                    latencies.append((time.perf_counter() - started) * 1000)

        await asyncio.gather(*(send_tap(index) for index in range(requests)))

    average = statistics.mean(latencies) if latencies else 0
    print(f"requests={requests} successes={successes} success_rate={successes / requests:.1%}")
    print(f"latency_ms_avg={average:.1f} latency_ms_max={max(latencies, default=0):.1f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="在本機或授權環境測試敲擊 API")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="測試目標，不要填未授權的公開網址")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1:
        parser.error("--requests 與 --concurrency 必須大於 0")
    asyncio.run(run_test(args.url.rstrip("/"), args.requests, args.concurrency))


if __name__ == "__main__":
    main()
