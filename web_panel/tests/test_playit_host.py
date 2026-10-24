"""The official Playit app for Windows: detection, start, and reading its address."""

from __future__ import annotations

import io
import json
import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import psutil
import pytest

from app.api import endpoints_tunnel
from app.core.config import Settings
from app.core.net_safety import PLAYIT_API_HOSTS
from app.services import playit_host
from app.services.playit_host import (
    PIPE_PATH,
    PlayitAddressError,
    PlayitTunnel,
    detect_playit_host,
    pick_minecraft_address,
    read_official_secret,
    read_tunnels_from_api,
    read_tunnels_from_pipe,
    tunnels_from_rundata,
)
from app.services.playit_service import PlayitService

FAKE_SECRET = "0123456789abcdef" * 4
# Shape of Playit's /v1/agents/rundata answer (playit-agent packages/api_client), with made-up values.
RUNDATA_SAMPLE = {
    "status": "success",
    "data": {
        "agent_id": "0b6f2c1e-1111-4222-8333-444455556666",
        "tunnels": [
            {
                "id": "11111111-aaaa-4bbb-8ccc-dddddddddddd",
                "internal_id": 1,
                "name": "Web",
                "display_address": "web-example.at.ply.gg:41000",
                "port_type": "tcp",
                "port_count": 1,
                "tunnel_type": None,
                "tunnel_type_display": "TCP",
                "agent_config": {"fields": [{"name": "local_ip", "value": "127.0.0.1"}, {"name": "local_port", "value": "8080"}]},
                "disabled_reason": None,
            },
            {
                "id": "9a8b7c6d-aaaa-4bbb-8ccc-dddddddddddd",
                "internal_id": 2,
                "name": "Minecraft Java",
                "display_address": "example-words.gl.joinmc.link",
                "port_type": "tcp",
                "port_count": 1,
                "tunnel_type": "minecraft-java",
                "tunnel_type_display": "Minecraft Java",
                "agent_config": {"fields": [{"name": "local_ip", "value": "127.0.0.1"}, {"name": "local_port", "value": "25565"}]},
                "disabled_reason": None,
            },
        ],
        "pending": [],
        "notices": [],
        "permissions": {"is_self_managed": False, "has_premium": False, "account_status": "verified"},
    },
}


class FakeService:
    def __init__(self, status: str, start_type: str = "manual") -> None:
        self._status, self._start_type = status, start_type

    def status(self) -> str:
        return self._status

    def start_type(self) -> str:
        return self._start_type


def _installed_app(tmp_path: Path) -> dict[str, str]:
    binary = tmp_path / "Program Files" / "playit_gg" / "bin" / "playit.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"MZ")
    return {"ProgramFiles": str(tmp_path / "Program Files"), "ProgramData": str(tmp_path / "ProgramData")}


def _missing(_name: str):
    raise psutil.NoSuchProcess(pid=None, name="playitd", msg="service does not exist")


# --- Detection --------------------------------------------------------------------------------


def test_running_service_is_detected_with_psutil(tmp_path: Path) -> None:
    status = detect_playit_host(system_name="Windows", environ=_installed_app(tmp_path), service_get=lambda _n: FakeService("running"))

    assert status.state == "running" and status.service_installed and status.app_installed
    assert status.starts_automatically is False


def test_stopped_service_reports_its_start_type(tmp_path: Path) -> None:
    status = detect_playit_host(
        system_name="Windows", environ=_installed_app(tmp_path), service_get=lambda _n: FakeService("stopped", "automatic")
    )

    assert status.state == "stopped" and status.starts_automatically is True


def test_missing_service_and_app_is_not_installed(tmp_path: Path) -> None:
    status = detect_playit_host(system_name="Windows", environ={"ProgramFiles": str(tmp_path)}, service_get=_missing)

    assert status.state == "not_installed" and not status.service_installed and not status.app_installed


def test_installed_app_without_its_service_still_counts_as_installed(tmp_path: Path) -> None:
    status = detect_playit_host(system_name="Windows", environ=_installed_app(tmp_path), service_get=_missing)

    assert status.state == "stopped" and status.app_installed and not status.service_installed


@pytest.mark.parametrize(
    ("stdout", "returncode", "expected"),
    [
        ("NOMBRE_SERVICIO: playitd\n        TIPO               : 10  WIN32_OWN_PROCESS\n        ESTADO             : 4  RUNNING\n"
         "        CÓD_SALIDA_WIN32   : 0  (0x0)\n", 0, "running"),
        ("SERVICE_NAME: playitd\n        TYPE               : 10  WIN32_OWN_PROCESS\n        STATE              : 1  STOPPED\n", 0, "stopped"),
        ("", 1060, "not_installed"),
    ],
)
def test_sc_fallback_does_not_depend_on_the_windows_language(tmp_path: Path, stdout: str, returncode: int, expected: str) -> None:
    def denied(_name):
        raise psutil.AccessDenied()

    def run(args, **_kwargs):
        return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr="")

    status = detect_playit_host(system_name="Windows", environ={"ProgramFiles": str(tmp_path)}, service_get=denied, run=run)

    assert status.state == expected


