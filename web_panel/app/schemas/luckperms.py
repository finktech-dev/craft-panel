from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LuckPermsEditorResponse(BaseModel):
    success: bool
    editor_url: str | None = None
    message: str


class LuckPermsCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=500)


class LuckPermsCustomRank(BaseModel):
    """A rank created from the panel: kept on the server so every browser lists it."""

    id: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")
    name: str = Field(min_length=1, max_length=40)
    weight: int = Field(default=50, ge=0, le=1000)
    tag: str = Field(default="", max_length=80)
    desc: str = Field(default="", max_length=200)
    perm: str = Field(default="", max_length=60)
    type: Literal["primary", "secondary"] = "primary"


class LuckPermsPanelConfig(BaseModel):
    """Local settings of the optional LuckPerms connector."""

    enabled: bool = False
    preset: str = ""
    primary_ranks: list[dict[str, object]] = Field(default_factory=list)
    secondary_roles: list[dict[str, object]] = Field(default_factory=list)
    custom_ranks: list[LuckPermsCustomRank] = Field(default_factory=list)


class LuckPermsAvailability(BaseModel):
    enabled: bool
    message: str
    primary_ranks: list[dict[str, object]] = Field(default_factory=list)
    secondary_roles: list[dict[str, object]] = Field(default_factory=list)
    custom_ranks: list[LuckPermsCustomRank] = Field(default_factory=list)


class LuckPermsRankStep(BaseModel):
    player: str = Field(pattern=r"^[A-Za-z0-9_]{3,16}$")
    direction: Literal["up", "down", "initial"]
