"""Detect servers started outside the panel so it never launches a second instance."""

from __future__ import annotations

import asyncio
import contextlib
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import psutil
import pytest

from app.core.config import Settings
from app.services import external_server_service
from app.services.external_server_service import ExternalServer, ExternalServerDetector
from app.services.server_process import ExternalServerRunningError, MinecraftServerManager

_LISTENER = (
    "import socket, sys, time\n"
    "s = socket.socket(); s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen()\n"
    "import os\n"
    "print('ready', os.getpid(), flush=True); time.sleep(120)\n"
)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _settings(tmp_path: Path, port: int) -> Settings:
    configured = Settings(project_root=tmp_path)
    assert configured.server_directory is not None
    configured.server_directory.mkdir(parents=True)
    (configured.server_directory / "server.properties").write_text(f"server-port={port}\n", encoding="utf-8")
    return configured


class ListenerProcess:
    """The process that really holds the port.

    A Windows venv's python.exe is a launcher that spawns the real interpreter,
    so Popen.pid is not the listening process; the child reports its own PID.
    """

    def __init__(self, popen: subprocess.Popen[str], pid: int) -> None:
        self._popen = popen
        self.pid = pid

    def poll(self) -> int | None:
        try:
            alive = psutil.Process(self.pid).status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            alive = False
        return None if alive else 0

    def stop(self) -> None:
        with contextlib.suppress(psutil.NoSuchProcess):
            psutil.Process(self.pid).kill()
        if self._popen.poll() is None:
            self._popen.kill()
        self._popen.wait()


@pytest.fixture
def listener() -> Iterator[tuple[ListenerProcess, int]]:
    port = _free_port()
    popen = subprocess.Popen([sys.executable, "-c", _LISTENER, str(port)], stdout=subprocess.PIPE, text=True)
    assert popen.stdout is not None
    status, _, pid = popen.stdout.readline().strip().partition(" ")
    assert status == "ready"
    process = ListenerProcess(popen, int(pid))
    yield process, port
    process.stop()


def test_server_port_defaults_and_reads_properties(tmp_path: Path) -> None:
    configured = _settings(tmp_path, 25570)
    assert ExternalServerDetector(configured).server_port() == 25570
    (configured.server_directory / "server.properties").write_text("server-port=nope\n", encoding="utf-8")
    assert ExternalServerDetector(configured).server_port() == 25565


def test_detects_foreign_listener_on_server_port(tmp_path: Path, listener) -> None:
    process, port = listener
    detector = ExternalServerDetector(_settings(tmp_path, port))

    found = detector.detect()

    assert found is not None
    assert found.pid == process.pid
    assert found.reason == "port"
    assert str(port) in found.message


def test_ignores_the_panel_own_process_tree(tmp_path: Path, listener) -> None:
    process, port = listener
    detector = ExternalServerDetector(_settings(tmp_path, port))

    assert detector.detect(own_pid=process.pid) is None


def test_flags_orphan_from_previous_panel_session(tmp_path: Path, listener) -> None:
    process, port = listener
    detector = ExternalServerDetector(_settings(tmp_path, port))
    detector.remember_panel_process(process.pid)

    found = detector.detect()

    assert found is not None and found.reason == "previous_panel_session"


def test_terminate_refuses_programs_that_are_not_java(tmp_path: Path, listener) -> None:
    process, port = listener
    detector = ExternalServerDetector(_settings(tmp_path, port))

    # The listener is a Python process holding the port: never kill it.
    assert detector.terminate(process.pid) is False
    assert process.poll() is None


def test_terminate_only_kills_currently_detected_java(tmp_path: Path, listener, monkeypatch) -> None:
    process, port = listener
    detector = ExternalServerDetector(_settings(tmp_path, port))
    original_detect = detector.detect

    def as_java(own_pid=None):
        found = original_detect(own_pid)
        return None if found is None else external_server_service.ExternalServer(
            pid=found.pid, name="java.exe", reason=found.reason, port=found.port
        )

    monkeypatch.setattr(detector, "detect", as_java)
    assert detector.terminate(process.pid + 100_000) is False
    assert detector.terminate(process.pid, own_pid=process.pid) is False
    assert process.poll() is None

    assert detector.terminate(process.pid) is True
    deadline = time.monotonic() + 10
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert process.poll() is not None


def test_detects_java_running_in_server_directory(tmp_path: Path, monkeypatch) -> None:
    configured = _settings(tmp_path, _free_port())
    server_directory = configured.server_directory

    class FakeJava:
        info = {"pid": 999_991, "name": "java.exe"}

        def cwd(self) -> str:
            return str(server_directory)

    monkeypatch.setattr(external_server_service.psutil, "process_iter", lambda attrs: iter([FakeJava()]))

    found = ExternalServerDetector(configured).detect()

    assert found is not None
    assert (found.pid, found.reason) == (999_991, "server_directory")
    assert "run.bat" in found.message


class _StoppedManager:
    is_running = False
    lifecycle_operation = None
    process_pid = None


class _Detector:
    def __init__(self, found: ExternalServer) -> None:
        self.found = found
        self.terminated = False

    def detect(self, own_pid=None):
        return self.found

    def terminate(self, pid, own_pid=None):
        self.terminated = True
        return True


@pytest.mark.asyncio
async def test_start_endpoint_refuses_before_creating_a_job(monkeypatch) -> None:
    from fastapi import HTTPException

    from app.api import endpoints_server

    found = ExternalServer(pid=4321, name="java.exe", reason="server_directory", port=25565)
    monkeypatch.setattr(endpoints_server, "server_manager", _StoppedManager())
    monkeypatch.setattr(endpoints_server, "external_server_detector", _Detector(found))
    monkeypatch.setattr(endpoints_server, "start_job", lambda *a, **k: pytest.fail("no job may start"))

    with pytest.raises(HTTPException) as error:
        await endpoints_server.start_server()

    assert error.value.status_code == 409
    assert "run.bat" in error.value.detail


@pytest.mark.asyncio
async def test_terminate_endpoint_explains_non_java_port_holders(monkeypatch) -> None:
    from fastapi import HTTPException

    from app.api import endpoints_server

    detector = _Detector(ExternalServer(pid=777, name="python.exe", reason="port", port=25565))
    monkeypatch.setattr(endpoints_server, "server_manager", _StoppedManager())
    monkeypatch.setattr(endpoints_server, "external_server_detector", detector)

    with pytest.raises(HTTPException) as error:
        await endpoints_server.terminate_external_server(endpoints_server.ExternalServerTerminateRequest(pid=777, confirm=True))

    assert error.value.status_code == 409
    assert "no es un servidor de Minecraft" in error.value.detail
    assert detector.terminated is False


@pytest.mark.asyncio
async def test_start_refuses_when_external_server_is_running(tmp_path: Path, listener) -> None:
    _, port = listener
    configured = _settings(tmp_path, port)
    configured.server_start_script.parent.mkdir(parents=True, exist_ok=True)
    configured.server_start_script.write_text("echo never runs\n", encoding="utf-8")
    manager = object.__new__(MinecraftServerManager)
    manager.__init__(configured_settings=configured)

    with pytest.raises(ExternalServerRunningError):
        await manager.start()

    assert not manager.is_running
    assert psutil.pid_exists(listener[0].pid)
    await asyncio.sleep(0)
