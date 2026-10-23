"""Defensive ZIP/TAR extraction shared by backups, Java runtimes and uploads.

The helpers never trust archive headers: member names are validated with the
portable rules in :mod:`app.core.path_safety`, links and special files are
refused, and the real number of decompressed bytes is counted while streaming
so a forged ``file_size`` cannot hide a zip bomb.
"""

from __future__ import annotations

import stat
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from app.core.path_safety import UnsafePathError, safe_relative_parts

_COPY_CHUNK = 1024 * 1024


class ArchiveSafetyError(ValueError):
    """The archive is malformed, malicious or larger than allowed."""


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    max_members: int = 200_000
    max_total_bytes: int = 64 * 1024**3
    max_member_bytes: int = 8 * 1024**3
    # Ratios above this for members bigger than ``ratio_floor_bytes`` are bombs;
    # real Minecraft region files and JARs stay far below it.
    max_compression_ratio: int = 200
    ratio_floor_bytes: int = 16 * 1024**2


def validate_member_name(name: str) -> tuple[str, ...]:
    """Return the validated components of an archive member name."""
    try:
        return safe_relative_parts(name.rstrip("/"))
    except UnsafePathError as error:
        raise ArchiveSafetyError(f"Ruta insegura dentro del archivo: {name!r}") from error


def _zip_member_is_link(member: zipfile.ZipInfo) -> bool:
    # Many Windows tools store no Unix file type at all; only an explicit type
    # other than "regular file" or "directory" (symlink, device, FIFO) is refused.
    file_type = stat.S_IFMT(member.external_attr >> 16)
    return file_type not in (0, stat.S_IFREG, stat.S_IFDIR)


def check_zip(archive: zipfile.ZipFile, limits: ArchiveLimits) -> list[tuple[zipfile.ZipInfo, tuple[str, ...]]]:
    """Validate every member before anything touches the disk."""
    members = archive.infolist()
    if len(members) > limits.max_members:
        raise ArchiveSafetyError("El archivo contiene demasiadas entradas.")
    declared_total = 0
    seen: set[str] = set()
    validated: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
    for member in members:
        parts = validate_member_name(member.filename)
        key = "/".join(parts).casefold()
        if key in seen and not member.is_dir():
            raise ArchiveSafetyError("El archivo contiene entradas duplicadas.")
        seen.add(key)
        if _zip_member_is_link(member):
            raise ArchiveSafetyError("El archivo contiene enlaces simbólicos o archivos especiales.")
        if member.file_size > limits.max_member_bytes:
            raise ArchiveSafetyError("El archivo contiene una entrada demasiado grande.")
        if (
            member.file_size > limits.ratio_floor_bytes
            and member.file_size > limits.max_compression_ratio * max(member.compress_size, 1)
        ):
            raise ArchiveSafetyError("El archivo tiene una compresión sospechosa (posible zip bomb).")
        declared_total += member.file_size
        if declared_total > limits.max_total_bytes:
            raise ArchiveSafetyError("El contenido descomprimido supera el límite permitido.")
        validated.append((member, parts))
    return validated


class _ByteBudget:
    def __init__(self, limits: ArchiveLimits) -> None:
        self._limits = limits
        self.total = 0

    def copy(self, source: IO[bytes], target: IO[bytes], compressed_size: int | None = None) -> None:
        limits = self._limits
        written = 0
        while chunk := source.read(_COPY_CHUNK):
            written += len(chunk)
            self.total += len(chunk)
            if written > limits.max_member_bytes or self.total > limits.max_total_bytes:
                raise ArchiveSafetyError("El contenido descomprimido supera el límite permitido.")
            # Headers can lie about file_size; the real stream cannot.
            if (
                compressed_size is not None
                and written > limits.ratio_floor_bytes
                and written > limits.max_compression_ratio * max(compressed_size, 1)
            ):
                raise ArchiveSafetyError("El archivo tiene una compresión sospechosa (posible zip bomb).")
            target.write(chunk)


def extract_zip(archive: zipfile.ZipFile, destination: Path, limits: ArchiveLimits = ArchiveLimits()) -> None:
    """Extract a ZIP into an existing, empty staging directory."""
    root = destination.resolve()
    budget = _ByteBudget(limits)
    for member, parts in check_zip(archive, limits):
        target = root.joinpath(*parts)
        if not target.resolve().is_relative_to(root):
            raise ArchiveSafetyError(f"Ruta insegura dentro del archivo: {member.filename!r}")
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source, target.open("xb") as output:
            budget.copy(source, output, member.compress_size)


def extract_tar(archive: tarfile.TarFile, destination: Path, limits: ArchiveLimits = ArchiveLimits()) -> None:
    """Extract only regular files and folders from a TAR into a staging directory."""
    root = destination.resolve()
    members = archive.getmembers()
    if len(members) > limits.max_members:
        raise ArchiveSafetyError("El archivo contiene demasiadas entradas.")
    declared_total = 0
    validated: list[tuple[tarfile.TarInfo, tuple[str, ...]]] = []
    for member in members:
        parts = validate_member_name(member.name)
        if not (member.isfile() or member.isdir()):
            raise ArchiveSafetyError("El archivo contiene enlaces simbólicos o archivos especiales.")
        declared_total += member.size
        if member.size > limits.max_member_bytes or declared_total > limits.max_total_bytes:
            raise ArchiveSafetyError("El contenido descomprimido supera el límite permitido.")
        validated.append((member, parts))

    budget = _ByteBudget(limits)
    for member, parts in validated:
        target = root.joinpath(*parts)
        if not target.resolve().is_relative_to(root):
            raise ArchiveSafetyError(f"Ruta insegura dentro del archivo: {member.name!r}")
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source = archive.extractfile(member)
        if source is None:
            raise ArchiveSafetyError("El archivo contiene una entrada ilegible.")
        with source, target.open("xb") as output:
            budget.copy(source, output)
        # Keep the executable bit for runtimes (java, jspawnhelper) on POSIX only.
        if member.mode & 0o111:
            target.chmod(0o755)


def read_member_capped(archive: zipfile.ZipFile, name: str, max_bytes: int) -> bytes | None:
    """Read one small member (metadata, icons) without trusting its header size."""
    try:
        member = archive.getinfo(name)
    except KeyError:
        return None
    if member.file_size > max_bytes:
        return None
    with archive.open(member) as source:
        data = source.read(max_bytes + 1)
    return data if len(data) <= max_bytes else None
