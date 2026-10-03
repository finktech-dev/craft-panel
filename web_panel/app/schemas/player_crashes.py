from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class PlayerCrashEvent(BaseModel):
    id: str
    player: str
    avatar_url: str
    category: Literal[
        "INVALID_DATA",
        "MOD_ERROR",
        "CLIENT_MISMATCH",
        "TIMEOUT",
        "NORMAL_DISCONNECT",
        "KICKED_BANNED",
        "SERVER_CRASH",
        "UNKNOWN"
    ]
    category_label: str
    severity: Literal["error", "warning", "info", "fatal"]
    summary: str
    timestamp: str
    file_source: str
    context_lines: list[str] = Field(default_factory=list)
    suspected_mod: str | None = None
    suggestion: str | None = None


class PlayerCrashesListResponse(BaseModel):
    total_events: int
    players_count: int
    critical_count: int
    unique_players: list[str]
    categories: list[dict[str, str]]
    events: list[PlayerCrashEvent]
