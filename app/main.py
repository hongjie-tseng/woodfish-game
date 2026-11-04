import asyncio
import contextlib
import logging
import subprocess
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import connect, initialize_database, insert_audit_log, transaction
from .store import FLUSH_INTERVAL_SECONDS, RoundNotActive, TapStore
from .models import (
    AdminStatusResponse,
    AdminAuditLogResponse,
    ConfigResponse,
    MetricsResponse,
    RoundActionRequest,
    StatsResponse,
    TapRequest,
    TapResponse,
    VersionResponse,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("woodfish")
settings = get_settings()
PROJECT_ROOT = Path(__file__).parent.parent
VERSION_FILE = PROJECT_ROOT / "VERSION"
INDEX_FILE = Path(__file__).parent / "templates" / "index.html"
_store: TapStore | None = None


def get_store() -> TapStore:
    global _store
    if _store is None or _store.database_path != settings.database_path:
        _store = TapStore(settings.database_path)
    return _store


async def flush_periodically(store: TapStore) -> None:
    while True:
        await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(store.flush)
        except Exception:
            logger.exception("Writing taps to SQLite failed; retrying on the next interval")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Uvicorn writes an access log line only while "uvicorn.access" has handlers; at thousands of
    # taps per second that logging costs more CPU than the taps, and the demo does not need it.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False
    state_created = initialize_database(
        settings.database_path, settings.round_name, settings.round_status
    )
    with transaction(settings.database_path) as connection:
        state = connection.execute(
            "SELECT round_status FROM game_state WHERE id = 1"
        ).fetchone()
        insert_audit_log(
            connection,
            team_id=settings.team_id,
            action="startup",
            previous_status=state["round_status"],
            new_status=state["round_status"],
            source="system_startup",
            source_ip=None,
            success=True,
            error_message=(
                "Initialized round state from settings"
                if state_created
                else "Persisted round status; no startup override applied"
            ),
            git_commit=git_commit(),
            state_initialized=state_created,
        )
    store = get_store()
    flusher = asyncio.create_task(flush_periodically(store))
    logger.info("Woodfish server started: team=%s database=%s", settings.team_id, settings.database_path)
    yield
    flusher.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await flusher
    await asyncio.to_thread(store.flush)


class CountTapRequests:
    """Counts every POST /api/tap, including ones that later fail validation, before routing."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"] == "/api/tap":
            get_store().count_request()
        await self.app(scope, receive, send)


app = FastAPI(title="電子敲木魚", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.add_middleware(CountTapRequests)


def project_version() -> str:
    try:
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        logger.warning("Version file is unavailable: %s", VERSION_FILE)
        return "unknown"
    return version or "unknown"


@lru_cache(maxsize=1)
def git_commit() -> str:
    # Deployments restart the service, so the commit is fixed for the life of the process.
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("Git commit is unavailable: %s", error)
        return "unknown"
    commit = result.stdout.strip()
    return commit or "unknown"


def deployment_token() -> str:
    commit = git_commit()
    return commit if commit != "unknown" else project_version()


def require_admin_proxy(request: Request) -> None:
    client_host = request.client.host if request.client else ""
    if client_host != settings.admin_proxy_ip:
        raise HTTPException(status_code=403, detail="管理 API 僅接受 VM 1")


@app.get("/", include_in_schema=False)
async def index() -> HTMLResponse:
    html = INDEX_FILE.read_text(encoding="utf-8")
    html = html.replace("__ASSET_VERSION__", deployment_token())
    return HTMLResponse(html, headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/api/version", response_model=VersionResponse)
async def get_version(response: Response) -> VersionResponse:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return VersionResponse(version=project_version(), commit=git_commit())


# Zabbix and the admin console read the flushed values in SQLite rather than one process's memory:
# with several Uvicorn workers each holds different unflushed taps, and a counter that moves backwards
# between polls would break Zabbix "Change per second". The values lag by at most one flush interval.
@app.get("/api/metrics", response_model=MetricsResponse)
def get_metrics(response: Response) -> MetricsResponse:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    with connect(settings.database_path) as connection:
        state = connection.execute(
            "SELECT tap_requests_total FROM game_state WHERE id = 1"
        ).fetchone()
    return MetricsResponse(
        team_id=settings.team_id,
        tap_requests_total=state["tap_requests_total"],
        server_time=datetime.now(timezone.utc),
    )


@app.get("/api/admin/status", response_model=AdminStatusResponse)
def admin_status(request: Request) -> AdminStatusResponse:
    require_admin_proxy(request)
    with connect(settings.database_path) as connection:
        state = connection.execute("SELECT * FROM game_state WHERE id = 1").fetchone()
    return AdminStatusResponse(
        team_id=settings.team_id,
        team_name=settings.team_name,
        round_name=state["round_name"],
        round_status=state["round_status"],
        team_taps=state["total_taps"],
        round_taps=state["round_taps"],
        tap_requests_total=state["tap_requests_total"],
        tap_requests_since_reset=state["tap_requests_total"] - state["tap_requests_reset_base"],
        version=project_version(),
        commit=git_commit(),
        server_time=datetime.now(timezone.utc),
    )


@app.get("/api/admin/audit-logs", response_model=list[AdminAuditLogResponse])
def admin_audit_logs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AdminAuditLogResponse]:
    require_admin_proxy(request)
    with connect(settings.database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, timestamp, team_id, action, previous_status, new_status,
                   source, source_ip, success, error_message, git_commit,
                   state_initialized
            FROM admin_audit_logs
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [AdminAuditLogResponse(**dict(row)) for row in rows]


@app.post("/api/admin/round/{action}", response_model=AdminStatusResponse)
async def admin_round_action(
    action: str,
    request: Request,
    payload: RoundActionRequest | None = None,
) -> AdminStatusResponse:
    require_admin_proxy(request)
    if action not in {"start", "pause", "resume", "end", "reset"}:
        raise HTTPException(status_code=404, detail="Unknown round action")
    source_ip = request.client.host if request.client else None
    rejected_error = await asyncio.to_thread(
        get_store().admin,
        lambda: apply_round_action(action, payload, source_ip),
        clear_duplicates=action == "reset",
    )
    if rejected_error is not None:
        raise HTTPException(status_code=409, detail=rejected_error)
    return await asyncio.to_thread(admin_status, request)


def apply_round_action(action: str, payload: RoundActionRequest | None, source_ip: str | None) -> str | None:
    """Runs the round transaction and returns the rejection reason, if any."""
    rejected_error = None
    with transaction(settings.database_path) as connection:
        state = connection.execute(
            "SELECT round_status FROM game_state WHERE id = 1"
        ).fetchone()
        previous_status = state["round_status"]
        transitions = {
            "pause": ("active", "paused"),
            "resume": ("paused", "active"),
            "end": (("active", "paused"), "ended"),
        }
        if action in transitions:
            allowed, new_status = transitions[action]
            allowed_statuses = (allowed,) if isinstance(allowed, str) else allowed
            if previous_status not in allowed_statuses:
                rejected_error = f"Cannot {action} while round is {previous_status}"
                insert_audit_log(
                    connection,
                    team_id=settings.team_id,
                    action=action,
                    previous_status=previous_status,
                    new_status=previous_status,
                    source="admin_api",
                    source_ip=source_ip,
                    success=False,
                    error_message=rejected_error,
                )
        if rejected_error is None and action == "start":
            connection.execute(
                """
                UPDATE game_state
                SET round_status = 'active',
                    round_name = COALESCE(?, round_name),
                    round_taps = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                """,
                (payload.name if payload else None,),
            )
        elif rejected_error is None and action == "pause":
            connection.execute(
                "UPDATE game_state SET round_status = 'paused', updated_at = CURRENT_TIMESTAMP WHERE id = 1"
            )
        elif rejected_error is None and action == "resume":
            connection.execute(
                "UPDATE game_state SET round_status = 'active', updated_at = CURRENT_TIMESTAMP WHERE id = 1"
            )
        elif rejected_error is None and action == "end":
            connection.execute(
                "UPDATE game_state SET round_status = 'ended', updated_at = CURRENT_TIMESTAMP WHERE id = 1"
            )
        elif rejected_error is None:
            # tap_requests_total stays monotonic for Zabbix Change per second; the console counts from this base.
            connection.execute(
                """
                UPDATE game_state
                SET total_taps = 0, round_taps = 0,
                    tap_requests_reset_base = tap_requests_total,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                """
            )
            connection.execute("DELETE FROM player_totals")
            connection.execute("DELETE FROM processed_taps")
        if rejected_error is None:
            updated = connection.execute(
                "SELECT round_status FROM game_state WHERE id = 1"
            ).fetchone()
            insert_audit_log(
                connection,
                team_id=settings.team_id,
                action=action,
                previous_status=previous_status,
                new_status=updated["round_status"],
                source="admin_api",
                source_ip=source_ip,
                success=True,
            )
    return rejected_error


@app.get("/health")
def health() -> dict:
    with connect(settings.database_path) as connection:
        connection.execute("SELECT 1").fetchone()
    return {
        "status": "ok",
        "team": settings.team_id,
        "server_time": datetime.now(timezone.utc),
    }


@app.get("/api/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    state = get_store().snapshot()
    return ConfigResponse(
        team_id=settings.team_id,
        team_name=settings.team_name,
        theme_color=settings.theme_color,
        round_name=state["round_name"],
        round_status=state["round_status"],
    )


@app.get("/api/stats", response_model=StatsResponse)
async def get_stats(player_id: str) -> StatsResponse:
    if not player_id or len(player_id) > 100:
        raise HTTPException(status_code=422, detail="Invalid player_id")
    state = get_store().snapshot(player_id)
    return StatsResponse(
        server_time=datetime.now(timezone.utc),
        reset_marker=state["tap_requests_reset_base"],
        **{key: state[key] for key in ("personal_taps", "team_taps", "round_taps", "round_name", "round_status")},
    )


@app.post("/api/tap", response_model=TapResponse)
async def tap(payload: TapRequest) -> TapResponse:
    try:
        duplicate, state = get_store().tap(payload.tap_id, payload.player_id)
    except RoundNotActive:
        raise HTTPException(status_code=409, detail="本回合目前未進行") from None
    return TapResponse(accepted=True, duplicate=duplicate, reset_marker=state["tap_requests_reset_base"], **{
        key: state[key] for key in ("personal_taps", "team_taps", "round_taps", "round_status")
    })
