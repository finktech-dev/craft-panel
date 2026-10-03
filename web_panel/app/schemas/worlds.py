from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class WorldItem(BaseModel):
    name: str
    is_active: bool
    size_bytes: int
    size_formatted: str
    last_modified: str
    has_nether: bool = False
    has_the_end: bool = False


class WorldSwitchRequest(BaseModel):
    world_name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")


class WorldCreateRequest(BaseModel):
    world_name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    seed: str | None = Field(default=None, max_length=128)
    gamemode: Literal["survival", "creative", "adventure", "spectator"] = "survival"
    difficulty: Literal["peaceful", "easy", "normal", "hard"] = "normal"
    generate_structures: bool = True
    hardcore: bool = False


class ServerPropertyOption(BaseModel):
    value: str
    label: str
    description: str | None = None


class ServerPropertyDefinition(BaseModel):
    key: str
    label: str
    category: str
    type: Literal["boolean", "number", "select", "text"]
    current_value: str
    default_value: str
    description: str
    recommended_value: str
    impact: str
    options: list[ServerPropertyOption] | None = None
    min_value: int | None = None
    max_value: int | None = None


class ServerPropertiesResponse(BaseModel):
    categories: list[str]
    properties: list[ServerPropertyDefinition]
    raw_motd: str
    motd_preview_html: str


class ServerPropertiesSaveRequest(BaseModel):
    properties: dict[str, str]
