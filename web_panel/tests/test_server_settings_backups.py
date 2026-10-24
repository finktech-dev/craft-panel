"""craftpanel.txt backup keys: interval, retention, size cap, location and [backup_include]."""

from __future__ import annotations

import os
import sys
import time
import zipfile
from pathlib import Path

import pytest

from app.services.server_settings_file import KEYS, SECTIONS, ServerSettingsFile, ValidationContext
from tests.test_server_settings_file import backup_service_for, make_world, settings_for, write_file


def _zip(path: Path, mtime: float, size: int = 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("world/level.dat", b"x" * size)
    os.utime(path, (mtime, mtime))
    return path


def test_backup_keep_and_max_size_replace_the_panel_settings(tmp_path: Path, monkeypatch) -> None:
    configured = settings_for(tmp_path)
    service = backup_service_for(configured, monkeypatch)
    now = time.time()
    paths = [_zip(configured.backups_directory / f"backup_{index}.zip", now - index * 60) for index in range(6)]

    assert len(service._select_purge_candidates(paths)) == 6 - configured.backup_retention_count

    write_file(configured, "backup_keep = 2\n")
    assert sorted(service._select_purge_candidates(paths)) == sorted(paths[2:])

    write_file(configured, "backup_keep = 5\nbackup_max_size = 1GB\n")
    monkeypatch.setattr("app.services.backup_service._GIBIBYTE", paths[0].stat().st_size * 2 + 1)
    # Only the newest two fit in "1GB" (shrunk for the test); the newest copy is always kept.
    assert len(service._select_purge_candidates(paths)) == 4


def test_backup_location_moves_new_copies_and_keeps_old_ones_visible(tmp_path: Path, monkeypatch) -> None:
    configured = settings_for(tmp_path)
    make_world(configured)
    service = backup_service_for(configured, monkeypatch)
    old = _zip(configured.backups_directory / "backup_old.zip", time.time() - 3600)
    location = tmp_path / "elsewhere" / "copies"
    write_file(configured, f"backup_location = {location}\nbackup_keep = 1\n")

    assert service.backups_directory == location
    new = _zip(location / "backup_new.zip", time.time())
    newer = _zip(location / "backup_newer.zip", time.time() + 10)

    listed = {path.name for path in service._backup_paths_sync()}
    assert {"backup_old.zip", "backup_new.zip", "backup_newer.zip"} <= listed
    assert service._backup_provenance(old) == "panel"
    assert service.get_backup_path("backup_old.zip").name == "backup_old.zip"

    deleted = service._audit_and_purge_sync().deleted
    # Retention only applies where new copies go; the old folder is never purged.
    assert deleted == [str(new)]
    assert old.is_file() and newer.is_file()


def test_safety_summary_counts_copies_in_both_places(tmp_path: Path) -> None:
    from app.services.safety_service import SafetyService

    configured = settings_for(tmp_path)
    location = tmp_path / "elsewhere"
    _zip(configured.backups_directory / "a.zip", time.time())
    _zip(location / "b.zip", time.time())
    write_file(configured, f"backup_location = {location}\n")

    assert {path.name for path in SafetyService(configured)._panel_backups()} == {"a.zip", "b.zip"}


def test_backup_location_validation(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    context = ValidationContext(server_directory=configured.server_directory)
    parse = KEYS["backup_location"].parser

    assert parse(str(tmp_path / "copies"), context) == str(tmp_path / "copies")
    for bad in [
        str(configured.server_directory / "backups"),
        str(configured.server_directory),
        "copies",
        "C:\\" if sys.platform == "win32" else "/",
        "\\\\host\\share\\copies",
    ]:
        with pytest.raises(ValueError):
            parse(bad, context)
    (tmp_path / "a-file").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        parse(str(tmp_path / "a-file"), context)


def test_backup_include_validation(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    context = ValidationContext(server_directory=configured.server_directory)
    parse = SECTIONS["backup_include"].parser

    for good in ["config/", "server.properties", "defaultconfigs", "kubejs/server_scripts/"]:
        assert parse(good, context) == good
    for bad in ["../outside", "/etc", "world", "world/data", "config\\x", "*.toml", "backups/", "con"]:
        with pytest.raises(ValueError):
            parse(bad, context)
    assert len(ServerSettingsFile().load(configured).items("backup_include")) == 0
    text = "[backup_include]\n" + "".join(f"folder{index}/\n" for index in range(51))
    write_file(configured, text)
    assert ServerSettingsFile().load(configured).problems[0].line == 52


def _server_files(configured) -> None:
    server = configured.server_directory
    (server / "config").mkdir()
    (server / "config" / "mod.toml").write_text("speed = 1\n", encoding="utf-8")
    (server / "config" / "keep.toml").write_text("mine = true\n", encoding="utf-8")
    (server / "server.properties").write_text("level-name=world\nmotd=old\n", encoding="utf-8")


def test_backup_include_adds_server_files_under_their_own_prefix(tmp_path: Path, monkeypatch) -> None:
    configured = settings_for(tmp_path)
    make_world(configured)
    _server_files(configured)
    write_file(configured, "[backup_include]\nconfig/\nserver.properties\nmissing.txt\n")
    service = backup_service_for(configured, monkeypatch)
    archive = tmp_path / "copy.zip"

    service._create_archive_sync(archive)

    with zipfile.ZipFile(archive) as contents:
        names = set(contents.namelist())
    assert {"server_files/config/mod.toml", "server_files/config/keep.toml", "server_files/server.properties"} <= names
    assert "world/level.dat" in names
    assert not any(name.startswith("server_files/world") for name in names)


@pytest.mark.parametrize("restore_files", [False, True])
def test_restore_puts_back_server_files_only_when_asked_and_never_protected_ones(
    tmp_path: Path, monkeypatch, restore_files: bool
) -> None:
    configured = settings_for(tmp_path)
    make_world(configured)
    _server_files(configured)
    write_file(configured, "[backup_include]\nconfig/\nserver.properties\n\n[protected]\nconfig/keep.toml\n")
    service = backup_service_for(configured, monkeypatch)
    archive = tmp_path / "copy.zip"
    service._create_archive_sync(archive)

    server = configured.server_directory
    (server / "config" / "mod.toml").write_text("speed = 9\n", encoding="utf-8")
    (server / "config" / "keep.toml").write_text("mine = changed\n", encoding="utf-8")
    (server / "server.properties").write_text("level-name=world\nmotd=new\n", encoding="utf-8")

    service._restore_archive_sync(archive, None, restore_files)

    assert (server / "world" / "level.dat").is_file()
    assert (server / "config" / "mod.toml").read_text(encoding="utf-8") == ("speed = 1\n" if restore_files else "speed = 9\n")
    assert "motd=old" in (server / "server.properties").read_text(encoding="utf-8") if restore_files else True
    # Protected files are never touched, even when restoring the configuration.
    assert (server / "config" / "keep.toml").read_text(encoding="utf-8") == "mine = changed\n"
    assert not any(path.name.startswith(".world-restore-") for path in server.iterdir())


def test_restore_rejects_zip_slip_in_server_files(tmp_path: Path, monkeypatch) -> None:
    from app.services.backup_service import BackupServiceError

    configured = settings_for(tmp_path)
    make_world(configured)
    service = backup_service_for(configured, monkeypatch)
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as contents:
        contents.writestr("world/level.dat", b"x")
        contents.writestr("server_files/../../outside.txt", b"x")

    with pytest.raises((BackupServiceError, Exception)):
        service._restore_archive_sync(archive, None, True)
    assert not (tmp_path / "outside.txt").exists()


@pytest.mark.asyncio
async def test_restore_is_refused_when_the_world_is_protected(tmp_path: Path, monkeypatch) -> None:
    from app.services.backup_service import BackupConflictError

    configured = settings_for(tmp_path)
    make_world(configured)
    write_file(configured, "[protected]\nworld/level.dat\n")
    service = backup_service_for(configured, monkeypatch)
    _zip(configured.backups_directory / "backup_a.zip", time.time())

    with pytest.raises(BackupConflictError) as error:
        await service.restore_backup("backup_a.zip")
    assert "protegido" in str(error.value)


def test_scheduler_prefers_backup_interval_from_the_file(tmp_path: Path) -> None:
    from app.services.scheduler_service import SchedulerService

    configured = settings_for(tmp_path)
    scheduler = SchedulerService(configured)
    scheduler._save_backup_interval(12)
    assert scheduler.backup_interval_seconds() == 12 * 3600

    write_file(configured, "backup_interval = 90m\n")
    assert scheduler.backup_interval_seconds() == 90 * 60

    scheduler.sync_with_settings_file()
    job = scheduler.scheduler.get_job("panel-backup")
    assert job is not None and job.trigger.interval.total_seconds() == 90 * 60


def test_choosing_an_interval_in_ajustes_updates_an_existing_file(tmp_path: Path) -> None:
    from app.services.scheduler_service import SchedulerService

    configured = settings_for(tmp_path)
    scheduler = SchedulerService(configured)

    scheduler.add_backup(3)
    assert not (configured.server_directory / "craftpanel.txt").exists()

    path = write_file(configured, "# mine\nbackup_interval = 6h\n")
    scheduler.add_backup(12)
    assert path.read_text(encoding="utf-8") == "# mine\nbackup_interval = 12h\n"
    assert scheduler.backup_interval_seconds() == 12 * 3600
