from datetime import datetime

from pydantic import BaseModel, Field


class TapRequest(BaseModel):
    tap_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    player_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class TapResponse(BaseModel):
    accepted: bool
    duplicate: bool
    personal_taps: int
    team_taps: int
    round_taps: int
    round_status: str


class StatsResponse(BaseModel):
    personal_taps: int
    team_taps: int
    round_taps: int
    round_name: str
    round_status: str
    server_time: datetime


class ConfigResponse(BaseModel):
    team_id: str
    team_name: str
    theme_color: str
    round_name: str
    round_status: str


class VersionResponse(BaseModel):
    version: str
    commit: str


class MetricsResponse(BaseModel):
    team_id: str
    tap_requests_total: int
    server_time: datetime


class RoundActionRequest(BaseModel):
    name: str | None = None


class AdminStatusResponse(BaseModel):
    team_id: str
    team_name: str
    round_name: str
    round_status: str
    team_taps: int
    round_taps: int
    version: str
    commit: str
    server_time: datetime


class AdminAuditLogResponse(BaseModel):
    id: int
    timestamp: datetime
    team_id: str
    action: str
    previous_status: str
    new_status: str
    source: str
    source_ip: str | None
    success: bool
    error_message: str | None
    git_commit: str | None
    state_initialized: bool
