"""Regression tests for hostile ZIP/TAR archives (zip-slip, links, zip bombs)."""

from __future__ import annotations

import io
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.core.archive_safety import (
    ArchiveLimits,
    ArchiveSafetyError,
    extract_tar,
    extract_zip,
    read_member_capped,
)
from app.core.config import Settings
from app.core.path_safety import UnsafePathError, is_safe_component, resolve_child
from app.services.backup_service import BackupService, BackupServiceError


def _zip_with(entries: dict[str, bytes], *, compression: int = zipfile.ZIP_DEFLATED) -> zipfile.ZipFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, data in entries.items():
            # ZipInfo keeps raw names (no normalisation), like a hand-crafted archive.
            info = zipfile.ZipInfo(name)
            info.compress_type = compression
            archive.writestr(info, data)
    buffer.seek(0)
    return zipfile.ZipFile(buffer)


@pytest.mark.parametrize(
    "name",
    [
        "../evil.txt",
        "world/../../evil.txt",
        "/etc/passwd",
        "C:/Windows/evil.dll",
        "world/C:evil",
        "world/level.dat:hidden",
        "world\\..\\evil.txt",
        "world/CON",
        "world/nul.txt",
        "world/trailing.",
        "world/bad\x01name",
    ],
)
def test_extract_zip_rejects_dangerous_member_names(tmp_path: Path, name: str) -> None:
    archive = _zip_with({name: b"x"})
    with pytest.raises(ArchiveSafetyError):
        extract_zip(archive, tmp_path)
    assert not any(tmp_path.iterdir())


def test_extract_zip_rejects_symlink_members(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        link = zipfile.ZipInfo("world/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "/etc/passwd")
    buffer.seek(0)
    with pytest.raises(ArchiveSafetyError, match="enlaces"):
        extract_zip(zipfile.ZipFile(buffer), tmp_path)


def test_extract_zip_rejects_high_compression_ratio(tmp_path: Path) -> None:
    archive = _zip_with({"world/bomb.bin": b"\0" * (4 * 1024 * 1024)})
    limits = ArchiveLimits(max_compression_ratio=10, ratio_floor_bytes=1024)
    with pytest.raises(ArchiveSafetyError, match="zip bomb"):
        extract_zip(archive, tmp_path, limits)


def test_extract_zip_counts_real_bytes_not_headers(tmp_path: Path) -> None:
    """A forged small file_size in the header must not bypass the size budget."""
    archive = _zip_with({"world/a.bin": b"a" * 5000, "world/b.bin": b"b" * 5000}, compression=zipfile.ZIP_STORED)
    for member in archive.infolist():
        member.file_size = 10
    limits = ArchiveLimits(max_total_bytes=6000)
    with pytest.raises((ArchiveSafetyError, zipfile.BadZipFile)):
        extract_zip(archive, tmp_path, limits)


def test_extract_zip_rejects_too_many_members(tmp_path: Path) -> None:
    archive = _zip_with({f"world/{index}.txt": b"x" for index in range(20)})
    with pytest.raises(ArchiveSafetyError, match="demasiadas"):
        extract_zip(archive, tmp_path, ArchiveLimits(max_members=10))


def test_extract_zip_accepts_a_normal_world(tmp_path: Path) -> None:
    archive = _zip_with({"world/level.dat": b"data", "world/region/r.0.0.mca": b"region"})
    extract_zip(archive, tmp_path)
    assert (tmp_path / "world" / "region" / "r.0.0.mca").read_bytes() == b"region"


def test_extract_tar_rejects_links_and_traversal(tmp_path: Path) -> None:
    for build in ("symlink", "traversal"):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            if build == "symlink":
                info = tarfile.TarInfo("jdk/bin/java")
                info.type = tarfile.SYMTYPE
                info.linkname = "/bin/sh"
                archive.addfile(info)
            else:
                info = tarfile.TarInfo("../../evil")
                info.size = 1
                archive.addfile(info, io.BytesIO(b"x"))
        buffer.seek(0)
        with tarfile.open(fileobj=buffer) as archive, pytest.raises(ArchiveSafetyError):
            extract_tar(archive, tmp_path)


def test_read_member_capped_refuses_oversized_members() -> None:
    archive = _zip_with({"META-INF/mods.toml": b"x" * 2048})
    assert read_member_capped(archive, "META-INF/mods.toml", 1024) is None
    assert read_member_capped(archive, "META-INF/mods.toml", 4096) == b"x" * 2048
    assert read_member_capped(archive, "missing", 4096) is None


@pytest.mark.parametrize("name", ["..", ".", "a:b", "CON", "lpt1.txt", "x/y", "x\\y", "", "name "])
def test_is_safe_component_rejects_windows_and_traversal_names(name: str) -> None:
    assert not is_safe_component(name)


def test_resolve_child_stays_inside_root(tmp_path: Path) -> None:
    assert resolve_child(tmp_path, "world") == (tmp_path / "world").resolve()
    for name in ("..", "../x", ".", "/abs"):
        with pytest.raises(UnsafePathError):
            resolve_child(tmp_path, name)


class _StoppedServer:
    is_running = False


def test_backup_restore_rejects_zip_slip_and_keeps_the_world(tmp_path: Path) -> None:
    configured = Settings(project_root=tmp_path)
    assert configured.server_directory is not None and configured.backups_directory is not None
    world = configured.server_directory / "world"
    world.mkdir(parents=True)
    (world / "level.dat").write_bytes(b"original")
    configured.backups_directory.mkdir(parents=True)
    malicious = configured.backups_directory / "backup_evil.zip"
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("world/level.dat", b"replaced")
        archive.writestr("world/../../escaped.txt", b"pwned")
    service = BackupService(configured_settings=configured, manager=_StoppedServer())

    with pytest.raises((BackupServiceError, ArchiveSafetyError)):
        service._restore_archive_sync(malicious)

    assert (world / "level.dat").read_bytes() == b"original"
    assert not (tmp_path / "escaped.txt").exists()
    assert not list(configured.server_directory.glob(".world-restore-*"))


def test_backup_ignores_a_level_name_outside_the_server_folder(tmp_path: Path, monkeypatch) -> None:
    configured = Settings(project_root=tmp_path)
    assert configured.server_directory is not None
    (configured.server_directory / "world").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    from app.services import server_properties_service as properties_module

    monkeypatch.setattr(
        properties_module.server_properties_service, "read_properties", lambda: {"level-name": "../outside"}
    )
    service = BackupService(configured_settings=configured, manager=_StoppedServer())
    assert service.world_directory.resolve() != outside.resolve()
