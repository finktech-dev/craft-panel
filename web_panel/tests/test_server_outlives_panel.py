"""The server runs detached from the panel: its console goes to a file, a restarted panel
takes it back, commands then go through RCON, and closing the panel stops it only when wanted."""

from __future__ import annotations

import asyncio
import json
import socket
import struct
import sys
import textwrap
import threading
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from app.core.config import Settings
from app.services import rcon
from app.services.external_server_service import ExternalServerDetector
from app.services.server_process import MinecraftServerManager, ServerState
from app.services.server_properties_service import ServerPropertiesService
from tests.test_server_settings_file import write_file

# --- A fake RCON server speaking the real protocol ---------------------------------


class FakeRcon:
    def __init__(self, password: str, answers: dict[str, str]) -> None:
        self.password = password
        self.answers = answers
        self.commands: list[str] = []
        self._socket = socket.socket()
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen()
        self.port = self._socket.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    @staticmethod
    def _send(conn, request_id: int, kind: int, payload: str) -> None:
        body = struct.pack("<ii", request_id, kind) + payload.encode() + b"\x00\x00"
        conn.sendall(struct.pack("<i", len(body)) + body)

    @staticmethod
    def _read(conn):
        header = conn.recv(4)
        if len(header) < 4:
            return None
        (length,) = struct.unpack("<i", header)
        body = b""
        while len(body) < length:
            body += conn.recv(length - len(body))
        request_id, kind = struct.unpack("<ii", body[:8])
        return request_id, kind, body[8:-2].decode()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._socket.accept()
            except OSError:
                return
            with conn:
                packet = self._read(conn)
                if packet is None:
                    continue
                request_id, _, password = packet
                self._send(conn, request_id if password == self.password else -1, 2, "")
                if password != self.password:
                    continue
                packet = self._read(conn)
                if packet is None:
                    continue
                request_id, _, command = packet
                self.commands.append(command)
                answer = self.answers.get(command, "")
                for start in range(0, max(len(answer), 1), 4096):
                    self._send(conn, request_id, 0, answer[start:start + 4096])

    def close(self) -> None:
        self._socket.close()


def test_rcon_client_sends_commands_and_joins_long_answers() -> None:
    long_answer = "x" * 5000
    server = FakeRcon("secreto", {"list": "There are 1 of a max of 10 players online: Steve", "dump": long_answer})
    try:
        settings = rcon.RconSettings(server.port, "secreto")
        assert rcon.run_command(settings, "/list").endswith("Steve")
        assert rcon.run_command(settings, "dump") == long_answer
        assert server.commands == ["list", "dump"]  # the leading slash is dropped
        with pytest.raises(rcon.RconError):
            rcon.run_command(rcon.RconSettings(server.port, "otra"), "list")
    finally:
        server.close()


def test_rcon_is_turned_on_once_and_an_owner_setup_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "server.properties"
    path.write_text("#comentario\nmotd=Hola\nenable-rcon=false\n", encoding="utf-8")
    updates = rcon.updates_to_enable(rcon.read_properties(path))
    assert updates and updates["enable-rcon"] == "true" and len(updates["rcon.password"]) >= 24
    rcon.write_properties(path, updates)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("#comentario\nmotd=Hola\nenable-rcon=true\n")
    assert rcon.updates_to_enable(rcon.read_properties(path)) is None
    assert rcon.rcon_settings(rcon.read_properties(path)).port == 25575


@pytest.mark.asyncio
async def test_properties_editor_never_shows_or_changes_the_rcon_password(tmp_path: Path) -> None:
    configured = Settings(project_root=tmp_path)
    configured.server_directory.mkdir(parents=True)
    (configured.server_directory / "server.properties").write_text("enable-rcon=true\nrcon.password=supersecreto\n", encoding="utf-8")
    service = ServerPropertiesService(configured, SimpleNamespace(is_running=False))
    response = await service.get_properties_response()
    assert "supersecreto" not in response.model_dump_json()
    with pytest.raises(ValueError):
        service._validate_updates({"rcon.password": "nueva"})


def test_a_reused_pid_is_never_taken_for_our_server(tmp_path: Path) -> None:
    configured = Settings(project_root=tmp_path)
    detector = ExternalServerDetector(configured)
    me = psutil.Process()
    detector.remember_panel_process(me.pid)
    assert detector.remembered_process().pid == me.pid
    detector.pid_file.write_text(json.dumps({"pid": me.pid, "created": me.create_time() - 500}), encoding="utf-8")
    assert detector.remembered_process() is None


# --- A real detached process standing in for Minecraft ------------------------------

FAKE_SERVER = textwrap.dedent(
    """
    import sys, time
    print("[Server thread/INFO]: Starting minecraft server", flush=True)
    print("[Server thread/INFO]: Done (1.0s)! For help, type help", flush=True)
    for raw in sys.stdin:
        command = raw.strip()
        print(f"[Server thread/INFO]: got {command}", flush=True)
        if command.lstrip("/") == "stop":
            print("[Server thread/INFO]: Stopping the server", flush=True)
            sys.exit(0)
    # No more input (the panel that started it is gone): keep running like Minecraft does.
    while True:
        time.sleep(0.2)
    """
)


class IsolatedManager(MinecraftServerManager):
    """A manager outside the production singleton, like a fresh panel session."""

    def __new__(cls, *args, **kwargs):
        return object.__new__(cls)

    def __init__(self, configured: Settings) -> None:
        self._initialized = False
        super().__init__(configured, SimpleNamespace(broadcast_json=self._ignore))

    @staticmethod
    async def _ignore(payload) -> None:
        return None


