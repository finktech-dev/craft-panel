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


class FakeProcess:
    """Stands in for psutil.Process; each signal can be given or made to raise AccessDenied."""

    def __init__(
        self,
        pid: int,
        name: str = "java.exe",
        cwd: str | None = None,
        cmdline: list[str] | None = None,
        open_files: list[str] | None = None,
        denied: bool = False,
    ) -> None:
        self.pid = pid
        self._name = name
        self._cwd = cwd or str(Path.home())
        self._cmdline = cmdline or ["java", "-jar", "tool.jar"]
        self._open_files = open_files or []
        self._denied = denied
        self.info = {"pid": pid, "name": name}

    def _check(self) -> None:
        if self._denied:
            raise psutil.AccessDenied(self.pid)

    def name(self) -> str:
        return self._name

    def cwd(self) -> str:
        self._check()
        return self._cwd

    def cmdline(self) -> list[str]:
        self._check()
        return self._cmdline

    def open_files(self) -> list:
        self._check()
        return [psutil._common.popenfile(path, -1) for path in self._open_files]

    def children(self, recursive: bool = False) -> list:
        return []


class FakeConnection:
    def __init__(self, pid: int, port: int) -> None:
        self.pid = pid
        self.status = psutil.CONN_LISTEN
        self.laddr = psutil._common.addr("0.0.0.0", port)


def fake_machine(monkeypatch, processes: list[FakeProcess], listening: dict[int, int] | None = None) -> None:
    """Replace process listing, lookup and sockets with ``processes`` (pid -> port for listeners)."""
    by_pid = {process.pid: process for process in processes}

    def lookup(pid: int) -> FakeProcess:
        if pid not in by_pid:
            raise psutil.NoSuchProcess(pid)
        return by_pid[pid]

    connections = [FakeConnection(pid, port) for pid, port in (listening or {}).items()]
    monkeypatch.setattr(external_server_service.psutil, "process_iter", lambda attrs: iter(processes))
    monkeypatch.setattr(external_server_service.psutil, "Process", lookup)
    monkeypatch.setattr(external_server_service.psutil, "net_connections", lambda kind: connections)


def test_detects_java_running_in_server_directory(tmp_path: Path, monkeypatch) -> None:
    configured = _settings(tmp_path, _free_port())
    fake_machine(monkeypatch, [FakeProcess(999_991, cwd=str(configured.server_directory))])

    found = ExternalServerDetector(configured).detect()

    assert found is not None
    assert (found.pid, found.reason, found.kind) == (999_991, "server_directory", "is_our_server")
    assert "run.bat" in found.message
    assert "Se abrió desde la carpeta del servidor" in found.reasons
    assert found.can_terminate


def test_world_lock_is_the_strongest_signal(tmp_path: Path, monkeypatch) -> None:
    configured = _settings(tmp_path, _free_port())
    (configured.server_directory / "server.properties").write_text("level-name=Adventure\n", encoding="utf-8")
    lock = configured.server_directory / "Adventure" / "session.lock"
    fake_machine(
        monkeypatch,
        [
            FakeProcess(11, cwd=str(tmp_path / "elsewhere"), open_files=[str(lock)]),
            FakeProcess(12, cwd=str(configured.server_directory)),
        ],
    )

    found = ExternalServerDetector(configured).inspect()

    assert [server.pid for server in found] == [11, 12]
    assert found[0].reason == "world_lock"
    assert "Tiene abierto el mundo Adventure" in found[0].reasons
    assert found[0].can_terminate


def test_command_line_mentioning_the_server_folder_is_confident(tmp_path: Path, monkeypatch) -> None:
    configured = _settings(tmp_path, _free_port())
    jar = configured.server_directory / "server.jar"
    fake_machine(monkeypatch, [FakeProcess(21, cmdline=["java", "-Xmx4G", "-jar", str(jar), "nogui"])])

    found = ExternalServerDetector(configured).detect()

    assert found is not None and found.kind == "is_our_server" and found.reason == "command_line"
    assert "Su línea de inicio menciona la carpeta del servidor" in found.reasons


def test_a_sibling_folder_with_a_longer_name_does_not_match(tmp_path: Path, monkeypatch) -> None:
    configured = _settings(tmp_path, _free_port())
    sibling = Path(f"{configured.server_directory}2")
    fake_machine(monkeypatch, [FakeProcess(22, cmdline=["java", "-jar", str(sibling / "server.jar")])])

    assert ExternalServerDetector(configured).detect() is None


