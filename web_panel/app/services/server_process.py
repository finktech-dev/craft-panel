"""Ciclo de vida asíncrono del proceso de Minecraft y su consola."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
from collections import deque
from collections.abc import Coroutine
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

from app.core.config import Settings, settings
from app.services.crash_analyzer import crash_analyzer
from app.services.discord_service import discord_service
from app.websocket.manager import ConnectionManager, connection_manager

logger = logging.getLogger(__name__)
_COMMAND_MAX_LENGTH: Final = 1_000
_PLAYER_JOIN_RE: Final = re.compile(
    r"(?:\[(?:minecraft|net\.minecraft\.server).*?\]:?\s+|^|\b)([a-zA-Z0-9_]{2,16})\s+joined the game",
    re.IGNORECASE,
)
_PLAYER_LEAVE_RE: Final = re.compile(
    r"(?:\[(?:minecraft|net\.minecraft\.server).*?\]:?\s+|^|\b)([a-zA-Z0-9_]{2,16})\s+left the game",
    re.IGNORECASE,
)
_PLAYER_DEATH_RE: Final = re.compile(
    r"(?:\[(?:net\.minecraft\.server\.MinecraftServer|minecraft/MinecraftServer)\]:?\s+)([a-zA-Z0-9_]{2,16})\s+(was\s+\w+|fell\s+\w+|hit\s+the\s+ground|drowned|suffocated|burned|went\s+up\s+in\s+flames|tried\s+to\s+swim|starved|died|withered|froze|discovered\s+the\s+floor)(.*)",
    re.IGNORECASE,
)
_ADVANCEMENT_RE: Final = re.compile(
    r"(?:\[(?:net\.minecraft\.server\.MinecraftServer|minecraft/MinecraftServer)\]:?\s+)([a-zA-Z0-9_]{2,16})\s+has\s+(made the advancement|completed the challenge|reached the goal)\s+\[(.*?)\]",
    re.IGNORECASE,
)
_SERVER_READY_RE: Final = re.compile(
    r"Done \([0-9.]+s\)!|Listening on /",
    re.IGNORECASE,
)


class ServerState(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    CRASHED = "CRASHED"


class ServerProcessError(RuntimeError):
    """Error de operación del proceso Java."""


@dataclass(frozen=True, slots=True)
class TerminalLine:
    timestamp: str
    stream: str
    message: str


class MinecraftServerManager:
    """Única autoridad sobre el proceso del servidor en el host.

    Todas las operaciones de proceso y E/S usan APIs ``asyncio``: nunca se
    bloquea el event loop del panel mientras Java está corriendo.
    """

    _instance: "MinecraftServerManager | None" = None

    def __new__(
        cls,
        configured_settings: Settings | None = None,
        websocket_manager: ConnectionManager | None = None,
    ) -> "MinecraftServerManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        configured_settings: Settings | None = None,
        websocket_manager: ConnectionManager | None = None,
    ) -> None:
        if getattr(self, "_initialized", False):
            return

        self._settings = configured_settings or settings
        self._websocket_manager = websocket_manager or connection_manager
        self._process: asyncio.subprocess.Process | None = None
        self._state = ServerState.STOPPED
        self._online_players: dict[str, str] = {}
        self._log_buffer: deque[TerminalLine] = deque(maxlen=self._settings.log_buffer_size)
        self._lock = asyncio.Lock()
        self._reader_tasks: set[asyncio.Task[None]] = set()
        self._watcher_task: asyncio.Task[None] | None = None
        self._stop_requested = False
        self._dev_mode: bool = False
        self._start_requested_time: float | None = None
        self._ready_notified: bool = False
        self._last_join_notified: dict[str, float] = {}
        self._last_leave_notified: dict[str, float] = {}
        self._last_death_notified: dict[str, float] = {}
        self._initialized = True

    @property
    def state(self) -> ServerState:
        return self._state

    @property
    def dev_mode(self) -> bool:
        return self._dev_mode

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def process_pid(self) -> int | None:
        """PID del lanzador; MetricsService resuelve Java cuando es un hijo."""
        return self._process.pid if self.is_running and self._process is not None else None

    @property
    def history(self) -> list[dict[str, str]]:
        return [asdict(line) for line in self._log_buffer]

    def get_online_players(self) -> list[dict[str, Any]]:
        if not self.is_running:
            self._online_players.clear()
            return []
        return [
            {
                "username": name,
                "avatar_url": f"https://mc-heads.net/avatar/{name}/40",
                "connected_since": since,
            }
            for name, since in self._online_players.items()
        ]

    async def start(self, dev_mode: bool = False) -> bool:
        """Inicia el servidor y retorna ``False`` si ya había un proceso vivo."""
        async with self._lock:
            if self.is_running:
                return False

            self._online_players.clear()
            self._dev_mode = dev_mode

            if not self._settings.server_directory or not self._settings.server_directory.is_dir():
                raise ServerProcessError(
                    f"No existe el directorio del servidor: {self._settings.server_directory}"
                )
            if not self._settings.server_start_script.is_file():
                raise ServerProcessError(
                    f"No existe el script de inicio del servidor: {self._settings.server_start_script}"
                )

            self._state = ServerState.STARTING
            self._stop_requested = False
            self._start_requested_time = asyncio.get_running_loop().time()
            self._ready_notified = False
            try:
                environment = os.environ.copy()
                local_java = self._settings.local_java_executable_path
                if local_java.is_file():
                    environment["PATH"] = f"{local_java.parent}{os.pathsep}{environment.get('PATH', '')}"
                self._process = await asyncio.create_subprocess_exec(
                    *self._settings.server_start_command,
                    cwd=str(self._settings.server_directory),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=environment,
                )
            except OSError as error:
                self._state = ServerState.CRASHED
                await self._record_log("system", f"No se pudo iniciar el servidor: {error}")
                raise ServerProcessError("No se pudo crear el proceso del servidor.") from error

            assert self._process.stdout is not None
            assert self._process.stderr is not None
            self._create_reader_task(self._read_stream(self._process.stdout, "stdout"))
            self._create_reader_task(self._read_stream(self._process.stderr, "stderr"))
            self._watcher_task = asyncio.create_task(
                self._watch_process(self._process), name="minecraft-process-watcher"
            )
            await self._broadcast_status()
            if not self._dev_mode:
                asyncio.create_task(discord_service.send_server_starting(), name="discord-server-starting")
            return True

    async def stop(self) -> bool:
        """Solicita una detención limpia mediante la consola de Minecraft."""
        if not self.is_running:
            return False
        self._stop_requested = True
        await self.send_command("/stop")
        return True

    async def graceful_restart(self, countdown_seconds: int = 10, dev_mode: bool | None = None) -> None:
        """Reinicia el servidor avisando a los jugadores en el chat y guardando el mundo."""
        target_dev_mode = self._dev_mode if dev_mode is None else dev_mode
        if not self.is_running:
            await self.start(dev_mode=target_dev_mode)
            return

        try:
            await self.send_command(
                f"/say §c[Servidor] El servidor se reiniciará en {countdown_seconds} segundos para aplicar cambios. ¡Guarden sus cosas!"
            )
            if countdown_seconds > 5:
                await asyncio.sleep(countdown_seconds - 5)
                await self.send_command("/say §e[Servidor] Reinicio en 5 segundos...")
                await asyncio.sleep(4)
                await self.send_command("/say §4[Servidor] Reiniciando ahora...")
                await asyncio.sleep(1)
            else:
                await asyncio.sleep(countdown_seconds)

            with contextlib.suppress(Exception):
                await self.send_command("/save-all flush")
                await asyncio.sleep(1.5)
        except Exception:
            pass

        await self.stop()
        try:
            await asyncio.wait_for(
                self.wait_until_stopped(), timeout=self._settings.graceful_stop_timeout_seconds
            )
        except TimeoutError:
            await self.kill()
            await self.wait_until_stopped()

        await self.start(dev_mode=target_dev_mode)

    async def kill(self) -> bool:
        """Finaliza el árbol de procesos cuando el cierre limpio no responde."""
        process = self._process
        if process is None or process.returncode is not None:
            return False

        self._stop_requested = True
        if os.name == "nt":
            taskkill = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await taskkill.wait()
        else:
            process.kill()
        return True

    async def send_command(self, command: str) -> None:
        """Escribe un único comando en STDIN sin usar una shell."""
        normalized_command = command.strip()
        if not normalized_command:
            raise ServerProcessError("El comando no puede estar vacío.")
        if "\n" in command or "\r" in command:
            raise ServerProcessError("El comando debe ocupar una sola línea.")
        if len(normalized_command) > _COMMAND_MAX_LENGTH:
            raise ServerProcessError("El comando supera el límite de 1000 caracteres.")

        process = self._process
        if process is None or process.returncode is not None or process.stdin is None:
            raise ServerProcessError("El servidor no está en ejecución.")

        try:
            process.stdin.write(f"{normalized_command}\n".encode("utf-8"))
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionError) as error:
            raise ServerProcessError("La consola del servidor ya no acepta comandos.") from error

    async def send_command_and_wait_for_log(
        self,
        command: str,
        expected_text: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Ejecuta un comando y espera su confirmación en la consola.

        Se usa para que una copia no comprima archivos mientras Minecraft aún
        está vaciando los cambios pendientes del mundo al disco.
        """
        sent_at = datetime.now(UTC).isoformat()
        await self.send_command(command)
        deadline = asyncio.get_running_loop().time() + timeout_seconds

        while asyncio.get_running_loop().time() < deadline:
            if any(
                line.timestamp >= sent_at and expected_text.casefold() in line.message.casefold()
                for line in self._log_buffer
            ):
                return
            await asyncio.sleep(0.1)

        raise ServerProcessError(
            f"El servidor no confirmó '{command}' dentro de {timeout_seconds:.0f} segundos."
        )

    async def shutdown(self) -> None:
        """Cierra ordenadamente el proceso al apagar FastAPI."""
        if not self.is_running:
            return

        await self.stop()
        process = self._process
        assert process is not None
        try:
            await asyncio.wait_for(process.wait(), timeout=self._settings.graceful_stop_timeout_seconds)
        except TimeoutError:
            logger.warning("El servidor no respondió a /stop; se forzará su cierre.")
            await self.kill()
            await process.wait()

    async def wait_until_ready(self, timeout_seconds: float = 120.0) -> None:
        """Wait for Minecraft's readiness line without guessing a fixed startup delay."""
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            if self._state == ServerState.RUNNING:
                return
            if not self.is_running:
                raise ServerProcessError("The server stopped before it finished starting.")
            await asyncio.sleep(0.2)
        raise ServerProcessError("The server did not finish starting in time.")
    async def wait_until_stopped(self) -> None:
        """Espera de forma cooperativa a que el proceso actual finalice."""
        process = self._process
        if process is not None and process.returncode is None:
            await process.wait()

    def _create_reader_task(self, coroutine: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coroutine)
        self._reader_tasks.add(task)
        task.add_done_callback(self._reader_tasks.discard)

    async def _read_stream(self, stream: asyncio.StreamReader, stream_name: str) -> None:
        async for raw_line in stream:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            await self._record_log(stream_name, line)

    async def _watch_process(self, process: asyncio.subprocess.Process) -> None:
        exit_code = await process.wait()
        for task in tuple(self._reader_tasks):
            with contextlib.suppress(asyncio.CancelledError):
                await task

        async with self._lock:
            if self._process is not process:
                return
            self._process = None
            self._online_players.clear()
            self._ready_notified = False
            self._start_requested_time = None
            self._last_join_notified.clear()
            self._last_leave_notified.clear()
            self._last_death_notified.clear()
            self._state = ServerState.STOPPED if self._stop_requested else ServerState.CRASHED

        await self._record_log("system", f"Proceso del servidor finalizado con código {exit_code}.")
        await self._broadcast_status()
        if not self._dev_mode:
            if self._state == ServerState.STOPPED:
                asyncio.create_task(discord_service.send_server_stopped(), name="discord-server-stopped")
            else:
                report = await crash_analyzer.get_latest_crash_report()
                asyncio.create_task(discord_service.send_crash(report), name="discord-server-crashed")
        self._dev_mode = False

    async def _record_log(self, stream: str, message: str) -> None:
        line = TerminalLine(
            timestamp=datetime.now(UTC).isoformat(),
            stream=stream,
            message=message,
        )
        self._log_buffer.append(line)

        # Rastrear cuando el servidor termina de inicializarse ("Done (X.XXs)!")
        if not self._ready_notified and _SERVER_READY_RE.search(message):
            self._ready_notified = True
            self._state = ServerState.RUNNING
            await self._broadcast_status()

            if not self._dev_mode:
                elapsed_sec = None
                if self._start_requested_time is not None:
                    elapsed_sec = round(asyncio.get_running_loop().time() - self._start_requested_time, 1)

                conn_addr = None
                conn_file = self._settings.panel_directory / ".server_connection.json" if self._settings.panel_directory else None
                if conn_file and conn_file.is_file():
                    try:
                        conn_addr = json.loads(conn_file.read_text(encoding="utf-8")).get("public_address")
                    except Exception:
                        pass
                asyncio.create_task(
                    discord_service.send_server_started(public_address=conn_addr, elapsed_seconds=elapsed_sec),
                    name="discord-server-started",
                )

        # Rastrear eventos de conexión y desconexión de jugadores (con debouncer anti-duplicados)
        join_m = _PLAYER_JOIN_RE.search(message)
        if join_m:
            player_name = join_m.group(1)
            now_ts = asyncio.get_running_loop().time()
            if now_ts - self._last_join_notified.get(player_name, 0.0) > 4.0:
                self._last_join_notified[player_name] = now_ts
                self._online_players[player_name] = line.timestamp
                if not self._dev_mode:
                    asyncio.create_task(discord_service.send_player_join(player_name), name="discord-player-join")
        else:
            leave_m = _PLAYER_LEAVE_RE.search(message)
            if leave_m:
                player_name = leave_m.group(1)
                now_ts = asyncio.get_running_loop().time()
                if now_ts - self._last_leave_notified.get(player_name, 0.0) > 4.0:
                    self._last_leave_notified[player_name] = now_ts
                    self._online_players.pop(player_name, None)
                    if not self._dev_mode:
                        asyncio.create_task(discord_service.send_player_leave(player_name), name="discord-player-leave")
            else:
                death_m = _PLAYER_DEATH_RE.search(message)
                if death_m:
                    player_name = death_m.group(1)
                    now_ts = asyncio.get_running_loop().time()
                    death_text = f"{player_name} {death_m.group(2)}{death_m.group(3)}".strip()
                    if now_ts - self._last_death_notified.get(player_name, 0.0) > 4.0:
                        self._last_death_notified[player_name] = now_ts
                        if not self._dev_mode:
                            asyncio.create_task(discord_service.send_player_death(player_name, death_text), name="discord-player-death")
                else:
                    adv_m = _ADVANCEMENT_RE.search(message)
                    if adv_m:
                        player_name = adv_m.group(1)
                        adv_type_raw = adv_m.group(2).lower()
                        adv_title = adv_m.group(3)
                        adv_kind = "desafío" if "challenge" in adv_type_raw else ("meta" if "goal" in adv_type_raw else "logro")
                        if not self._dev_mode:
                            asyncio.create_task(discord_service.send_advancement(player_name, adv_title, adv_kind), name="discord-player-adv")

        await self._websocket_manager.broadcast_json({"type": "log", "line": asdict(line)})

    async def _broadcast_status(self) -> None:
        await self._websocket_manager.broadcast_json(
            {
                "type": "status",
                "state": self._state,
                "pid": self._process.pid if self._process else None,
                "dev_mode": self._dev_mode,
            }
        )


server_manager = MinecraftServerManager()
