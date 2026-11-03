from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    team_id: str = "A"
    team_name: str = "A 隊"
    theme_color: str = "#b45309"
    database_path: str = str(BASE_DIR / "data" / "woodfish.db")
    round_name: str = "課堂展示回合"
    round_status: str = "active"
    tap_timeout_seconds: float = 10.0
    max_retry_attempts: int = 3

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
