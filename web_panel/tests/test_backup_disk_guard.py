"""Regression coverage for disk exhaustion caused by scheduled backups."""

from __future__ import annotations

import os
import time
import zipfile
from collections import namedtuple
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services import backup_service as backup_module
from app.services.backup_service import BackupService, BackupServiceError

_DiskUsage = namedtuple("_DiskUsage", "total used free")


class StoppedServer:
    is_running = False


class SilentDiscord:
    async def send_backup_created(self, backup) -> None:
        return None


def _service(tmp_path: Path, **overrides) -> BackupService:
    configured = Settings(project_root=tmp_path, backup_min_free_disk_gb=0, **overrides)
    assert configured.server_directory is not None
    world = configured.server_directory / "world"
    world.mkdir(parents=True)
    (world / "level.dat").write_bytes(b"level")
    return BackupService(configured_settings=configured, manager=StoppedServer(), discord=SilentDiscord())


def _old_panel_backup(service: BackupService, name: str, age_seconds: int) -> Path:
    service.backups_directory.mkdir(parents=True, exist_ok=True)
    path = service.backups_directory / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("world/level.dat", name)
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))
    return path


@pytest.mark.asyncio
async def test_retention_runs_after_every_backup(tmp_path: Path) -> None:
    service = _service(tmp_path, backup_retention_count=2)
    old = [_old_panel_backup(service, f"backup_old_{index}.zip", 600 - index) for index in range(3)]

    created = await service.create_backup()

    remaining = sorted(path.name for path in service.backups_directory.glob("*.zip"))
    assert len(remaining) == 2
    assert created.filename in remaining
    assert old[2].name in remaining


@pytest.mark.asyncio
async def test_backup_refuses_to_start_without_free_space(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, backup_retention_count=5)
    service._settings.backup_min_free_disk_gb = 10
    existing = _old_panel_backup(service, "backup_existing.zip", 60)
    monkeypatch.setattr(backup_module.shutil, "disk_usage", lambda _: _DiskUsage(100, 100, 1024))

    with pytest.raises(BackupServiceError, match="Espacio insuficiente"):
        await service.create_backup()

    assert existing.exists(), "copies within the retention window must never be deleted"
    assert list(service.backups_directory.glob("backup_2*.zip")) == []


@pytest.mark.asyncio
async def test_scheduled_backup_skips_unchanged_world(tmp_path: Path) -> None:
    service = _service(tmp_path)

    first = await service.create_scheduled_backup()
    second = await service.create_scheduled_backup()

    assert first is not None
    assert second is None
    (service.world_directory / "region.mca").write_bytes(b"chunk")
    time.sleep(1.1)  # backup filenames only have one-second resolution
    third = await service.create_scheduled_backup()
    assert third is not None


@pytest.mark.asyncio
async def test_scheduled_backup_runs_when_last_backup_was_deleted(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = await service.create_scheduled_backup()
    assert first is not None
    (service.backups_directory / first.filename).unlink()

    assert await service.create_scheduled_backup() is not None


def test_retention_always_keeps_newest_even_above_disk_cap(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, backup_retention_count=3, backup_max_disk_gb=1)
    newest = _old_panel_backup(service, "backup_new.zip", 1)
    older = _old_panel_backup(service, "backup_older.zip", 60)
    # Shrink the GiB unit so a 1 "GB" cap is smaller than any single archive.
    monkeypatch.setattr(backup_module, "_GIBIBYTE", 1)

    assert service._select_purge_candidates([newest, older]) == [older]


def test_stale_partial_archives_are_cleaned(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.backups_directory.mkdir(parents=True)
    stale = service.backups_directory / ".backup_x.zip.abc.part"
    fresh = service.backups_directory / ".backup_y.zip.def.part"
    stale.write_bytes(b"partial")
    fresh.write_bytes(b"partial")
    old = time.time() - 72 * 3600
    os.utime(stale, (old, old))

    deleted = service._delete_stale_temporary_archives_sync()

    assert deleted == [str(stale)]
    assert fresh.exists()
