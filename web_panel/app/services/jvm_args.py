"""Write the server's RAM into ``user_jvm_args.txt`` (-Xmx/-Xms), the file run.bat reads."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from app.core.config import Settings
from app.services.protected_paths import require_not_protected

JVM_ARGS_FILENAME = "user_jvm_args.txt"


class JvmArgsMissingError(FileNotFoundError):
    """The server has no user_jvm_args.txt to put the RAM in."""


def jvm_args_path(configured: Settings) -> Path:
    assert configured.server_directory is not None
    return configured.server_directory / JVM_ARGS_FILENAME


def apply_ram(configured: Settings, allocated_ram_gb: int) -> bool:
    """Set -Xmx to ``allocated_ram_gb`` and -Xms to at most 2G; returns whether the file changed."""
    target = jvm_args_path(configured)
    if not target.is_file():
        raise JvmArgsMissingError(str(target))
    lines = target.read_text(encoding="utf-8").splitlines()
    maximum_line = f"-Xmx{allocated_ram_gb}G"
    initial_line = f"-Xms{min(2, allocated_ram_gb)}G"
    found_maximum = found_initial = False
    updated: list[str] = []
    for line in lines:
        if line.strip().lower().startswith("-xmx"):
            updated.append(maximum_line)
            found_maximum = True
        elif line.strip().lower().startswith("-xms"):
            updated.append(initial_line)
            found_initial = True
        else:
            updated.append(line)
    if not found_initial:
        updated.append(initial_line)
    if not found_maximum:
        updated.append(maximum_line)
    if updated == lines:
        return False
    require_not_protected(target, configured=configured)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text("\n".join(updated) + "\n", encoding="utf-8")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return True
