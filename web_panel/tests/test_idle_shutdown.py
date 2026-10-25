"""``idle_shutdown``: the server stops itself after too few players for a while."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.api import server_automation
from app.services.server_process import ServerState
from tests.test_server_settings_file import settings_for, write_file


class FakeManager:
    def __init__(self) -> None:
        self.is_running = True
        self.state = ServerState.RUNNING
        self.lifecycle_operation: str | None = None
        self.players: list[str] = []
        self.commands: list[str] = []
        self.logs: list[str] = []
        self.stops = 0

    def get_online_players(self) -> list[dict]:
        return [{"username": name} for name in self.players]

    async def send_command(self, command: str) -> None:
        self.commands.append(command)

    async def log_system(self, message: str) -> None:
        self.logs.append(message)

    async def stop(self) -> bool:
        self.stops += 1
        return True


@pytest.fixture
def idle(tmp_path: Path, monkeypatch):
    configured = settings_for(tmp_path)
    manager = FakeManager()
    monkeypatch.setattr(server_automation, "settings", configured)
    monkeypatch.setattr(server_automation, "server_manager", manager)
    return configured, manager, server_automation.IdleShutdown()


@pytest.mark.asyncio
async def test_off_by_default(idle) -> None:
    configured, manager, watcher = idle
    for now in (0, 10_000, 100_000):
        await watcher.check(now)
    assert manager.stops == 0


@pytest.mark.asyncio
async def test_empty_server_stops_after_the_configured_time(idle) -> None:
    configured, manager, watcher = idle
    write_file(configured, "idle_shutdown = 10m\n")
    await watcher.check(0)
    await watcher.check(599)
    assert manager.stops == 0
    await watcher.check(600)
    assert manager.stops == 1
    assert any("nadie conectado durante 10 minutos" in line for line in manager.logs)
    # Nobody online, so nobody to warn in the chat.
    assert manager.commands == []


@pytest.mark.asyncio
async def test_enough_players_reset_the_countdown(idle) -> None:
    configured, manager, watcher = idle
    write_file(configured, "idle_shutdown = 10m\nidle_min_players = 2\n")
    manager.players = ["Steve"]
    await watcher.check(0)
    await watcher.check(500)
    manager.players = ["Steve", "Alex"]
    await watcher.check(550)
    manager.players = ["Steve"]
    await watcher.check(600)
    await watcher.check(1100)
    assert manager.stops == 0
    await watcher.check(1200)
    assert manager.stops == 1
    assert any("menos de 2 jugadores" in line for line in manager.logs)


@pytest.mark.asyncio
async def test_players_still_online_are_warned_once_in_the_chat(idle) -> None:
    configured, manager, watcher = idle
    write_file(configured, "idle_shutdown = 10m\nidle_min_players = 3\n")
    manager.players = ["Steve"]
    await watcher.check(0)
    await watcher.check(560)
    await watcher.check(580)
    assert len(manager.commands) == 1 and "1 minuto" in manager.commands[0]
    await watcher.check(600)
    assert manager.stops == 1


@pytest.mark.asyncio
async def test_never_counts_while_loading_or_during_another_operation(idle) -> None:
    configured, manager, watcher = idle
    write_file(configured, "idle_shutdown = 5m\n")
    manager.state = ServerState.STARTING
    await watcher.check(0)
    await watcher.check(1000)
    manager.state = ServerState.RUNNING
    manager.lifecycle_operation = "reinicio"
    await watcher.check(2000)
    manager.lifecycle_operation = None
    await watcher.check(3000)
    await watcher.check(3299)
    assert manager.stops == 0
    await watcher.check(3300)
    assert manager.stops == 1


@pytest.mark.asyncio
async def test_scheduler_runs_the_idle_check(tmp_path: Path) -> None:
    from app.services.scheduler_service import IDLE_CHECK_JOB_ID, SchedulerService

    scheduler = SchedulerService(settings_for(tmp_path))

    async def action() -> None:
        return None

    scheduler.set_idle_check_action(action)
    scheduler.start()
    try:
        assert scheduler.scheduler.get_job(IDLE_CHECK_JOB_ID) is not None
    finally:
        scheduler.shutdown()


@pytest.mark.parametrize(("text", "valid"), [("30m", True), ("4m", False), ("2d", False), ("", True)])
def test_idle_shutdown_limits(tmp_path: Path, text: str, valid: bool) -> None:
    from app.services.server_settings_file import parse_text

    parsed = parse_text(f"idle_shutdown = {text}\nidle_min_players = 0\n")
    fields = {problem.field for problem in parsed.problems}
    assert ("idle_shutdown" not in fields) == valid
    assert "idle_min_players" in fields
