"""Regression coverage for races between start, stop, restart and kill."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api import endpoints_server
from app.core.config import Settings
from app.services.server_process import MinecraftServerManager, ServerBusyError


class FakeProcess:
    pid = 4242

    def __init__(self) -> None:
        self.returncode: int | None = None
        self._exited = asyncio.Event()

    def finish(self, code: int = 0) -> None:
        if self.returncode is None:
            self.returncode = code
            self._exited.set()

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode


class FakeManager(MinecraftServerManager):
    """Isolated manager whose process primitives are simulated."""

    def __new__(cls, *args, **kwargs):  # bypass the production singleton
        return object.__new__(cls)

    def __init__(self, tmp_path: Path, stop_delay: float | None = 0.05) -> None:
        super().__init__(configured_settings=Settings(project_root=tmp_path, graceful_stop_timeout_seconds=5))
        self.starts = 0
        self.stop_delay = stop_delay

    async def _start_process(self, dev_mode: bool) -> bool:
        if self.is_running:
            return False
        await asyncio.sleep(0.01)
        self.starts += 1
        self._process = FakeProcess()
        return True

    async def _request_stop(self) -> bool:
        process = self._process
        if not self.is_running or process is None:
            return False
        if self.stop_delay is not None:
            asyncio.get_running_loop().call_later(self.stop_delay, process.finish)
        return True

    async def _kill_process(self) -> bool:
        process = self._process
        if process is None or process.returncode is not None:
            return False
        process.finish(1)
        return True

    async def _record_log(self, stream: str, message: str) -> None:
        return None


@pytest.mark.asyncio
async def test_stop_is_rejected_while_restart_is_running(tmp_path: Path) -> None:
    manager = FakeManager(tmp_path)
    await manager.start()

    restart = asyncio.create_task(manager.restart())
    await asyncio.sleep(0.01)
    with pytest.raises(ServerBusyError):
        await manager.stop()

    assert await restart is True
    assert manager.is_running
    assert manager.starts == 2
    assert manager.lifecycle_operation is None


@pytest.mark.asyncio
async def test_concurrent_restarts_start_only_one_process(tmp_path: Path) -> None:
    manager = FakeManager(tmp_path)
    await manager.start()

    results = await asyncio.gather(manager.restart(), manager.restart(), return_exceptions=True)

    assert sum(result is True for result in results) == 1
    assert sum(isinstance(result, ServerBusyError) for result in results) == 1
    assert manager.starts == 2


@pytest.mark.asyncio
async def test_kill_during_restart_cancels_the_pending_start(tmp_path: Path) -> None:
    manager = FakeManager(tmp_path, stop_delay=None)  # /stop never completes on its own
    await manager.start()

    restart = asyncio.create_task(manager.restart())
    await asyncio.sleep(0.01)
    assert await manager.kill() is True

    assert await restart is False
    assert not manager.is_running
    assert manager.starts == 1


@pytest.mark.asyncio
async def test_shutdown_during_restart_does_not_raise_or_restart(tmp_path: Path) -> None:
    manager = FakeManager(tmp_path)
    await manager.start()

    restart = asyncio.create_task(manager.restart())
    await asyncio.sleep(0.01)
    await manager.shutdown()

    assert await restart is False
    assert not manager.is_running


class BusyManager:
    lifecycle_operation = "reinicio"


@pytest.mark.asyncio
@pytest.mark.parametrize("call", [endpoints_server.restart_server, endpoints_server.graceful_restart_server])
async def test_restart_endpoints_return_conflict_while_busy(monkeypatch, call) -> None:
    monkeypatch.setattr(endpoints_server, "server_manager", BusyManager())

    with pytest.raises(HTTPException) as error:
        await call()

    assert error.value.status_code == 409
