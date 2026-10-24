"""Automations from craftpanel.txt: start with the panel, restart after crashes, daily restart, startup timeout."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api import endpoints_server, server_automation
from app.services.crash_guard import CrashRestartGuard
from app.services.external_server_service import ExternalServer
from tests.test_server_settings_file import settings_for, write_file


class FakeManager:
    def __init__(self, running: bool = False, operation: str | None = None) -> None:
        self.is_running = running
        self.lifecycle_operation = operation
        self.process_pid = None
        self.logs: list[str] = []
        self.listeners: list = []

    async def log_system(self, message: str) -> None:
        self.logs.append(message)

    def add_crash_listener(self, listener) -> None:
        self.listeners.append(listener)


class FakeDetector:
    def __init__(self, found: ExternalServer | None = None) -> None:
        self.found = found

    def detect(self, own_pid=None):
        return self.found


class Launches:
    def __init__(self) -> None:
        self.starts: list[str] = []
        self.restarts: list[tuple[int, str]] = []
        self.fail_with: str | None = None

    async def launch_start_job(self, *, dev_mode: bool = False, title: str = "") -> None:
        if self.fail_with:
            raise HTTPException(status_code=409, detail=self.fail_with)
        self.starts.append(title)

    async def launch_graceful_restart_job(self, countdown: int, *, title: str = "") -> None:
        self.restarts.append((countdown, title))


class FakePlayit:
    needs_setup = False


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    configured = settings_for(tmp_path)
    configured.playit_enabled = False
    manager = FakeManager()
    launches = Launches()
    launches.playit_service = FakePlayit()
    guard = CrashRestartGuard()
    monkeypatch.setattr(server_automation, "settings", configured)
    monkeypatch.setattr(server_automation, "server_manager", manager)
    monkeypatch.setattr(server_automation, "external_server_detector", FakeDetector())
    monkeypatch.setattr(server_automation, "crash_guard", guard)
    monkeypatch.setattr(server_automation, "_endpoints", lambda: launches)
    monkeypatch.setattr(server_automation, "CRASH_RESTART_DELAY_SECONDS", 0)
    return configured, manager, launches, guard, monkeypatch


# -- start_with_panel -----------------------------------------------------------


@pytest.mark.asyncio
async def test_start_with_panel_is_off_by_default(world) -> None:
    configured, manager, launches, *_ = world
    await server_automation.start_with_panel()
    assert launches.starts == []


@pytest.mark.asyncio
async def test_start_with_panel_starts_a_job(world) -> None:
    configured, manager, launches, *_ = world
    write_file(configured, "start_with_panel = true\n")
    await server_automation.start_with_panel()
    assert launches.starts == ["Encender el servidor al abrir el panel"]


@pytest.mark.asyncio
async def test_start_with_panel_skips_external_servers_and_pending_playit(world) -> None:
    configured, manager, launches, guard, monkeypatch = world
    write_file(configured, "start_with_panel = true\n")
    monkeypatch.setattr(server_automation, "external_server_detector", FakeDetector(ExternalServer(1, "java.exe", "server_directory", 25565)))
    await server_automation.start_with_panel()
    assert launches.starts == []

    monkeypatch.setattr(server_automation, "external_server_detector", FakeDetector())
    configured.playit_enabled = True
    launches.playit_service.needs_setup = True
    await server_automation.start_with_panel()
    assert launches.starts == []


# -- restart_on_crash ---------------------------------------------------------------


def test_guard_pauses_after_too_many_crashes_in_ten_minutes() -> None:
    guard = CrashRestartGuard()
    assert guard.allow_restart(2, now=0)
    assert guard.allow_restart(2, now=60)
    assert not guard.allow_restart(2, now=120)
    assert guard.paused_message and "3 veces" in guard.paused_message
    assert not guard.allow_restart(2, now=5000)  # stays paused until someone starts it by hand
    guard.reset()
    assert guard.allow_restart(2, now=6000)


def test_guard_forgets_crashes_older_than_the_window() -> None:
    guard = CrashRestartGuard()
    assert guard.allow_restart(1, now=0)
    assert guard.allow_restart(1, now=601)


@pytest.mark.asyncio
async def test_crash_restart_is_off_by_default(world) -> None:
    configured, manager, launches, *_ = world
    await server_automation.restart_after_crash()
    assert launches.starts == [] and manager.logs == []


@pytest.mark.asyncio
async def test_crash_restart_starts_a_tracked_job_and_logs_it(world) -> None:
    configured, manager, launches, *_ = world
    write_file(configured, "restart_on_crash = true\n")
    await server_automation.restart_after_crash()
    assert launches.starts == ["Volver a encender después de un cierre"]
    assert any("Lo volvemos a encender" in line for line in manager.logs)


@pytest.mark.asyncio
async def test_crash_loop_stops_restarting_and_shows_up_in_the_checks(world, monkeypatch) -> None:
    from app.services import safety_service

    configured, manager, launches, guard, _ = world
    write_file(configured, "restart_on_crash = true\nmax_crash_restarts = 2\n")
    for _ in range(3):
        await server_automation.restart_after_crash()

    assert len(launches.starts) == 2
    assert any("dejamos de volver a encenderlo" in line for line in manager.logs)
    items = safety_service.auto_restart_items(guard.paused_message)
    assert items and items[0].level == "warn"
    assert safety_service.auto_restart_items(None) == []


@pytest.mark.asyncio
async def test_crash_restart_never_runs_over_an_external_server_or_another_operation(world) -> None:
    configured, manager, launches, guard, monkeypatch = world
    write_file(configured, "restart_on_crash = true\n")
    monkeypatch.setattr(server_automation, "external_server_detector", FakeDetector(ExternalServer(1, "java.exe", "port", 25565)))
    await server_automation.restart_after_crash()
    assert launches.starts == []
    assert any("fuera del panel" in line for line in manager.logs)

    monkeypatch.setattr(server_automation, "external_server_detector", FakeDetector())
    manager.lifecycle_operation = "inicio"
    await server_automation.restart_after_crash()
    assert launches.starts == []


@pytest.mark.asyncio
async def test_crash_restart_reports_a_refused_start(world) -> None:
    configured, manager, launches, *_ = world
    write_file(configured, "restart_on_crash = true\n")
    launches.fail_with = "Revisá craftpanel.txt"
    await server_automation.restart_after_crash()
    assert any("No se pudo volver a encender" in line for line in manager.logs)


def test_manager_calls_listeners_only_for_crashes() -> None:
    import inspect

    from app.services.server_process import MinecraftServerManager

    source = inspect.getsource(MinecraftServerManager._watch_process)
    assert "ServerState.CRASHED and not self._dev_mode" in source
    assert "_crash_listeners" in source


# -- daily_restart ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_restart_skips_a_stopped_server(world) -> None:
    configured, manager, launches, *_ = world
    write_file(configured, "daily_restart = 05:30\n")
    await server_automation.daily_restart()
    assert launches.restarts == []


@pytest.mark.asyncio
async def test_daily_restart_warns_for_restart_warning(world) -> None:
    configured, manager, launches, *_ = world
    manager.is_running = True
    write_file(configured, "daily_restart = 05:30\nrestart_warning = 2m\n")
    await server_automation.daily_restart()
    assert launches.restarts == [(120, "Reinicio diario")]


def test_scheduler_adds_and_removes_the_daily_restart(tmp_path: Path) -> None:
    from app.services.scheduler_service import DAILY_RESTART_JOB_ID, SchedulerService

    configured = settings_for(tmp_path)
    scheduler = SchedulerService(configured)

    async def action() -> None:
        return None

    scheduler.set_daily_restart_action(action)
    scheduler.sync_with_settings_file()
    assert scheduler.scheduler.get_job(DAILY_RESTART_JOB_ID) is None

    write_file(configured, "daily_restart = 05:30\n")
    scheduler.sync_with_settings_file()
    job = scheduler.scheduler.get_job(DAILY_RESTART_JOB_ID)
    assert job is not None and "05:30" in job.name
    fields = {field.name: str(field) for field in job.trigger.fields}
    assert fields["hour"] == "5" and fields["minute"] == "30"

    write_file(configured, "daily_restart =\n")
    scheduler.sync_with_settings_file()
    assert scheduler.scheduler.get_job(DAILY_RESTART_JOB_ID) is None


# -- startup_timeout ------------------------------------------------------------------


def test_startup_timeout_replaces_the_fixed_wait(tmp_path: Path, monkeypatch) -> None:
    configured = settings_for(tmp_path)
    monkeypatch.setattr(endpoints_server, "settings", configured)
    assert endpoints_server._ready_timeout_seconds() == 300

    write_file(configured, "startup_timeout = 12m\n")
    assert endpoints_server._ready_timeout_seconds() == 720


@pytest.mark.asyncio
async def test_wait_until_ready_uses_the_configured_timeout(tmp_path: Path, monkeypatch) -> None:
    configured = settings_for(tmp_path)
    write_file(configured, "startup_timeout = 90s\n")
    monkeypatch.setattr(endpoints_server, "settings", configured)
    seen: list[float] = []

    class Manager:
        async def wait_until_ready(self, timeout_seconds: float) -> None:
            seen.append(timeout_seconds)

    monkeypatch.setattr(endpoints_server, "server_manager", Manager())

    class Reporter:
        done_message = ""

        def __call__(self, *args) -> None:
            return None

    assert await endpoints_server._wait_until_ready(Reporter())
    assert seen == [90.0]


@pytest.mark.asyncio
async def test_starting_by_hand_resets_the_crash_guard(monkeypatch) -> None:
    from app.services.crash_guard import crash_guard

    crash_guard.paused_message = "paused"

    async def fake_launch(**kwargs):
        from app.services.job_service import Job

        return Job.__new__(Job)

    monkeypatch.setattr(endpoints_server, "launch_start_job", fake_launch)
    monkeypatch.setattr(endpoints_server, "accepted", lambda job, message: message)

    assert await endpoints_server.start_server() == "Encendiendo el servidor."
    assert crash_guard.paused_message is None
