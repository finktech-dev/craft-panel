"""API contracts for backups."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BackupItem(BaseModel):
    filename: str
    size_mb: float = Field(ge=0)
    created_at: str


class BackupCreateResponse(BaseModel):
    success: bool
    backup: BackupItem
    message: str


class BackupAuditItem(BackupItem):
    healthy: bool
    error: str | None = None


class BackupAuditResponse(BaseModel):
    checked: list[BackupAuditItem]
    deleted: list[str]
    skipped_corrupt: list[str]
    deleted_temporary: list[str]


class BackupSafetyItem(BackupItem):
    """Metadata of a backup, for display without running an operation."""

    provenance: Literal["panel", "simplebackups", "external"]
    integrity: Literal["verified", "corrupt"]
    integrity_message: str
    restore_ready: bool
    restore_message: str


class BackupSafetyOverview(BaseModel):
    """Read-only state for a clear and safe backups screen."""

    backups: list[BackupSafetyItem]
    total_backups: int = Field(ge=0)
    verified_backups: int = Field(ge=0)
    corrupted_backups: int = Field(ge=0)
    server_running: bool
    restore_warning: str
    retention_count: int = Field(ge=1)
    max_disk_gb: int = Field(ge=1)
