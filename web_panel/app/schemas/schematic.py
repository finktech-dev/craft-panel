"""Modelos de respuesta para esquemas NBT generados por el panel."""

from pydantic import BaseModel, Field


class SchematicItem(BaseModel):
    filename: str
    size_kb: float
    modified_at: str


class SchematicGenerationResponse(BaseModel):
    success: bool
    schematic: SchematicItem
    message: str


class ViaductGenerationRequest(BaseModel):
    length_blocks: int = Field(default=60, ge=20, le=256)
