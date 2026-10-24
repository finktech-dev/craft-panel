"""Portable path and private-file helpers shared by services that touch disk.

Every check here is applied on all operating systems, so an archive or a file
name that would be dangerous on Windows is rejected even when the panel runs on
Linux (and the other way around). That keeps backups and uploads portable.
"""

from __future__ import annotations

import contextlib
import os
import re
import uuid
from pathlib import Path, PurePosixPath

# CON, PRN, AUX, NUL, COM1-9 and LPT1-9 are devices on Windows, with or without
# an extension ("nul.txt" still opens the NUL device on older Windows builds).
_WINDOWS_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(\..*)?$", re.IGNORECASE)
_FORBIDDEN_CHARACTERS = frozenset('<>:"|?*\\')


class UnsafePathError(ValueError):
    """A user or archive supplied path that could escape its directory."""


def is_safe_component(component: str) -> bool:
    """Return whether ``component`` is a plain file or folder name.

    Rejects traversal (``..``), drive letters and NTFS alternate data streams
    (anything with ``:``), separators, control characters, Windows device names
    and trailing dots/spaces, which Windows silently strips.
    """
    if not component or component in {".", ".."} or len(component) > 255:
        return False
    if any(character in _FORBIDDEN_CHARACTERS or ord(character) < 32 or character == "/" for character in component):
        return False
    if component[-1] in {".", " "}:
        return False
    return not _WINDOWS_RESERVED.match(component)


def safe_relative_parts(name: str) -> tuple[str, ...]:
    """Split a forward-slash relative path and validate every component."""
    if not name or name.startswith("/") or "\\" in name:
        raise UnsafePathError(name)
    parts = tuple(part for part in PurePosixPath(name).parts if part)
    if not parts or not all(is_safe_component(part) for part in parts):
        raise UnsafePathError(name)
    return parts


def resolve_child(root: Path, name: str) -> Path:
    """Resolve ``name`` below ``root`` and refuse anything that escapes it."""
    parts = safe_relative_parts(name)
    resolved_root = root.resolve()
    candidate = resolved_root.joinpath(*parts).resolve()
    if candidate == resolved_root or not candidate.is_relative_to(resolved_root):
        raise UnsafePathError(name)
    return candidate


def write_private_text(path: Path, content: str) -> None:
    """Atomically write a secret file readable only by the current account.

    On POSIX the temporary file is created with mode 0600 before any byte is
    written. On Windows files inherit the ACL of the user profile folder; the
    temporary name is random so a stale file can never be reused.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