@pytest.fixture
def fake_server(tmp_path: Path, monkeypatch):
    configured = Settings(project_root=tmp_path)
    configured.server_directory.mkdir(parents=True)
    configured.panel_directory.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "fake_server.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    configured.server_start_script.write_text("rem fake\n", encoding="utf-8")
    monkeypatch.setattr(Settings, "server_start_command", property(lambda self: [sys.executable, "-u", str(script)]))
    monkeypatch.setattr("app.services.server_process.server_environment", lambda configured: None)
    monkeypatch.setattr("app.services.server_process.discord_service", SimpleNamespace(
        **{name: (lambda *a, **k: asyncio.sleep(0)) for name in (
            "send_server_starting", "send_server_started", "send_server_stopped", "send_crash",
            "send_player_join", "send_player_leave", "send_player_death", "send_advancement")}
    ))
    started: list[psutil.Process] = []
    yield configured, started
    for process in started:
        for member in [*process.children(recursive=True), process] if process.is_running() else []:
            try:
                member.kill()
            except psutil.Error:
                pass


def _no_external(manager: MinecraftServerManager) -> None:
    manager._external_detector.detect = lambda *args, **kwargs: None


async def _wait_for(predicate, timeout: float = 15.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out")
        await asyncio.sleep(0.1)


def _messages(manager: MinecraftServerManager) -> list[str]:
    return [line["message"] for line in manager.history]


@pytest.mark.asyncio
async def test_console_goes_to_a_file_and_a_restarted_panel_takes_the_server_back(fake_server) -> None:
    configured, started = fake_server
    first = IsolatedManager(configured)
    _no_external(first)
    assert await first.start()
    started.append(psutil.Process(first.process_pid))
    await first.wait_until_ready(timeout_seconds=15)
    await first.send_command("hola")
    await _wait_for(lambda: any("got hola" in message for message in _messages(first)))
    assert "got hola" in first.console_log_path.read_text(encoding="utf-8")

    # A new panel session: it finds the same process and follows its console.
    second = IsolatedManager(configured)
    _no_external(second)
    assert await second.adopt_running_server()
    assert second.is_running and second.state == ServerState.RUNNING
    assert any("got hola" in message for message in _messages(second))
    assert "Lo retomamos" in _messages(second)[-1]

    # The server ends with a /stop (sent here through the first session's input): not a crash.
    await first.send_command("stop")
    await _wait_for(lambda: not second.is_running)
    await _wait_for(lambda: second.state != ServerState.RUNNING)
    assert second.state == ServerState.STOPPED
    assert any("Stopping the server" in message for message in _messages(second))


@pytest.mark.asyncio
async def test_without_stdin_commands_go_through_rcon(fake_server) -> None:
    configured, _ = fake_server
    server = FakeRcon("clave-larga", {"say hola": "", "list": "There are 2 of a max of 10 players online: Steve, Alex"})
    try:
        write_props = configured.server_directory / "server.properties"
        write_props.write_text(f"enable-rcon=true\nrcon.port={server.port}\nrcon.password=clave-larga\n", encoding="utf-8")
        manager = IsolatedManager(configured)
        manager._process = SimpleNamespace(pid=1, returncode=None, stdin=None)
        await manager.send_command("/say hola")
        assert server.commands == ["say hola"]
        assert await manager._refresh_players_from_rcon()
        assert [player["username"] for player in manager.get_online_players()] == ["Steve", "Alex"]
    finally:
        server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(("setting", "stops"), [("stop_with_panel = true\n", True), ("stop_with_panel = false\n", False), ("", True)])
async def test_closing_the_panel_stops_the_server_only_when_wanted(fake_server, setting: str, stops: bool) -> None:
    configured, _ = fake_server
    write_file(configured, setting)
    manager = IsolatedManager(configured)
    requested: list[bool] = []

    async def fake_request_stop() -> bool:
        requested.append(True)
        manager._process.returncode = 0
        return True

    manager._process = SimpleNamespace(pid=1, returncode=None, stdin=None, wait=lambda: asyncio.sleep(0))
    manager._request_stop = fake_request_stop
    await manager.shutdown()
    assert bool(requested) is stops


def test_closing_the_window_asks_the_server_to_stop_through_rcon_or_ctrl_c(fake_server, monkeypatch) -> None:
    configured, _ = fake_server
    server = FakeRcon("clave-larga", {})
    pressed: list[int] = []
    monkeypatch.setattr("app.services.server_process.request_graceful_stop", lambda pid: pressed.append(pid) or True)
    try:
        props = configured.server_directory / "server.properties"
        props.write_text(f"enable-rcon=true\nrcon.port={server.port}\nrcon.password=clave-larga\n", encoding="utf-8")
        manager = IsolatedManager(configured)
        manager._process = SimpleNamespace(pid=4242, returncode=None)
        manager.stop_for_closing_window()
        assert server.commands == ["stop"] and pressed == []

        # Still loading (RCON not up): Ctrl+C in the server's own console instead.
        props.write_text("enable-rcon=false\n", encoding="utf-8")
        manager.stop_for_closing_window()
        assert pressed == [4242]

        # stop_with_panel = false: nothing is sent.
        write_file(configured, "stop_with_panel = false\n")
        manager.stop_for_closing_window()
        assert pressed == [4242] and server.commands == ["stop"]
    finally:
        server.close()
