"""Minecraft RCON: commands for a server this panel session did not start.

The panel starts Java detached from its own window, so the server can outlive a
panel restart. A panel that takes such a server back has no console input to
write to, so commands go through RCON instead. The panel turns RCON on before a
start when it is off, with a random password. Minecraft reads that password from
server.properties; the panel never shows it and the properties editor hides it.
"""

from __future__ import annotations

import logging
import os
import secrets
import socket
import struct
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PORT = 25575
# server.properties keys the panel manages; the properties editor never shows or writes them.
MANAGED_KEYS = frozenset({"rcon.password"})

_TYPE_AUTH = 3
_TYPE_COMMAND = 2
# Minecraft splits long answers in packets of this many bytes.
_MAX_PAYLOAD = 4096


class RconError(RuntimeError):
    """RCON is off, unreachable or refused the password."""


@dataclass(frozen=True, slots=True)
class RconSettings:
    port: int
    password: str


def read_properties(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def rcon_settings(properties: dict[str, str]) -> RconSettings | None:
    """Usable RCON settings, or ``None`` when RCON is off or has no password (Minecraft then keeps it off)."""
    if properties.get("enable-rcon", "false").strip().lower() != "true":
        return None
    password = properties.get("rcon.password", "")
    if not password:
        return None
    try:
        port = int(properties.get("rcon.port", DEFAULT_PORT))
    except ValueError:
        port = DEFAULT_PORT
    return RconSettings(port if 1 <= port <= 65535 else DEFAULT_PORT, password)


def updates_to_enable(properties: dict[str, str]) -> dict[str, str] | None:
    """Lines to write so RCON works, or ``None`` when it already does (an owner's own setup is kept)."""
    if rcon_settings(properties) is not None:
        return None
    return {
        "enable-rcon": "true",
        "rcon.port": properties.get("rcon.port") or str(DEFAULT_PORT),
        "rcon.password": secrets.token_urlsafe(24),
        # The panel's own commands should not echo in every op's chat.
        "broadcast-rcon-to-ops": "false",
    }


def write_properties(path: Path, updates: dict[str, str]) -> None:
    """Replace or append ``updates`` keeping every other line, atomically."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        lines = []
    written: set[str] = set()
    merged: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in updates:
            merged.append(f"{key}={updates[key]}")
            written.add(key)
        else:
            merged.append(line)
    merged.extend(f"{key}={value}" for key, value in updates.items() if key not in written)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text("\n".join(merged) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _packet(request_id: int, kind: int, payload: str) -> bytes:
    body = struct.pack("<ii", request_id, kind) + payload.encode("utf-8") + b"\x00\x00"
    return struct.pack("<i", len(body)) + body


def _receive_exactly(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise RconError("El servidor cerró la conexión de RCON.")
        data += chunk
    return data


def _receive(sock: socket.socket) -> tuple[int, str]:
    (length,) = struct.unpack("<i", _receive_exactly(sock, 4))
    if not 10 <= length <= _MAX_PAYLOAD + 10:
        raise RconError("Respuesta de RCON inválida.")
    body = _receive_exactly(sock, length)
    request_id, _kind = struct.unpack("<ii", body[:8])
    return request_id, body[8:-2].decode("utf-8", errors="replace")


def run_command(settings: RconSettings, command: str, *, host: str = "127.0.0.1", timeout: float = 5.0) -> str:
    """Send one command and return Minecraft's answer (may be empty)."""
    command = command.strip().removeprefix("/")
    try:
        with socket.create_connection((host, settings.port), timeout=timeout) as sock:
            sock.sendall(_packet(1, _TYPE_AUTH, settings.password))
            request_id, _ = _receive(sock)
            if request_id == -1:
                raise RconError("RCON no aceptó la contraseña.")
            sock.sendall(_packet(2, _TYPE_COMMAND, command))
            _, answer = _receive(sock)
            # A full packet means more may follow; stop at the first short read or pause.
            sock.settimeout(0.3)
            last = answer
            while len(last.encode("utf-8")) >= _MAX_PAYLOAD:
                try:
                    _, last = _receive(sock)
                except (TimeoutError, socket.timeout):
                    break
                answer += last
            return answer
    except RconError:
        raise
    except OSError as error:
        raise RconError(f"No pudimos hablar con el servidor por RCON: {error.strerror or error}") from error
