"""What the server folder says about its past, read from files only (no Java, no network).

- ``new``: there is nothing to start yet (no start script).
- ``installed``: it can start, but no world was ever created.
- ``played``: a world exists, so the server has been used before.

The wizard uses it to skip what is already done, and the login to decide
whether to open the wizard or the home screen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.core.config import Settings
from app.core.path_safety import is_safe_component

HistoryPhase = Literal["new", "installed", "played"]


@dataclass(frozen=True, slots=True)
class ServerHistory:
    phase: HistoryPhase
    world_name: str | None = None
    last_played_at: datetime | None = None
    known_players: int = 0


def _level_name(properties_text: str) -> str:
    for line in properties_text.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "level-name" and value.strip():
            return value.strip()
    return "world"


def read_server_history(configured: Settings) -> ServerHistory:
    root = configured.server_directory
    if root is None:
        return ServerHistory("new")
    try:
        can_start = configured.server_start_script.is_file()
    except (OSError, ValueError):
        can_start = False
    if not can_start:
        return ServerHistory("new")

    try:
        level = _level_name((root / "server.properties").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        level = "world"
    # level-name may hold a sub-path; only look for plain folder names inside the server.
    level_dat = root / level / "level.dat" if is_safe_component(level) else None
    try:
        modified = level_dat.stat().st_mtime if level_dat is not None else None
    except OSError:
        modified = None
    if modified is None:
        return ServerHistory("installed")

    try:
        cache = json.loads((root / "usercache.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = []
    return ServerHistory(
        "played",
        world_name=level,
        last_played_at=datetime.fromtimestamp(modified, UTC),
        known_players=len(cache) if isinstance(cache, list) else 0,
    )


def needs_setup(configured: Settings, server_running: bool) -> bool:
    """Open the wizard after login only while the server was never played and is not running."""
    return not server_running and read_server_history(configured).phase != "played"
