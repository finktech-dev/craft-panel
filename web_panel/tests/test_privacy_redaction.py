"""The console and problem logs never show the host's Windows user folder."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.privacy import redact_personal_paths
from app.services.server_process import MinecraftServerManager


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (r"Java home: C:\Users\Alex Smith\AppData\Local\jdk-21", r"Java home: C:\Users\<usuario>\AppData\Local\jdk-21"),
        ("Loading c:/users/alex/Desktop/mods/x.jar", "Loading c:/users/<usuario>/Desktop/mods/x.jar"),
        (r"two: D:\Users\bob\a and C:\USERS\carol\b", r"two: D:\Users\<usuario>\a and C:\USERS\<usuario>\b"),
        ("<Alex> hola, rey!", "<Alex> hola, rey!"),  # chat lines are left alone
        (r"D:\Dev\server\world\level.dat", r"D:\Dev\server\world\level.dat"),
        ("", ""),
    ],
)
def test_user_folder_is_replaced_in_paths_only(line: str, expected: str) -> None:
    assert redact_personal_paths(line) == expected


class _Sockets:
    async def broadcast_json(self, payload) -> None:
        self.last = payload


@pytest.mark.asyncio
async def test_console_lines_are_redacted_before_history_and_broadcast(tmp_path: Path) -> None:
    manager = object.__new__(MinecraftServerManager)
    sockets = _Sockets()
    manager.__init__(configured_settings=Settings(project_root=tmp_path), websocket_manager=sockets)

    await manager._record_log("stdout", r"Using C:\Users\Alex\AppData\Roaming\.minecraft")

    assert manager.history[-1]["message"] == r"Using C:\Users\<usuario>\AppData\Roaming\.minecraft"
    assert "Alex" not in str(sockets.last)
