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
    mod_id: str | None = None
    version: str | None = None
    description: str | None = None
    authors: str | None = None
    has_config: bool = False
    config_filename: str | None = None


class ModBulkActionRequest(BaseModel):
    action: str = Field(pattern=r"^(enable|disable|delete)$")
    filenames: list[str] = Field(min_length=1, max_length=200)


class ModBulkActionResponse(BaseModel):
    action: str
    affected_count: int
    errors: list[str] = []
    message: str


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
    loader: str | None = None
    game_version: str | None = None
    install_dependencies: bool = True
    # Set when updating: the installed jar to remove once the new version is in place.
    replace_filename: str | None = Field(default=None, min_length=1, max_length=255)


class ModUpdateItem(BaseModel):
    filename: str
    mod_id: str | None = None
    name: str
    current_version: str | None = None
    latest_version: str | None = None
    project_id: str | None = None
    has_update: bool = False


class ClientPackExportResponse(BaseModel):
    filename: str
    size_mb: float = Field(ge=0)
    message: str


class ModEnvironmentResponse(BaseModel):
    """Installed server as detected from its files; ``None`` means unknown."""

    loader: str | None
    minecraft_version: str | None
    loader_version: str | None = None
    label: str | None = None


class ModHistoryRef(BaseModel):
    filename: str
    name: str
    version: str | None = None


class ModHistoryVersionChange(BaseModel):
    name: str
    from_filename: str
    to_filename: str
    from_version: str | None = None
    to_version: str | None = None


class ModHistoryChanges(BaseModel):
    """What going back to a snapshot would do to the current mods folder."""

    added: list[ModHistoryRef] = []
    removed: list[ModHistoryRef] = []
    updated: list[ModHistoryVersionChange] = []
    enabled: list[ModHistoryRef] = []
    disabled: list[ModHistoryRef] = []


class ModHistoryEntry(BaseModel):
    """A moment of the mods folder and what changed right after it."""

    id: str
    created_at: str
    action: str
    summary: str
    added: int = Field(ge=0)
    removed: int = Field(ge=0)
    updated: int = Field(ge=0)
    toggled: int = Field(ge=0)
    mod_count: int = Field(ge=0)
    restorable: bool


class ModHistoryDetail(ModHistoryEntry):
    changes: ModHistoryChanges
    lines: list[str]
    missing: list[ModHistoryRef] = []


class ModHistoryRestoreRequest(BaseModel):
    confirm: bool = False


class ModHistoryRestoreResponse(BaseModel):
    message: str
    undo_id: str | None = None
    restored_count: int = Field(ge=0)
