from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class PlayerTimelineEntry(BaseModel):
    """One thing that happened to the player during the session that ended."""

    time: str | None = None
    kind: Literal["join", "chat", "command", "admin", "death", "advancement", "lag", "error", "kick", "leave"]
    text: str


class PlayerCrashEvent(BaseModel):
    id: str
    player: str
    avatar_url: str
    category: Literal[
        "INVALID_DATA",
        "MOD_ERROR",
        "CLIENT_MISMATCH",
        "TIMEOUT",
        "CLIENT_CLOSED",
        "NORMAL_DISCONNECT",
        "KICKED",
        "BANNED",
        "NOT_WHITELISTED",
        # Kept so lists saved by older versions still load.
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
    # Plain-language explanation shown first in the panel.
    headline: str | None = None
    advice: str | None = None
    # ISO date and time of the disconnect, when the log tells it.
    occurred_at: str | None = None
    session_seconds: int | None = None
    joined_at: str | None = None
    kicked_by: str | None = None
    lag_warnings: int = 0
    timeline: list[PlayerTimelineEntry] = Field(default_factory=list)


class PlayerCrashesListResponse(BaseModel):
    total_events: int
    players_count: int
    critical_count: int
    unique_players: list[str]
    categories: list[dict[str, str]]
    events: list[PlayerCrashEvent]
