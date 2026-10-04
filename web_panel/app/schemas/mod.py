"""Contratos para el gestor de mods y el catálogo Modrinth."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModItem(BaseModel):
    filename: str
    name: str
    size_mb: float = Field(ge=0)
    is_enabled: bool
    modified_at: str
    is_server_only: bool = False


class ModToggleResponse(BaseModel):
    filename: str
    is_enabled: bool
    message: str


class ModrinthSearchHit(BaseModel):
    project_id: str
    slug: str
    title: str
    description: str
    icon_url: str | None
    downloads: int = Field(ge=0)


class ModInstallRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=128)
    version_id: str | None = Field(default=None, min_length=1, max_length=128)


class ClientPackExportResponse(BaseModel):
    filename: str
    size_mb: float = Field(ge=0)
    message: str
