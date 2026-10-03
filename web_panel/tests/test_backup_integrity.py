"""Pruebas de integridad y purga conservadora de backups."""

from __future__ import annotations

import os
import time
import zipfile
from pathlib import Path

from app.core.config import Settings
from app.services.backup_service import BackupService


def _write_zip(path: Path, content: str) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("world/level.dat", content)


def test_audit_purges_only_old_valid_archives_and_preserves_corrupt(tmp_path: Path):
    configured = Settings(
        project_root=tmp_path,
        backup_retention_count=1,
        backup_max_disk_gb=1,
    )
    assert configured.backups_directory is not None
    assert configured.server_directory is not None
    simplebackups = configured.server_directory / "simplebackups" / "example-world"
    simplebackups.mkdir(parents=True)

    newest = configured.backups_directory / "newest.zip"
    oldest = simplebackups / "oldest.zip"
    corrupt = simplebackups / "corrupt.zip"
    configured.backups_directory.mkdir(parents=True)
    _write_zip(newest, "new")
    _write_zip(oldest, "old")
    corrupt.write_bytes(b"this is not a zip archive")
    now = time.time()
    os.utime(newest, (now, now))
    os.utime(oldest, (now - 60, now - 60))

    result = BackupService(configured_settings=configured)._audit_and_purge_sync()

    assert newest.exists()
    assert not oldest.exists()
    assert corrupt.exists()
    assert result.deleted == [str(oldest)]
    assert result.skipped_corrupt == [str(corrupt)]
    states = {entry.filename: entry.healthy for entry in result.checked}
    assert states == {"newest.zip": True, "oldest.zip": True, "corrupt.zip": False}