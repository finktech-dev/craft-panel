"""Ciclo de vida del agente Playit y extracción de su dirección pública."""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import secrets
import subprocess
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import httpx
import psutil

from app.core.config import Settings, settings
from app.core.net_safety import PLAYIT_HOSTS, allowed_client, download_to_file
from app.services.playit_host import (
    PlayitAddressError,
    PlayitHostStatus,
    detect_playit_host,
    official_secret_path,
    pick_minecraft_address,
    read_tunnels_from_api,
    read_tunnels_from_pipe,
    start_official_service,
)
from app.core.path_safety import write_private_text
from app.schemas.runtime import TunnelLogLine, TunnelStatus
from app.websocket.manager import ConnectionManager, connection_manager

logger = logging.getLogger(__name__)
_RELEASE_API_URL = "https://api.github.com/repos/playit-cloud/playit-agent/releases/latest"
_PLAYIT_API = "https://api.playit.gg"
_MAX_AGENT_BYTES = 128 * 1024 * 1024
_OPEN_PLAYIT_HINT = "Playit está instalado pero apagado. Abrí Playit.gg desde el menú Inicio y probá de nuevo."
_PUBLIC_ADDRESS: Final[re.Pattern[str]] = re.compile(
    r"\b(?:[a-z0-9-]+\.)+(?:joinmc\.link|playit\.gg|ply\.gg)(?::\d{2,5})?\b",
    re.IGNORECASE,
)


class PlayitServiceError(RuntimeError):
    pass


