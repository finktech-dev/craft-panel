"""The single place that answers "may the panel change this file?" for ``[protected]``.

Paths listed in ``[protected]`` of ``server/craftpanel.txt`` (gitignore-style,
relative to the server folder) are never modified or deleted by the panel:
mod changes, config saves, restores, installer writes, server.properties
edits and world deletion all call :func:`require_not_protected` or
:func:`require_tree_not_protected` before touching disk.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from app.core.config import Settings, settings
from app.services.server_settings_file import GitignoreMatcher, read_server_settings

PROTECTED_MESSAGE = "Ese archivo está protegido en craftpanel.txt. Sacalo de [protected] si querés que el panel lo cambie."


class ProtectedPathError(PermissionError):
    """The panel was asked to change a path the user protected."""

    status_code = 409

    def __init__(self, relative: str) -> None:
        self.relative = relative
        super().__init__(f"{PROTECTED_MESSAGE} ({relative})")


def _matcher(configured: Settings) -> GitignoreMatcher:
    return GitignoreMatcher(read_server_settings(configured).items("protected"))


def _relative(configured: Settings, path: Path) -> str | None:
    assert configured.server_directory is not None
    root = os.path.normcase(os.path.abspath(configured.server_directory))
    target = os.path.normcase(os.path.abspath(path))
    if target == root or not target.startswith(root.rstrip("\\/") + os.sep):
        return None
    return os.path.relpath(os.path.abspath(path), os.path.abspath(configured.server_directory)).replace("\\", "/")


def is_protected(path: Path, configured: Settings = settings, *, is_directory: bool | None = None) -> bool:
    """Whether ``path`` (inside the server folder) is covered by ``[protected]``."""
    relative = _relative(configured, path)
    if relative is None:
        return False
    matcher = _matcher(configured)
    if not matcher:
        return False
    directory = path.is_dir() if is_directory is None else is_directory
    return matcher.matches(relative, directory)


def require_not_protected(*paths: Path, configured: Settings = settings) -> None:
    """Raise :class:`ProtectedPathError` when any of ``paths`` is protected."""
    matcher = _matcher(configured)
    if not matcher:
        return
    for path in paths:
        relative = _relative(configured, path)
        if relative is not None and matcher.matches(relative, path.is_dir()):
            raise ProtectedPathError(relative)


def require_tree_not_protected(folder: Path, configured: Settings = settings) -> None:
    """Like :func:`require_not_protected`, for a folder and everything inside it (before deleting it)."""
    matcher = _matcher(configured)
    if not matcher:
        return
    require_not_protected(folder, configured=configured)
    for directory, folders, files in os.walk(folder, followlinks=False):
        base = Path(directory)
        for name in [*folders, *files]:
            relative = _relative(configured, base / name)
            if relative is not None and matcher.matches(relative, name in folders):
                raise ProtectedPathError(relative)


def unprotected(paths: Iterable[Path], configured: Settings = settings) -> list[Path]:
    """The subset of ``paths`` the panel may change."""
    matcher = _matcher(configured)
    if not matcher:
        return list(paths)
    kept: list[Path] = []
    for path in paths:
        relative = _relative(configured, path)
        if relative is None or not matcher.matches(relative, path.is_dir()):
            kept.append(path)
    return kept