def test_user_hint_from_settings_file_is_confident(tmp_path: Path, monkeypatch) -> None:
    configured = _settings(tmp_path, _free_port())
    (configured.server_directory / "craftpanel.txt").write_text("[detect]\nmy-modpack-launcher\n", encoding="utf-8")
    fake_machine(monkeypatch, [FakeProcess(31, cmdline=["javaw", "-jar", "D:/games/My-Modpack-Launcher.jar"], name="javaw.exe")])

    found = ExternalServerDetector(configured).detect()

    assert found is not None and found.kind == "is_our_server" and found.reason == "hint"
    assert any("my-modpack-launcher" in reason for reason in found.reasons)


def test_minecraft_from_another_folder_on_our_port_cannot_be_closed(tmp_path: Path, monkeypatch) -> None:
    port = _free_port()
    configured = _settings(tmp_path, port)
    other = FakeProcess(41, cwd=str(tmp_path / "other-server"), cmdline=["java", "@user_jvm_args.txt", "@libraries/net/neoforged/neoforge/x/win_args.txt", "nogui"])
    fake_machine(monkeypatch, [other], listening={41: port})

    found = ExternalServerDetector(configured).detect()

    assert found is not None
    assert found.kind == "other_java_server"
    assert f"Usa el puerto {port}" in found.reasons
    assert any("Arranca como un servidor de Minecraft" in reason for reason in found.reasons)
    assert not found.can_terminate
    assert "otra carpeta" in found.message


def test_minecraft_from_another_folder_elsewhere_is_ignored(tmp_path: Path, monkeypatch) -> None:
    configured = _settings(tmp_path, _free_port())
    fake_machine(monkeypatch, [FakeProcess(42, cwd=str(tmp_path / "other"), cmdline=["java", "@user_jvm_args.txt", "nogui"])])

    assert ExternalServerDetector(configured).detect() is None


def test_other_program_on_port_is_explained(tmp_path: Path, monkeypatch) -> None:
    port = _free_port()
    configured = _settings(tmp_path, port)
    fake_machine(monkeypatch, [FakeProcess(51, name="game.exe")], listening={51: port})

    found = ExternalServerDetector(configured).detect()

    assert found is not None and found.kind == "other_program_on_port"
    assert "Es otro programa (game.exe), no un servidor de Minecraft" in found.reasons
    assert not found.can_terminate
    assert str(port) in found.explanation and "Lo que encontramos" in found.explanation


def test_access_denied_signals_are_skipped(tmp_path: Path, monkeypatch) -> None:
    port = _free_port()
    configured = _settings(tmp_path, port)
    fake_machine(monkeypatch, [FakeProcess(61, denied=True)], listening={61: port})

    found = ExternalServerDetector(configured).detect()

    # Unknown origin: it is in the way, but the panel is not sure enough to close it.
    assert found is not None and found.kind == "other_program_on_port" and not found.can_terminate


def test_the_panel_own_tree_is_never_reported(tmp_path: Path, monkeypatch) -> None:
    configured = _settings(tmp_path, _free_port())
    fake_machine(monkeypatch, [FakeProcess(71, cwd=str(configured.server_directory))])

    assert ExternalServerDetector(configured).detect(own_pid=71) is None


def test_open_files_is_only_asked_of_java_and_port_holders(tmp_path: Path, monkeypatch) -> None:
    configured = _settings(tmp_path, _free_port())
    asked: list[int] = []

    class Watched(FakeProcess):
        def open_files(self) -> list:
            asked.append(self.pid)
            return []

    fake_machine(monkeypatch, [Watched(81, name="chrome.exe"), Watched(82, name="explorer.exe"), Watched(83)])

    ExternalServerDetector(configured).inspect()

    assert asked == [83]


@pytest.mark.asyncio
async def test_external_endpoint_lists_reasons(monkeypatch) -> None:
    from app.api import endpoints_server

    found = ExternalServer(
        pid=4321, name="java.exe", reason="world_lock", port=25565, kind="is_our_server",
        reasons=("Tiene abierto el mundo world", "Usa el puerto 25565"),
    )
    monkeypatch.setattr(endpoints_server, "server_manager", _StoppedManager())
    monkeypatch.setattr(endpoints_server, "external_server_detector", _Detector(found))

    info = await endpoints_server.external_server()

    assert info.detected and info.kind == "is_our_server" and info.can_terminate
    assert info.reasons == ["Tiene abierto el mundo world", "Usa el puerto 25565"]


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