class PlayitService:
    def __init__(self, configured_settings: Settings = settings, manager: ConnectionManager = connection_manager) -> None:
        self._settings = configured_settings
        self._connections = manager
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._watcher_task: asyncio.Task[None] | None = None
        self._public_address: str | None = None
        self._claim_code: str | None = None
        self._started_at: datetime | None = None
        self._last_exit_code: int | None = None
        self._last_error: str | None = None
        self._stop_requested = False
        self._history: deque[TunnelLogLine] = deque(maxlen=configured_settings.log_buffer_size)
        self._lock = asyncio.Lock()
        self._host_status = PlayitHostStatus(state="not_installed")
        self._host_checked_at = 0.0

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def host_status(self) -> PlayitHostStatus:
        """The official Playit app on this PC (installed, stopped or running), cached for 2 seconds."""
        now = time.monotonic()
        if now - self._host_checked_at < 2:
            return self._host_status
        self._host_checked_at = now
        self._host_status = detect_playit_host(
            system_name=platform.system(),
            service_get=getattr(psutil, "win_service_get", None),
            run=subprocess.run,
        )
        return self._host_status

    def _forget_host_status(self) -> None:
        self._host_checked_at = 0.0

    @property
    def uses_external_agent(self) -> bool:
        """Whether the official Playit service (``playitd``) is already running.

        The panel then never starts a second agent and never reads or copies that
        service's agent key to run one.
        """
        return self.host_status().state == "running"

    @property
    def can_start_external_agent(self) -> bool:
        """The official app is installed but its service is stopped (it starts manually)."""
        host = self.host_status()
        return host.state == "stopped" and host.service_installed and host.app_installed

    @property
    def history(self) -> tuple[TunnelLogLine, ...]:
        """Historial acotado para abrir la consola sin perder el contexto."""
        return tuple(self._history)

    @property
    def needs_setup(self) -> bool:
        assert self._settings.playit_secret_path is not None
        return not self._settings.playit_secret_path.is_file() and not self.uses_external_agent

    def status(self) -> TunnelStatus:
        host = self.host_status()
        return TunnelStatus(
            external_agent=host.state,
            external_autostart=host.starts_automatically,
            is_running=self.is_running or self.uses_external_agent,
            public_address=self._public_address or self._settings.effective_public_address,
            message=self._status_message(),
            started_at=self._started_at,
            last_exit_code=self._last_exit_code,
            last_error=self._last_error,
            needs_setup=self.needs_setup,
            claim_url=f"https://playit.gg/claim/{self._claim_code}" if self._claim_code else None,
        )

    async def start(self) -> TunnelStatus:
        async with self._lock:
            if self.is_running:
                await self._record("El agente ya estaba activo; no se inició una segunda copia.")
                return self.status()
            if self.uses_external_agent:
                await self._record("Usando el servicio Playit ya instalado en esta computadora.")
                return self.status()
            assert self._settings.playit_secret_path is not None
            if self.can_start_external_agent and not self._settings.playit_secret_path.is_file():
                await self._start_external_agent()
                return self.status()
            secret = await self._read_secret()
            await self.ensure_installed()
            self._public_address = None
            self._last_exit_code = None
            self._last_error = None
            self._stop_requested = False
            self._started_at = datetime.now(UTC)
            await self._record("Iniciando agente Playit…")
            try:
                self._process = await asyncio.create_subprocess_exec(
                    str(self._settings.playit_executable_path),
                    "--secret",
                    secret,
                    cwd=str(self._settings.playit_executable_path.parent),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
            except OSError as error:
                self._last_error = "No se pudo iniciar el ejecutable de Playit."
                # strerror only: str(error) would include this PC's folders.
                await self._record(f"Error al iniciar Playit: {error.strerror or 'error desconocido'}", level="error")
                raise PlayitServiceError(self._last_error) from error
            assert self._process.stdout is not None
            self._reader_task = asyncio.create_task(self._read_output(self._process.stdout), name="playit-output")
            self._watcher_task = asyncio.create_task(self._watch_process(self._process), name="playit-watch")
            return self.status()

    async def start_external_agent(self) -> TunnelStatus:
        """Turn on the official Playit service, the same way its Start menu shortcut does."""
        async with self._lock:
            if not self.uses_external_agent:
                await self._start_external_agent()
            return self.status()

    async def _start_external_agent(self) -> None:
        if not self.can_start_external_agent:
            raise PlayitServiceError(_OPEN_PLAYIT_HINT)
        await self._record("Encendiendo Playit…")
        await asyncio.to_thread(start_official_service)
        for _ in range(30):
            self._forget_host_status()
            if self.uses_external_agent:
                await self._record("Playit está encendido.", level="success")
                return
            await asyncio.sleep(0.5)
        self._last_error = _OPEN_PLAYIT_HINT
        await self._record(self._last_error, level="error")
        raise PlayitServiceError(self._last_error)

    async def read_external_address(self, server_port: int, *, use_agent_key: bool = True) -> str:
        """Public address of the Minecraft tunnel of the official Playit app.

        First the service's local status pipe (no secret involved); if that is
        not possible, one request to Playit's agent API with the key from
        ``playit.toml``, used only in memory. Raises :class:`PlayitAddressError`.
        """
        host = self.host_status()
        if host.state == "not_installed":
            raise PlayitAddressError("No encontramos Playit instalado en esta computadora.")
        tunnels = []
        if host.state == "running":
            try:
                tunnels = await asyncio.to_thread(read_tunnels_from_pipe)
            except PlayitAddressError as error:
                logger.info("The Playit status pipe did not answer: %s", error)
        if not tunnels:
            if not use_agent_key:
                raise PlayitAddressError("Playit todavía no muestra una dirección.")
            tunnels = await read_tunnels_from_api(official_secret_path())
        address = pick_minecraft_address(tunnels, server_port)
        if address is None:
            raise PlayitAddressError(
                "No encontramos un túnel de Minecraft en tu Playit. Creá uno en playit.gg o pegá la dirección a mano."
            )
        return address

    async def begin_claim(self) -> TunnelStatus:
        """Create Playit's official browser claim without receiving account credentials."""
        async with self._lock:
            if self._claim_code:
                return self.status()
            code = secrets.token_hex(16)
            try:
                async with allowed_client(PLAYIT_HOSTS, timeout=20.0, follow_redirects=False) as client:
                    response = await client.post(
                        f"{_PLAYIT_API}/claim/setup",
                        json={"code": code, "agent_type": "self-managed", "version": "minecraft-panel"},
                    )
                    response.raise_for_status()
                    payload = response.json()
            except (httpx.HTTPError, ValueError) as error:
                raise PlayitServiceError("No se pudo preparar la vinculación con Playit.") from error
            if not isinstance(payload, dict) or payload.get("status") != "success":
                raise PlayitServiceError("Playit rechazó la preparación de la vinculación. Intentá nuevamente.")
            self._claim_code = code
            await self._record("Abrí la página oficial de Playit para vincular esta computadora.", level="success")
            return self.status()

    async def complete_claim(self) -> TunnelStatus:
        """Exchange an approved claim once; the short-lived code is never persisted."""
        async with self._lock:
            code = self._claim_code
            if not code:
                raise PlayitServiceError("No hay una vinculación de Playit pendiente.")
            try:
                async with allowed_client(PLAYIT_HOSTS, timeout=20.0, follow_redirects=False) as client:
                    response = await client.post(f"{_PLAYIT_API}/claim/exchange", json={"code": code})
                    response.raise_for_status()
                    payload = response.json()
            except (httpx.HTTPError, ValueError) as error:
                raise PlayitServiceError("Todavía no se pudo confirmar la vinculación. Terminá la aprobación en Playit e intentá de nuevo.") from error
            secret = payload.get("data", {}).get("secret_key") if isinstance(payload, dict) else None
            if not isinstance(secret, str) or len(secret) < 16:
                raise PlayitServiceError("Playit todavía está esperando tu aprobación en el navegador.")
            assert self._settings.playit_secret_path is not None
            await asyncio.to_thread(self._write_secret, self._settings.playit_secret_path, secret)
            self._claim_code = None
            self._last_error = None
            await self._record("Playit quedó vinculado. La clave se guardó solo en esta computadora.", level="success")
            return self.status()
    async def configure_secret(self, agent_secret: str) -> TunnelStatus:
        """Guarda la clave localmente y de forma atómica; nunca se registra en logs."""
        secret = agent_secret.strip()
        if len(secret) < 16 or "\n" in secret or "\r" in secret:
            raise PlayitServiceError("La clave de agente de Playit no tiene un formato válido.")
        async with self._lock:
            if self.is_running:
                await self.stop()
            assert self._settings.playit_secret_path is not None
            await asyncio.to_thread(self._write_secret, self._settings.playit_secret_path, secret)
            self._last_error = None
            await self._record("Clave del agente guardada. Ya podés iniciar el túnel.", level="success")
            return self.status()

    async def stop(self) -> bool:
        process = self._process
        if process is None or process.returncode is not None:
            return False
        await self._record("Deteniendo agente Playit…")
        self._stop_requested = True
        process.terminate()
        await process.wait()
        return True

    async def shutdown(self) -> None:
        """Cierra el agente al apagar el panel, sin dejar procesos huérfanos."""
        await self.stop()
        for task in (self._reader_task, self._watcher_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (self._reader_task, self._watcher_task) if task is not None),
            return_exceptions=True,
        )

    async def ensure_installed(self) -> None:
        target = self._settings.playit_executable_path
        if target.is_file():
            return
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        try:
            async with allowed_client(PLAYIT_HOSTS, timeout=120.0) as client:
                release = await client.get(_RELEASE_API_URL, headers={"Accept": "application/vnd.github+json"})
                release.raise_for_status()
                download_url, sha256 = self._select_asset(release.json())
                await download_to_file(
                    client,
                    download_url,
                    target,
                    max_bytes=_MAX_AGENT_BYTES,
                    expected_hash=("sha256", sha256) if sha256 else None,
                )
                if os.name != "nt":
                    await asyncio.to_thread(os.chmod, target, 0o700)
        except (httpx.HTTPError, OSError, ValueError) as error:
            raise PlayitServiceError("No se pudo descargar Playit desde su release oficial.") from error

    async def _read_secret(self) -> str:
        assert self._settings.playit_secret_path is not None
        path = self._settings.playit_secret_path
        if not path.is_file():
            self._last_error = "Falta vincular Playit: abrí la consola del túnel y pegá la clave del agente una sola vez."
            await self._record(self._last_error, level="error")
            raise PlayitServiceError(self._last_error)
        try:
            secret = (await asyncio.to_thread(path.read_text, encoding="utf-8")).strip()
        except OSError as error:
            self._last_error = "No se pudo leer la clave local de Playit."
            await self._record(f"Error de lectura de la clave de Playit: {error.strerror or 'error desconocido'}", level="error")
            raise PlayitServiceError(self._last_error) from error
        if len(secret) < 16:
            self._last_error = "La clave local de Playit no es válida. Pegala nuevamente desde tu cuenta de Playit."
            await self._record(self._last_error, level="error")
            raise PlayitServiceError(self._last_error)
        return secret

    @staticmethod
    def _write_secret(path: Path, secret: str) -> None:
        write_private_text(path, secret)

    @staticmethod
    def _select_asset(release: dict[str, object]) -> tuple[str, str | None]:
        """Pick the official portable agent for the current supported host."""
        assets = release.get("assets", [])
        if not isinstance(assets, list):
            raise ValueError("Release de Playit inválida.")
        system = platform.system().lower()
        machine = platform.machine().lower()
        architecture = "aarch64" if machine in {"arm64", "aarch64"} else "amd64"
        prefixes = {
            # Official releases have used both playit-* and playit-cli-* names.
            "windows": (
                f"playit-cli-windows-{'x86_64' if architecture == 'amd64' else architecture}",
                f"playit-cli-windows-{architecture}",
                f"playit-windows-{'x86_64' if architecture == 'amd64' else architecture}",
                f"playit-windows-{architecture}",
            ),
            "linux": (f"playit-cli-linux-{architecture}", f"playit-linux-{architecture}"),
            "darwin": (f"-apple-{'m1' if architecture == 'aarch64' else 'intel'}",),
        }.get(system)
        if prefixes is None:
            raise ValueError("No compatible automatic Playit download is available for this operating system.")
        candidates = [
            asset for asset in assets
            if isinstance(asset, dict)
            and isinstance(asset.get("name"), str)
            and (asset["name"].endswith(prefixes) if system == "darwin" else asset["name"].startswith(prefixes))
            and not asset["name"].endswith(".msi")
        ]
        if not candidates:
            raise ValueError(f"No hay un binario Playit compatible para {system} {architecture}.")
        url = candidates[0].get("browser_download_url")
        if not isinstance(url, str) or not url.startswith("https://github.com/playit-cloud/"):
            raise ValueError("URL de descarga Playit inválida.")
        # GitHub publishes "sha256:<hex>" digests for release assets.
        digest = candidates[0].get("digest")
        sha256 = digest.removeprefix("sha256:") if isinstance(digest, str) and digest.startswith("sha256:") else None
        return url, sha256 if sha256 and len(sha256) == 64 else None

    async def _read_output(self, stream: asyncio.StreamReader) -> None:
        async for raw_line in stream:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            match = _PUBLIC_ADDRESS.search(line)
            if match:
                self._public_address = match.group(0)
                await self._record(f"Dirección pública detectada: {self._public_address}", level="success")
            await self._record(line)

    async def _watch_process(self, process: asyncio.subprocess.Process) -> None:
        exit_code = await process.wait()
        if process is not self._process:
            return
        self._last_exit_code = exit_code
        if self._stop_requested:
            await self._record("Agente Playit detenido.", level="warning")
        elif exit_code == 0:
            await self._record("El agente Playit finalizó.", level="warning")
        else:
            self._last_error = f"Playit terminó inesperadamente (código {exit_code})."
            await self._record(self._last_error, level="error")

    def _status_message(self) -> str:
        if self.uses_external_agent:
            return "Playit está instalado y funcionando."
        if self.can_start_external_agent and self.needs_setup:
            return "Playit está instalado pero apagado. Lo encendemos cuando enciendas el servidor."
        if self.is_running and self._public_address:
            return "Túnel Playit activo y dirección pública detectada."
        if self.is_running:
            return "Playit está activo; revisá la consola del túnel para completar la vinculación o ver el progreso."
        if self._last_error:
            return self._last_error
        if self.needs_setup:
            return "Falta vincular tu cuenta de Playit con la clave de agente."
        return "Túnel Playit detenido."

    async def _record(self, message: str, level: str = "info") -> None:
        line = TunnelLogLine(timestamp=datetime.now(UTC), level=level, message=message)
        self._history.append(line)
        await self._connections.broadcast_json({
            "type": "log",
            "line": {
                "timestamp": line.timestamp.isoformat(),
                "stream": "playit",
                "message": f"[Playit] {line.message}",
            },
        })


playit_service = PlayitService()
