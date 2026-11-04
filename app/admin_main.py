import asyncio
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import RoundActionRequest


class AdminSettings(BaseSettings):
    game_server_a_url: str = "http://192.168.26.133:8000"
    game_server_b_url: str = "http://192.168.26.135:8000"
    admin_request_timeout_seconds: float = 5.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


class ControlResult(BaseModel):
    target: str
    success: bool
    status: str
    detail: str | None = None
    data: dict | None = None


class ControlResponse(BaseModel):
    overall: str
    results: list[ControlResult]


admin_settings = AdminSettings()
UPSTREAMS = {
    "A": admin_settings.game_server_a_url.rstrip("/"),
    "B": admin_settings.game_server_b_url.rstrip("/"),
}
# (monotonic time, team taps, tap requests); the console polls about once per second.
SAMPLES: dict[str, deque[tuple[float, int, int]]] = defaultdict(lambda: deque(maxlen=200))
INDEX_FILE = Path(__file__).parent / "templates" / "admin.html"
app = FastAPI(title="Woodfish centralized administration")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


def rate_for(target: str, now: float, window: float = 60, field: int = 1, scale: float = 60) -> float | None:
    samples = SAMPLES[target]
    if len(samples) < 2:
        return None
    while len(samples) > 2 and samples[0][0] < now - 60:
        samples.popleft()
    first = next((sample for sample in samples if sample[0] >= now - window), samples[0])
    if first is samples[-1]:
        first = samples[-2]
    elapsed = samples[-1][0] - first[0]
    delta = samples[-1][field] - first[field]
    if elapsed <= 0 or delta < 0:
        return 0.0
    return round(delta * scale / elapsed, 1)


async def fetch_status(client: httpx.AsyncClient, target: str) -> dict:
    now = time.monotonic()
    try:
        response = await client.get(f"{UPSTREAMS[target]}/api/admin/status")
        response.raise_for_status()
        data = response.json()
        SAMPLES[target].append((now, int(data["team_taps"]), int(data.get("tap_requests_total", 0))))
        data["target"] = target
        data["online"] = True
        data["recent_rate_per_minute"] = rate_for(target, now)
        data["taps_per_second"] = rate_for(target, now, window=5, scale=1)
        data["requests_per_second"] = rate_for(target, now, window=5, field=2, scale=1)
        return data
    except (httpx.HTTPError, ValueError, KeyError) as error:
        return {
            "target": target,
            "online": False,
            "detail": str(error),
            "recent_rate_per_minute": None,
            "taps_per_second": None,
            "requests_per_second": None,
        }


async def fetch_all_status() -> list[dict]:
    timeout = httpx.Timeout(admin_settings.admin_request_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        return list(await asyncio.gather(*(fetch_status(client, target) for target in UPSTREAMS)))


async def apply_action(client: httpx.AsyncClient, target: str, action: str, payload: dict) -> ControlResult:
    try:
        response = await client.post(f"{UPSTREAMS[target]}/api/admin/round/{action}", json=payload)
        response.raise_for_status()
        return ControlResult(target=target, success=True, status="completed", data=response.json())
    except (httpx.HTTPError, ValueError) as error:
        return ControlResult(target=target, success=False, status="failed", detail=str(error))


async def fetch_audit_logs(client: httpx.AsyncClient, target: str, limit: int) -> list[dict]:
    try:
        response = await client.get(
            f"{UPSTREAMS[target]}/api/admin/audit-logs",
            params={"limit": limit},
        )
        response.raise_for_status()
        return [{**entry, "target": target} for entry in response.json()]
    except (httpx.HTTPError, ValueError) as error:
        return [{"target": target, "error": str(error)}]


@app.get("/", include_in_schema=False)
async def admin_index() -> HTMLResponse:
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/health")
async def admin_health() -> dict:
    return {"status": "ok", "service": "woodfish-admin"}


@app.get("/api/admin/status")
async def admin_status() -> dict:
    teams = await fetch_all_status()
    return {"teams": teams, "server_time": datetime.now(timezone.utc)}


@app.get("/api/admin/audit-logs")
async def audit_logs(limit: int = 50) -> dict:
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    timeout = httpx.Timeout(admin_settings.admin_request_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        batches = await asyncio.gather(
            *(fetch_audit_logs(client, target, limit) for target in UPSTREAMS)
        )
    records = [record for batch in batches for record in batch if "id" in record]
    records.sort(key=lambda record: (record["timestamp"], record["id"]), reverse=True)
    return {"records": records[:limit], "server_time": datetime.now(timezone.utc)}


@app.post("/api/admin/control/{target}/{action}", response_model=ControlResponse)
async def control(target: str, action: str, payload: RoundActionRequest | None = None) -> ControlResponse:
    target = target.upper()
    if target not in {*UPSTREAMS, "ALL"}:
        raise HTTPException(status_code=404, detail="Unknown team target")
    if action not in {"start", "pause", "resume", "end", "reset"}:
        raise HTTPException(status_code=404, detail="Unknown round action")
    targets = list(UPSTREAMS) if target == "ALL" else [target]
    body = payload.model_dump(exclude_none=True) if payload else {}
    timeout = httpx.Timeout(admin_settings.admin_request_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        results = list(await asyncio.gather(*(apply_action(client, item, action, body) for item in targets)))
    successes = sum(result.success for result in results)
    overall = "success" if successes == len(results) else "partial" if successes else "failed"
    return ControlResponse(overall=overall, results=results)
