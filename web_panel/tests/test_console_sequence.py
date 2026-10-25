"""Console lines are numbered so a reconnecting browser only adds what it missed."""

from __future__ import annotations

from collections import deque

import pytest

from app.services.server_process import MinecraftServerManager


class RecordingSockets:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def broadcast_json(self, payload: dict) -> None:
        self.sent.append(payload)


def _manager() -> MinecraftServerManager:
    manager = object.__new__(MinecraftServerManager)
    manager._log_buffer = deque(maxlen=3)
    manager._log_seq = 0
    manager._ready_notified = True
    manager._dev_mode = True
    manager._online_players = {}
    manager._last_join_notified = {}
    manager._last_leave_notified = {}
    manager._last_death_notified = {}
    manager._replaying = False
    manager._saw_stopping = False
    manager._saw_crash = False
    manager._websocket_manager = RecordingSockets()
    return manager


@pytest.mark.asyncio
async def test_lines_are_numbered_in_order_and_history_keeps_the_numbers() -> None:
    manager = _manager()
    for text in ("uno", "dos", "tres", "cuatro"):
        await manager._record_log("stdout", text)

    sent = [payload["line"]["seq"] for payload in manager._websocket_manager.sent if payload.get("type") == "log"]
    assert sent == [1, 2, 3, 4]
    # The buffer keeps the last lines with their original numbers, so nothing is renumbered.
    assert [line["seq"] for line in manager.history] == [2, 3, 4]
