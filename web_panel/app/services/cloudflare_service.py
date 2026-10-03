"""Quick Tunnel temporal para acceder al panel desde fuera de la red local."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime

from app.core.config import Settings, settings
from app.schemas.runtime import CloudflareQuickTunnelStatus

logger = logging.getLogger(__name__)
_QUICK_TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)


class CloudflareQuickTunnelError(RuntimeError):
    pass


class CloudflareQuickTunnelService:
    """Controla una única instancia local de ``cloudflared tunnel --url``."""

    def __init__(self, configured_settings: Settings = settings) -> None:
        self._settings = configured_settings
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._watcher_task: asyncio.Task[None] | None = None
        self._url: str | None = None
        self._started_at: datetime | None = None
        self._last_error: str | None = None
        self._stop_requested = False
        self._lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def status(self) -> CloudflareQuickTunnelStatus:
        return CloudflareQuickTunnelStatus(
            is_running=self.is_running,
            public_url=self._url,
            message=self._message(),
            started_at=self._started_at,
            last_error=self._last_error,
        )

    async def start(self) -> CloudflareQuickTunnelStatus:
        async with self._lock:
            if self.is_running:
                return self.status()
            executable = self._settings.cloudflared_executable_path
            if not executable.is_file():
                self._last_error = f"No existe cloudflared.exe en {executable}."
                raise CloudflareQuickTunnelError(self._last_error)

            self._url = None
            self._last_error = None
            self._stop_requested = False
            self._started_at = datetime.now(UTC)
            try:
                self._process = await asyncio.create_subprocess_exec(
                    str(executable),
                    "tunnel",
                    "--url",
                    f"http://127.0.0.1:{self._settings.panel_port}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
            except OSError as error:
                self._last_error = "No se pudo iniciar cloudflared."
                raise CloudflareQuickTunnelError(self._last_error) from error

            assert self._process.stdout is not None
            self._reader_task = asyncio.create_task(self._read_output(self._process.stdout))
            self._watcher_task = asyncio.create_task(self._watch_process(self._process))
            return self.status()

    async def stop(self) -> CloudflareQuickTunnelStatus:
        async with self._lock:
            process = self._process
            if process is None or process.returncode is not None:
                return self.status()
            self._stop_requested = True
            process.terminate()
        await process.wait()
        async with self._lock:
            if self._process is process:
                self._process = None
                self._url = None
        return self.status()

    async def shutdown(self) -> None:
        await self.stop()
        for task in (self._reader_task, self._watcher_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (self._reader_task, self._watcher_task) if task is not None),
            return_exceptions=True,
        )

    async def _read_output(self, stream: asyncio.StreamReader) -> None:
        async for raw_line in stream:
            line = raw_line.decode("utf-8", errors="replace").strip()
            match = _QUICK_TUNNEL_URL.search(line)
            if match:
                self._url = match.group(0)
                logger.info("Quick Tunnel de Cloudflare detectado: %s", self._url)

    async def _watch_process(self, process: asyncio.subprocess.Process) -> None:
        exit_code = await process.wait()
        if process is not self._process:
            return
        if not self._stop_requested and exit_code != 0:
            self._last_error = f"Cloudflared terminó inesperadamente (código {exit_code})."
        self._process = None
        self._url = None

    def _message(self) -> str:
        if self.is_running and self._url:
            return "Enlace temporal HTTPS activo. Cambiará al reiniciar el túnel."
        if self.is_running:
            return "Cloudflare está creando el enlace temporal…"
        if self._last_error:
            return self._last_error
        return "Túnel temporal detenido."


cloudflare_quick_tunnel_service = CloudflareQuickTunnelService()
