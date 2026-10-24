from __future__ import annotations

from pydantic import BaseModel, Field


class LuckPermsEditorResponse(BaseModel):
    success: bool
    editor_url: str | None = None
    message: str


class LuckPermsCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=500)


class LuckPermsPanelConfig(BaseModel):
    """Local settings of the optional LuckPerms connector."""

    enabled: bool = False
    preset: str = ""
    primary_ranks: list[dict[str, object]] = Field(default_factory=list)
    secondary_roles: list[dict[str, object]] = Field(default_factory=list)


class LuckPermsAvailability(BaseModel):
    enabled: bool
    message: str
    primary_ranks: list[dict[str, object]] = Field(default_factory=list)
    secondary_roles: list[dict[str, object]] = Field(default_factory=list)
