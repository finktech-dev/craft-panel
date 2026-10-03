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
    x: float
    y: float
    z: float
    dimension: Literal["minecraft:overworld", "minecraft:the_nether", "minecraft:the_end"] = "minecraft:overworld"
    description: str = ""
    icon: str = "map-pin"


class WaypointTeleportRequest(BaseModel):
    target: str = Field(min_length=1, max_length=50)  # '@a' or username
