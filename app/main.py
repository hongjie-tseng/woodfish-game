import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import connect, initialize_database, transaction
from .models import ConfigResponse, StatsResponse, TapRequest, TapResponse


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("woodfish")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database(settings.database_path, settings.round_name, settings.round_status)
    logger.info("Woodfish server started: team=%s database=%s", settings.team_id, settings.database_path)
    yield


app = FastAPI(title="電子敲木魚", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


def current_state(connection, player_id: str) -> dict:
    state = connection.execute("SELECT * FROM game_state WHERE id = 1").fetchone()
    player = connection.execute(
        "SELECT tap_count FROM player_totals WHERE player_id = ?", (player_id,)
    ).fetchone()
    return {
        "personal_taps": player["tap_count"] if player else 0,
        "team_taps": state["total_taps"],
        "round_taps": state["round_taps"],
        "round_name": state["round_name"],
        "round_status": state["round_status"],
    }


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "templates" / "index.html")


@app.get("/health")
async def health() -> dict:
    with connect(settings.database_path) as connection:
        connection.execute("SELECT 1").fetchone()
    return {
        "status": "ok",
        "team": settings.team_id,
        "server_time": datetime.now(timezone.utc),
    }


@app.get("/api/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    with connect(settings.database_path) as connection:
        state = connection.execute("SELECT round_name, round_status FROM game_state WHERE id = 1").fetchone()
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
    with connect(settings.database_path) as connection:
        state = current_state(connection, player_id)
    return StatsResponse(server_time=datetime.now(timezone.utc), **state)


@app.post("/api/tap", response_model=TapResponse)
async def tap(payload: TapRequest, request: Request) -> TapResponse:
    started = time.monotonic()
    try:
        with transaction(settings.database_path) as connection:
            existing = connection.execute(
                "SELECT player_id FROM processed_taps WHERE tap_id = ?", (payload.tap_id,)
            ).fetchone()
            if existing:
                state = current_state(connection, payload.player_id)
                return TapResponse(accepted=True, duplicate=True, **{
                    key: state[key] for key in ("personal_taps", "team_taps", "round_taps", "round_status")
                })

            state = connection.execute("SELECT round_status FROM game_state WHERE id = 1").fetchone()
            if state["round_status"] != "active":
                raise HTTPException(status_code=409, detail="本回合目前未進行")

            connection.execute(
                "INSERT INTO processed_taps (tap_id, player_id) VALUES (?, ?)",
                (payload.tap_id, payload.player_id),
            )
            connection.execute(
                """
                INSERT INTO player_totals (player_id, tap_count) VALUES (?, 1)
                ON CONFLICT(player_id) DO UPDATE SET
                    tap_count = tap_count + 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (payload.player_id,),
            )
            connection.execute(
                """
                UPDATE game_state SET total_taps = total_taps + 1,
                    round_taps = round_taps + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                """
            )
            result = current_state(connection, payload.player_id)
            return TapResponse(accepted=True, duplicate=False, **{
                key: result[key] for key in ("personal_taps", "team_taps", "round_taps", "round_status")
            })
    finally:
        elapsed = (time.monotonic() - started) * 1000
        logger.debug("tap request completed in %.1fms from %s", elapsed, request.client.host if request.client else "unknown")