def test_other_systems_never_query_windows_services() -> None:
    def explode(*_args, **_kwargs):
        raise AssertionError("must not be called")

    assert detect_playit_host(system_name="Linux", service_get=explode, run=explode).state == "not_installed"


# --- PlayitService integration -----------------------------------------------------------------


def _service(tmp_path: Path, monkeypatch, getter) -> PlayitService:
    monkeypatch.setattr("app.services.playit_service.platform.system", lambda: "Windows")
    monkeypatch.setattr("app.services.playit_service.psutil.win_service_get", getter, raising=False)
    for name, value in _installed_app(tmp_path / "host").items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("ProgramW6432", raising=False)
    return PlayitService(Settings(project_root=tmp_path / "panel"))


def test_running_official_app_needs_no_link_and_no_own_agent(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch, lambda _n: FakeService("running"))

    assert service.needs_setup is False and service.uses_external_agent is True
    assert service.status().external_agent == "running"
    assert service.status().message == "Playit está instalado y funcionando."


@pytest.mark.asyncio
async def test_start_turns_on_a_stopped_official_app_instead_of_asking_to_link(tmp_path: Path, monkeypatch) -> None:
    state = {"status": "stopped"}
    service = _service(tmp_path, monkeypatch, lambda _n: FakeService(state["status"]))
    started: list[bool] = []

    def fake_start(*_args, **_kwargs):
        started.append(True)
        state["status"] = "running"
        return True

    monkeypatch.setattr("app.services.playit_service.start_official_service", fake_start)

    assert service.needs_setup is True and service.can_start_external_agent is True
    status = await service.start()

    assert started == [True]
    assert status.external_agent == "running" and status.is_running
    assert service._process is None  # the panel did not start a second agent


@pytest.mark.asyncio
async def test_start_explains_how_to_open_playit_when_it_does_not_start(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch, lambda _n: FakeService("stopped"))
    monkeypatch.setattr("app.services.playit_service.start_official_service", lambda *_a, **_k: False)
    monkeypatch.setattr("app.services.playit_service.asyncio.sleep", _no_sleep)

    with pytest.raises(Exception, match="Abrí Playit.gg desde el menú Inicio"):
        await service.start()


async def _no_sleep(_seconds: float) -> None:
    return None


def test_official_start_command_is_the_apps_own_cli(tmp_path: Path) -> None:
    environ = _installed_app(tmp_path)
    calls: list[tuple] = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    assert playit_host.start_official_service(environ, run) is True
    assert calls[0][0][1:] == ("start",) and calls[0][0][0].endswith("playit.exe")
    assert playit_host.start_official_service({"ProgramFiles": str(tmp_path / "none")}, run) is False


# --- Address from the local status pipe -----------------------------------------------------------


class FakePipe(io.RawIOBase):
    def __init__(self, replies: list[dict]) -> None:
        self._out = io.BytesIO(b"".join(json.dumps(reply).encode() + b"\n" for reply in replies))
        self.written = b""

    def readable(self) -> bool:
        return True

    def writable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        return self._out.read(min(size, 7))  # small chunks, like a real pipe

    def write(self, data: bytes) -> int:
        self.written += data
        return len(data)


HELLO = {"message_kind": "hello", "data": {"protocol": {"ipc_version": 2, "capabilities": ["lifecycle_state"]}}}


def _state(lifecycle: dict) -> dict:
    return {"message_kind": "response", "data": {"ipc_version": 2, "request_id": 1, "response": {"type": "state", "data": lifecycle}}}


def test_pipe_reads_tunnels_with_a_read_only_request() -> None:
    lifecycle = {
        "state": "running",
        "data": {
            "version": "1.0.12",
            "tunnels": [
                {"display_address": "web-example.at.ply.gg:41000", "destination": "127.0.0.1:8080", "is_disabled": False, "disabled_reason": None},
                {"display_address": "example-words.gl.joinmc.link", "destination": "127.0.0.1:25565", "is_disabled": False, "disabled_reason": None},
            ],
            "pending_tunnels": [], "notices": [], "account_status": "verified", "agent_id": "x", "login_link": None, "start_time": 0,
        },
    }
    event = {"message_kind": "event", "data": {"ipc_version": 2, "event": {"type": "stats", "data": {}}}}
    pipe = FakePipe([HELLO, event, _state(lifecycle)])
    opened: list[str] = []

    def opener(path: str):
        opened.append(path)
        return pipe

    tunnels = read_tunnels_from_pipe(opener)

    assert opened == [PIPE_PATH]
    assert json.loads(pipe.written) == {"ipc_version": 2, "request_id": 1, "request": {"type": "get_state"}}
    assert pick_minecraft_address(tunnels, 25565) == "example-words.gl.joinmc.link"


