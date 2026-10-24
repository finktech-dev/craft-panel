from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class Waypoint(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=50)
    x: float
    y: float
    z: float
    dimension: Literal["minecraft:overworld", "minecraft:the_nether", "minecraft:the_end"] = "minecraft:overworld"
    description: str = ""
    icon: str = "map-pin"


class WaypointCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    # Finite, in-world coordinates only: they are written into a /tp command.
    x: float = Field(ge=-30_000_000, le=30_000_000)
    y: float = Field(ge=-2_048, le=4_096)
    z: float = Field(ge=-30_000_000, le=30_000_000)
    dimension: Literal["minecraft:overworld", "minecraft:the_nether", "minecraft:the_end"] = "minecraft:overworld"
    description: str = Field(default="", max_length=300)
    icon: str = Field(default="map-pin", pattern=r"^[a-z0-9-]{1,32}$")


class WaypointTeleportRequest(BaseModel):
    # A player name or a plain selector; no spaces, so it cannot add command arguments.
    target: str = Field(min_length=1, max_length=16, pattern=r"^(@[aprs]|[A-Za-z0-9_]{1,16})$")
