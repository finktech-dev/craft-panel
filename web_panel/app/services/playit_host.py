"""Read-only integration with the official Playit app for Windows.

The official installer registers a ``playitd`` Windows service (manual start)
and puts ``playit.exe`` in ``Program Files\\playit_gg\\bin``. This module:

* detects whether that app is installed and whether its service runs, without
  depending on the Windows display language;
* starts the service with the app's own ``playit.exe start`` command, which the
  installer allows for every signed-in user (no administrator rights and no
  change to the service configuration);
* reads the public address of the Minecraft tunnel, first from the service's
  local status pipe (no secret involved) and, only if that fails, from Playit's
  agent API using the agent key in ``playit.toml``. The key is used in memory
  for that one HTTPS request and is never logged, stored or returned.

Sources: https://github.com/playit-cloud/playit-agent (``packages/playit-ipc``,
``packages/playitd``, ``packages/playit-cli/wix/main.wxs``,
``packages/api_client``).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Literal

import httpx
import psutil

from app.core.net_safety import PLAYIT_API_HOSTS, allowed_client

logger = logging.getLogger(__name__)

SERVICE_NAME = "playitd"
PIPE_PATH = r"\\.\pipe\playitd-system"
AGENT_API_URL = "https://api.playit.gg/v1/agents/rundata"
OFFICIAL_DOWNLOAD_URL = "https://playit.gg/download"
_IPC_VERSION = 2
_MAX_PIPE_BYTES = 1024 * 1024
_HEX_SECRET = re.compile(r"^[0-9a-fA-F]{16,256}$")
# ``sc.exe query`` labels are translated ("STATE", "ESTADO"...), but the line is always
# "<label> : <number>  <UPPERCASE_NAME>", and only the state code is a single digit.
_SC_STATE = re.compile(r":\s*([1-7])\s+[A-Z_]+\s*$", re.MULTILINE)
_SC_STATES = {1: "stopped", 2: "start_pending", 3: "stop_pending", 4: "running", 5: "continue_pending", 6: "pause_pending", 7: "paused"}
_RUNNING_STATES = {"running", "start_pending", "continue_pending"}

PlayitHostState = Literal["running", "stopped", "not_installed"]
StartType = Literal["automatic", "manual", "disabled"]
ServiceGetter = Callable[[str], Any]
CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class PlayitAddressError(RuntimeError):
    """The address could not be read; the message is safe to show as is."""


@dataclass(frozen=True, slots=True)
class PlayitHostStatus:
    state: PlayitHostState
    service_installed: bool = False
    app_installed: bool = False
    start_type: StartType | None = None

    @property
    def starts_automatically(self) -> bool | None:
        return None if self.start_type is None else self.start_type == "automatic"


@dataclass(frozen=True, slots=True)
class PlayitTunnel:
    address: str
    local_port: int | None = None
    tunnel_type: str | None = None
    disabled: bool = False


def _program_files(environ: Mapping[str, str]) -> list[Path]:
    folders: list[Path] = []
    for name in ("ProgramW6432", "ProgramFiles"):
        value = environ.get(name)
        if value and Path(value) not in folders:
            folders.append(Path(value))
    return folders


def official_binary(environ: Mapping[str, str] | None = None, name: str = "playit.exe") -> Path | None:
    """``Program Files\\playit_gg\\bin\\<name>`` when the official app installed it."""
    for folder in _program_files(environ if environ is not None else os.environ):
        candidate = folder / "playit_gg" / "bin" / name
        if candidate.is_file():
            return candidate
    return None


def official_secret_path(environ: Mapping[str, str] | None = None) -> Path:
    values = environ if environ is not None else os.environ
    return Path(values.get("ProgramData") or r"C:\ProgramData") / "playit_gg" / "playit.toml"


def _query_with_psutil(service_get: ServiceGetter | None) -> tuple[bool, str | None, str | None] | None:
    """(installed, status, start type), or None when psutil cannot answer."""
    if service_get is None:
        return None
    try:
        service = service_get(SERVICE_NAME)
    except psutil.NoSuchProcess:
        return False, None, None
    except (psutil.Error, OSError):
        return None
    try:
        status = str(service.status())
    except (psutil.Error, OSError):
        return None
    try:
        start_type = str(service.start_type())
    except (psutil.Error, OSError):
        start_type = None
    return True, status, start_type


def _query_with_sc(run: CommandRunner) -> tuple[bool, str | None, str | None]:
    try:
        result = run(
            ("sc.exe", "query", SERVICE_NAME),
            capture_output=True,
            text=True,
            # sc.exe prints localized text in the OEM code page.
            errors="replace",
            timeout=3,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False, None, None
    if result.returncode != 0:  # 1060: the service does not exist
        return False, None, None
    match = _SC_STATE.search(result.stdout or "")
    return True, _SC_STATES.get(int(match.group(1))) if match else None, None


def detect_playit_host(
    *,
    system_name: str,
    environ: Mapping[str, str] | None = None,
    service_get: ServiceGetter | None = None,
    run: CommandRunner = subprocess.run,
) -> PlayitHostStatus:
    """Whether the official Playit app is installed and its service is running."""
    if system_name.casefold() != "windows":
        return PlayitHostStatus(state="not_installed")
    queried = _query_with_psutil(service_get)
    installed, status, start_type = queried if queried is not None else _query_with_sc(run)
    app_installed = official_binary(environ) is not None
    if installed and status in _RUNNING_STATES:
        state: PlayitHostState = "running"
    elif installed or app_installed:
        state = "stopped"
    else:
        state = "not_installed"
    normalized_start = start_type if start_type in {"automatic", "manual", "disabled"} else None
    return PlayitHostStatus(
        state=state,
        service_installed=installed,
        app_installed=app_installed,
        start_type=normalized_start,  # type: ignore[arg-type]
    )


def start_official_service(environ: Mapping[str, str] | None = None, run: CommandRunner = subprocess.run) -> bool:
    """Run the official ``playit.exe start``; True when the command reported success.

    The installer grants signed-in users permission to start and stop ``playitd``,
    so this never asks for administrator rights and never changes how the service starts.
    """
    executable = official_binary(environ)
    if executable is None:
        return False
    try:
        result = run(
            (str(executable), "start"),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


# --- Address from the local status pipe -------------------------------------------------------


class _LineReader:
    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._buffer = b""
        self._total = 0

    def readline(self) -> bytes:
        while b"\n" not in self._buffer:
            chunk = self._stream.read(65536)
            if not chunk:
                raise PlayitAddressError("Playit cerró la conexión.")
            self._total += len(chunk)
            if self._total > _MAX_PIPE_BYTES:
                raise PlayitAddressError("Playit respondió algo que no esperábamos.")
            self._buffer += chunk
        line, _, self._buffer = self._buffer.partition(b"\n")
        return line


def _pipe_lifecycle(opener: Callable[[str], BinaryIO]) -> dict[str, Any]:
    """Ask the service for its state with the read-only ``get_state`` request."""
    with opener(PIPE_PATH) as pipe:
        reader = _LineReader(pipe)
        hello = json.loads(reader.readline())
        protocol = (hello.get("data") or {}).get("protocol") or {} if isinstance(hello, dict) else {}
        if not isinstance(hello, dict) or hello.get("message_kind") != "hello" or protocol.get("ipc_version") != _IPC_VERSION:
            raise PlayitAddressError("Esta versión de Playit todavía no es compatible con el panel.")
        request = {"ipc_version": _IPC_VERSION, "request_id": 1, "request": {"type": "get_state"}}
        pipe.write(json.dumps(request).encode("utf-8") + b"\n")
        pipe.flush()
        for _ in range(64):
            envelope = json.loads(reader.readline())
            data = envelope.get("data") if isinstance(envelope, dict) else None
            if envelope.get("message_kind") == "response" and isinstance(data, dict) and data.get("request_id") == 1:
                response = data.get("response")
                if not isinstance(response, dict) or response.get("type") != "state":
                    raise PlayitAddressError("Playit no pudo contestar ahora. Probá de nuevo en un rato.")
                lifecycle = response.get("data")
                return lifecycle if isinstance(lifecycle, dict) else {}
    raise PlayitAddressError("Playit no contestó a tiempo.")


def tunnels_from_lifecycle(lifecycle: Mapping[str, Any]) -> list[PlayitTunnel]:
    """Tunnels from a ``get_state`` answer; raises with a plain message when Playit is not ready."""
    state = lifecycle.get("state")
    if state in {"waiting_for_secret", "has_invalid_secret"}:
        raise PlayitAddressError("Playit todavía no está vinculado a tu cuenta. Abrí Playit.gg y terminá de configurarlo.")
    if state != "running":
        raise PlayitAddressError("Playit se está encendiendo. Esperá unos segundos y probá de nuevo.")
    data = lifecycle.get("data") if isinstance(lifecycle.get("data"), dict) else {}
    tunnels: list[PlayitTunnel] = []
    for item in data.get("tunnels") or []:
        if not isinstance(item, dict) or not isinstance(item.get("display_address"), str):
            continue
        destination = str(item.get("destination") or "")
        port_text = destination.rpartition(":")[2]
        tunnels.append(
            PlayitTunnel(
                address=item["display_address"].strip(),
                local_port=int(port_text) if port_text.isdigit() else None,
                disabled=bool(item.get("is_disabled")),
            )
        )
    return tunnels


def read_tunnels_from_pipe(
    opener: Callable[[str], BinaryIO] | None = None, timeout: float = 5.0
) -> list[PlayitTunnel]:
    """Tunnels reported by the running ``playitd`` service, without any secret."""
    open_pipe = opener or (lambda path: open(path, "r+b", buffering=0))  # noqa: SIM115
    outcome: dict[str, Any] = {}

    def worker() -> None:
        try:
            outcome["value"] = tunnels_from_lifecycle(_pipe_lifecycle(open_pipe))
        except PlayitAddressError as error:
            outcome["error"] = error
        except (OSError, ValueError, AttributeError, TypeError):
            outcome["error"] = PlayitAddressError("No pudimos hablar con Playit en esta computadora.")

    # A blocking pipe read cannot be cancelled, so it runs in a daemon thread with a deadline.
    thread = threading.Thread(target=worker, name="playit-pipe", daemon=True)
    thread.start()
    thread.join(timeout)
    if "value" in outcome:
        return outcome["value"]
    raise outcome.get("error") or PlayitAddressError("Playit no contestó a tiempo.")


# --- Address from Playit's agent API (fallback) -----------------------------------------------


def read_official_secret(path: Path) -> str:
    """The agent key from ``playit.toml``; raises a plain message, never the file content."""
    try:
        raw = path.read_text(encoding="utf-8", errors="strict").strip()
    except FileNotFoundError:
        raise PlayitAddressError("No encontramos la configuración de Playit en esta computadora.") from None
    except (OSError, UnicodeError):
        raise PlayitAddressError("Windows no nos deja leer la configuración de Playit.") from None
    secret: object = raw
    if not _HEX_SECRET.match(raw):
        try:
            secret = tomllib.loads(raw).get("secret_key")
        except tomllib.TOMLDecodeError:
            secret = None
    if not isinstance(secret, str) or not _HEX_SECRET.match(secret.strip()):
        raise PlayitAddressError("La configuración de Playit no tiene una clave que podamos usar.")
    return secret.strip()


def tunnels_from_rundata(payload: Any) -> list[PlayitTunnel]:
    """Tunnels from a ``/v1/agents/rundata`` answer (``{"status": "success", "data": {...}}``)."""
    if not isinstance(payload, dict) or payload.get("status") != "success" or not isinstance(payload.get("data"), dict):
        raise PlayitAddressError("Playit no aceptó el pedido. Probá pegando la dirección a mano.")
    tunnels: list[PlayitTunnel] = []
    for item in payload["data"].get("tunnels") or []:
        if not isinstance(item, dict) or not isinstance(item.get("display_address"), str):
            continue
        fields = (item.get("agent_config") or {}).get("fields") if isinstance(item.get("agent_config"), dict) else None
        local_port = None
        for field in fields or []:
            if isinstance(field, dict) and field.get("name") == "local_port" and str(field.get("value", "")).isdigit():
                local_port = int(field["value"])
        tunnels.append(
            PlayitTunnel(
                address=item["display_address"].strip(),
                local_port=local_port,
                tunnel_type=item.get("tunnel_type") if isinstance(item.get("tunnel_type"), str) else None,
                disabled=bool(item.get("disabled_reason")),
            )
        )
    return tunnels


async def read_tunnels_from_api(
    secret_path: Path, transport: httpx.AsyncBaseTransport | None = None
) -> list[PlayitTunnel]:
    """One HTTPS request to Playit's agent API with the key held only in this call."""
    secret = read_official_secret(secret_path)
    try:
        async with allowed_client(PLAYIT_API_HOSTS, timeout=15.0, follow_redirects=False, transport=transport) as client:
            response = await client.post(AGENT_API_URL, json={}, headers={"Authorization": f"Agent-Key {secret}"})
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise PlayitAddressError("No pudimos conectarnos con Playit. Revisá tu Internet o pegá la dirección a mano.") from None
    finally:
        del secret
    return tunnels_from_rundata(payload)


def pick_minecraft_address(tunnels: Iterable[PlayitTunnel], server_port: int) -> str | None:
    """The Minecraft Java tunnel: by type, then by the server's local port, then the only one."""
    usable = [tunnel for tunnel in tunnels if tunnel.address and not tunnel.disabled]
    for matches in (
        lambda tunnel: tunnel.tunnel_type == "minecraft-java",
        lambda tunnel: tunnel.local_port == server_port,
        lambda tunnel: tunnel.address.casefold().rstrip(".").endswith(".joinmc.link"),
    ):
        found = [tunnel for tunnel in usable if matches(tunnel)]
        if found:
            return found[0].address
    return usable[0].address if len(usable) == 1 else None