def test_pipe_reports_an_unlinked_app_in_plain_words() -> None:
    pipe = FakePipe([HELLO, _state({"state": "waiting_for_secret"})])

    with pytest.raises(PlayitAddressError, match="todavía no está vinculado"):
        read_tunnels_from_pipe(lambda _path: pipe)


def test_pipe_refuses_an_unknown_protocol_version() -> None:
    pipe = FakePipe([{"message_kind": "hello", "data": {"protocol": {"ipc_version": 3}}}])

    with pytest.raises(PlayitAddressError, match="no es compatible"):
        read_tunnels_from_pipe(lambda _path: pipe)
    assert pipe.written == b""


def test_pipe_errors_become_a_plain_message() -> None:
    def opener(_path):
        raise FileNotFoundError(PIPE_PATH)

    with pytest.raises(PlayitAddressError, match="No pudimos hablar con Playit"):
        read_tunnels_from_pipe(opener)


# --- Address from the agent API (fallback) ---------------------------------------------------------


def test_minecraft_tunnel_is_extracted_from_a_recorded_api_payload() -> None:
    tunnels = tunnels_from_rundata(RUNDATA_SAMPLE)

    assert [tunnel.tunnel_type for tunnel in tunnels] == [None, "minecraft-java"]
    assert pick_minecraft_address(tunnels, 25565) == "example-words.gl.joinmc.link"
    with pytest.raises(PlayitAddressError):
        tunnels_from_rundata({"status": "error", "data": {"type": "auth", "message": "InvalidAgentKey"}})


@pytest.mark.parametrize(
    ("tunnels", "expected"),
    [
        ([PlayitTunnel("a.ply.gg:1", local_port=8080), PlayitTunnel("b.ply.gg:2", local_port=25565)], "b.ply.gg:2"),
        ([PlayitTunnel("only.ply.gg:3")], "only.ply.gg:3"),
        ([PlayitTunnel("x.ply.gg:1"), PlayitTunnel("y.ply.gg:2")], None),
        ([PlayitTunnel("off.joinmc.link", disabled=True)], None),
    ],
)
def test_minecraft_tunnel_choice(tunnels, expected) -> None:
    assert pick_minecraft_address(tunnels, 25565) == expected


@pytest.mark.parametrize(
    "content",
    [f'secret_key = "{FAKE_SECRET}"\n', f"{FAKE_SECRET}\n"],
)
def test_agent_key_file_formats(tmp_path: Path, content: str) -> None:
    path = tmp_path / "playit.toml"
    path.write_text(content, encoding="utf-8")

    assert read_official_secret(path) == FAKE_SECRET


def test_unreadable_agent_key_file_never_echoes_its_content(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "playit.toml"
    path.write_text(f'secret_key = "{FAKE_SECRET}"\n', encoding="utf-8")

    def denied(*_args, **_kwargs):
        raise PermissionError(13, "Access is denied", str(path))

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(PlayitAddressError) as error:
        read_official_secret(path)
    assert "Windows no nos deja leer" in str(error.value) and error.value.__cause__ is None


@pytest.mark.asyncio
async def test_api_request_uses_the_key_once_on_the_official_host_only(tmp_path: Path) -> None:
    path = tmp_path / "playit.toml"
    path.write_text(f'secret_key = "{FAKE_SECRET}"\n', encoding="utf-8")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=RUNDATA_SAMPLE)

    tunnels = await read_tunnels_from_api(path, transport=httpx.MockTransport(handler))

    assert len(seen) == 1
    assert seen[0].method == "POST" and seen[0].url.host in PLAYIT_API_HOSTS and seen[0].url.scheme == "https"
    assert seen[0].url.path == "/v1/agents/rundata"
    assert seen[0].headers["Authorization"] == f"Agent-Key {FAKE_SECRET}"
    assert pick_minecraft_address(tunnels, 25565) == "example-words.gl.joinmc.link"


@pytest.mark.asyncio
async def test_api_failure_message_never_contains_the_key(tmp_path: Path) -> None:
    path = tmp_path / "playit.toml"
    path.write_text(f'secret_key = "{FAKE_SECRET}"\n', encoding="utf-8")

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(PlayitAddressError) as error:
        await read_tunnels_from_api(path, transport=httpx.MockTransport(handler))
    assert FAKE_SECRET not in str(error.value) and error.value.__cause__ is None


# --- End to end: "Usar la dirección de mi Playit" -----------------------------------------------------


@pytest.fixture
def endpoint_world(tmp_path: Path, monkeypatch):
    configured = Settings(project_root=tmp_path / "panel")
    assert configured.server_directory is not None and configured.panel_directory is not None
    configured.server_directory.mkdir(parents=True)
    secret_file = tmp_path / "ProgramData" / "playit_gg" / "playit.toml"
    secret_file.parent.mkdir(parents=True)
    secret_file.write_text(f'secret_key = "{FAKE_SECRET}"\n', encoding="utf-8")
    monkeypatch.setattr(endpoints_tunnel, "settings", configured)
    monkeypatch.setattr(endpoints_tunnel, "server_properties_service", SimpleNamespace(read_properties=lambda: {"server-port": "25565"}))
    monkeypatch.setattr("app.services.playit_service.official_secret_path", lambda: secret_file)
    service = PlayitService(configured)
    service._host_status = playit_host.PlayitHostStatus(state="running", service_installed=True, app_installed=True)
    service._host_checked_at = float("inf")
    monkeypatch.setattr(endpoints_tunnel, "playit_service", service)
    return configured


@pytest.mark.asyncio
async def test_address_from_the_pipe_is_saved_without_touching_the_key(endpoint_world, monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        "app.services.playit_service.read_tunnels_from_pipe",
        lambda: [PlayitTunnel("example-words.gl.joinmc.link", local_port=25565)],
    )

    async def must_not_run(*_args, **_kwargs):
        raise AssertionError("the agent key must not be read when the pipe answers")

    monkeypatch.setattr("app.services.playit_service.read_tunnels_from_api", must_not_run)

    response = await endpoints_tunnel.use_external_tunnel_address()

    assert response.public_address == "example-words.gl.joinmc.link" and response.saved_to == "panel"
    saved = json.loads((endpoint_world.panel_directory / ".server_connection.json").read_text(encoding="utf-8"))
    assert saved == {"public_address": "example-words.gl.joinmc.link"}


@pytest.mark.asyncio
async def test_api_fallback_saves_only_the_address_to_craftpanel_txt(endpoint_world, monkeypatch, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    (endpoint_world.server_directory / "craftpanel.txt").write_text("# mine\npublic_address =\n", encoding="utf-8")

    def pipe_down():
        raise PlayitAddressError("No pudimos hablar con Playit en esta computadora.")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=RUNDATA_SAMPLE)

    real_api = playit_host.read_tunnels_from_api
    monkeypatch.setattr("app.services.playit_service.read_tunnels_from_pipe", pipe_down)
    monkeypatch.setattr(
        "app.services.playit_service.read_tunnels_from_api",
        lambda path: real_api(path, transport=httpx.MockTransport(handler)),
    )

    response = await endpoints_tunnel.use_external_tunnel_address()

    body = response.model_dump_json()
    craftpanel = (endpoint_world.server_directory / "craftpanel.txt").read_text(encoding="utf-8")
    assert response.saved_to == "craftpanel.txt"
    assert "public_address = example-words.gl.joinmc.link" in craftpanel
    for text in (body, craftpanel, caplog.text, *(path.read_text(encoding="utf-8", errors="replace") for path in endpoint_world.panel_directory.glob("*") if path.is_file())):
        assert FAKE_SECRET not in text
    assert not (endpoint_world.panel_directory / ".playit_agent_secret").exists()


@pytest.mark.asyncio
async def test_automatic_lookup_never_reads_the_key(endpoint_world, monkeypatch) -> None:
    def pipe_down():
        raise PlayitAddressError("Playit todavía no muestra una dirección.")

    async def must_not_run(*_args, **_kwargs):
        raise AssertionError("the agent key must not be read without a click")

    monkeypatch.setattr("app.services.playit_service.read_tunnels_from_pipe", pipe_down)
    monkeypatch.setattr("app.services.playit_service.read_tunnels_from_api", must_not_run)

    with pytest.raises(Exception) as error:
        await endpoints_tunnel.use_external_tunnel_address(use_agent_key=False)
    assert getattr(error.value, "status_code", None) == 409


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pasted", "expected"),
    [("  example-words.gl.joinmc.link ", "example-words.gl.joinmc.link"), ("web-example.at.ply.gg:41000", "web-example.at.ply.gg:41000")],
)
async def test_pasted_address_is_cleaned_and_saved(endpoint_world, pasted: str, expected: str) -> None:
    response = await endpoints_tunnel.save_friend_address(endpoints_tunnel.FriendAddressRequest(public_address=pasted))

    assert response.public_address == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("pasted", ["no es una dirección", "host:99999", "bad_host!.com", "a" * 300])
async def test_pasted_garbage_is_refused_in_plain_words(endpoint_world, pasted: str) -> None:
    with pytest.raises(Exception) as error:
        await endpoints_tunnel.save_friend_address(endpoints_tunnel.FriendAddressRequest.model_construct(public_address=pasted))
    assert getattr(error.value, "status_code", None) == 422
