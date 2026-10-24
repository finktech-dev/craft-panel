"""Async lifecycle of the Minecraft process and its console."""

from __future__ import annotations

import asyncio
import uuid
import contextlib
import json
import logging
import os
import re
from collections import deque
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from app.core.config import Settings, settings
from app.core.privacy import redact_personal_paths
from app.services.crash_analyzer import crash_analyzer
from app.services.discord_service import discord_service
from app.services.external_server_service import ExternalServerDetector
from app.services.server_settings_file import read_server_settings
from app.services.progress import ProgressCallback, StepPlan, report
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


# Steps announced through ``progress`` callbacks. ``ready`` is reported by the
# caller while it waits for Minecraft's "Done" line, outside the lifecycle lock.
_READY_STEP: Final = ("ready", "Esperando a que cargue el mundo")
START_STEPS: Final[StepPlan] = (
    ("connect", "Preparando la dirección para tus amigos"),
    ("start", "Encendiendo el servidor"),
    _READY_STEP,
)
RESTART_STEPS: Final[StepPlan] = (
    ("stop", "Apagando el servidor"),
    ("start", "Encendiendo el servidor"),
    _READY_STEP,
)
GRACEFUL_RESTART_STEPS: Final[StepPlan] = (
    ("notice", "Avisando a los jugadores"),
    ("save", "Guardando el mundo"),
    ("stop", "Apagando el servidor"),
    ("start", "Encendiendo el servidor"),
    _READY_STEP,
)


class ServerState(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    CRASHED = "CRASHED"


class ServerProcessError(RuntimeError):
    """Java process operation error."""

    status_code = 503


class ServerBusyError(ServerProcessError):
    """Another start/stop/restart operation is already in progress."""

    status_code = 409


class ServerStartTimeoutError(ServerProcessError):
    """The process is alive but Minecraft has not reported it is ready yet."""

    status_code = 504


class ExternalServerRunningError(ServerProcessError):
    """A server the panel did not start is already running (run.bat, previous session...)."""

    status_code = 409


class ServerSettingsFileError(ServerProcessError):
    """craftpanel.txt names a start script or Java that cannot be used."""

    status_code = 409


def _describe_countdown(seconds: int) -> str:
    """"90 segundos", "2 minutos": how long until a restart, for the chat."""
    if seconds >= 120 and seconds % 60 == 0:
        return f"{seconds // 60} minutos"
    return f"{seconds} segundos"


def server_java_bin_directory(configured: Settings) -> Path | None:
    """Folder of the Java the server should use: craftpanel.txt's, else the best one found.

    "Best" is the lowest installed Java that is new enough for the server's Minecraft
    version (tools/java, JAVA_HOME, PATH, the registry, Program Files or the Minecraft
    Launcher's own runtime), so a Java that is not on PATH still works.
    """
    if (chosen := configured.server_java_executable) is not None:
        return chosen.parent
    from app.services.runtime_discovery import RuntimeDiscoveryService  # noqa: PLC0415 - avoids an import cycle

    try:
        status = RuntimeDiscoveryService(configured).server_java()
    except Exception:  # noqa: BLE001 - detection must never block a start; PATH still applies
        logger.warning("Java detection failed; using the Java on PATH.", exc_info=True)
        status = None
    if status is not None and status.state == "available" and status.executable:
        return Path(status.executable).parent
    return configured.server_java_bin_directory


def server_environment(configured: Settings) -> dict[str, str]:
    """Environment for the server process: the chosen Java goes first on PATH."""
    environment = os.environ.copy()
    java_bin = server_java_bin_directory(configured)
    if java_bin is not None:
        environment["PATH"] = f"{java_bin}{os.pathsep}{environment.get('PATH', '')}"
    return environment


@dataclass(frozen=True, slots=True)
class TerminalLine:
    timestamp: str
    stream: str
    message: str
    # Grows by one per line, so a reconnecting browser can skip the lines it already shows.
    seq: int = 0


class MinecraftServerManager:
    """Sole authority over the server process on the host.

    All process and I/O operations use ``asyncio`` APIs: the panel's event
    loop is never blocked while Java is running.
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
        self._external_detector = ExternalServerDetector(self._settings)
        self._process: asyncio.subprocess.Process | None = None
        self._state = ServerState.STOPPED
        self._online_players: dict[str, str] = {}
        self._log_buffer: deque[TerminalLine] = deque(maxlen=self._settings.log_buffer_size)
        self._log_seq = 0
        # Line numbers restart with the panel; browsers compare this to know when that happened.
        self.log_session = uuid.uuid4().hex[:12]
        self._lock = asyncio.Lock()
        # Serializes whole lifecycle operations; _lock only guards process creation.
        self._lifecycle_lock = asyncio.Lock()
        self._lifecycle_operation: str | None = None
        self._restart_cancelled = False
        self._reader_tasks: set[asyncio.Task[None]] = set()
        self._watcher_task: asyncio.Task[None] | None = None
        self._stop_requested = False
        self._dev_mode: bool = False
        self._start_requested_time: float | None = None
        self._ready_notified: bool = False
        self._last_join_notified: dict[str, float] = {}
        self._last_leave_notified: dict[str, float] = {}
        self._last_death_notified: dict[str, float] = {}
        self._crash_listeners: list[Callable[[], Coroutine[Any, Any, None]]] = []
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
    def lifecycle_operation(self) -> str | None:
        """Name of the lifecycle operation in progress, if any."""
        return self._lifecycle_operation

    @contextlib.asynccontextmanager
    async def _exclusive_lifecycle(self, operation: str) -> AsyncIterator[None]:
        # Reject instead of queueing: a queued stop must never hit a freshly restarted server.
        if self._lifecycle_lock.locked():
            raise ServerBusyError(
                f"Ya hay una operación en curso ({self._lifecycle_operation}). Esperá a que termine."
            )
        async with self._lifecycle_lock:
            self._lifecycle_operation = operation
            try:
                yield
            finally:
                self._lifecycle_operation = None

    @property
    def process_pid(self) -> int | None:
        """Launcher PID; MetricsService resolves Java when it is a child process."""
        return self._process.pid if self.is_running and self._process is not None else None

    def add_crash_listener(self, listener: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """Run ``listener`` each time the server ends on its own (not a requested stop or kill)."""
        if listener not in self._crash_listeners:
            self._crash_listeners.append(listener)

    async def log_system(self, message: str) -> None:
        """Show a panel message in the console, like the panel's own start/stop notes."""
        await self._record_log("system", message)

    @property
    def history(self) -> list[dict[str, Any]]:
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

    async def start(self, dev_mode: bool = False, progress: ProgressCallback | None = None) -> bool:
        """Start the server; return ``False`` if a process was already running."""
        async with self._exclusive_lifecycle("inicio"):
            report(progress, "start", "Abriendo el servidor de Minecraft.")
            return await self._start_process(dev_mode)

    async def _start_process(self, dev_mode: bool) -> bool:
        async with self._lock:
            if self.is_running:
                return False

            self._online_players.clear()
            self._dev_mode = dev_mode

            if not self._settings.server_directory or not self._settings.server_directory.is_dir():
                raise ServerProcessError(
                    f"No existe el directorio del servidor: {self._settings.server_directory}"
                )
            file_settings = await asyncio.to_thread(read_server_settings, self._settings)
            if problem := file_settings.launch_problem:
                raise ServerSettingsFileError(problem)
            if file_settings.java and not Path(file_settings.java).is_file():
                raise ServerSettingsFileError(
                    "No encontramos el Java elegido en craftpanel.txt. "
                    "Corregilo en Ajustes › Tu servidor o dejalo vacío."
                )
            if (memory := file_settings.value("memory")) is not None:
                await asyncio.to_thread(self._apply_memory, memory)
            if not self._settings.server_start_script.is_file():
                raise ServerProcessError(
                    f"No encontramos {self._settings.server_start_script.name} en la carpeta del servidor. "
                    "Revisá «Archivo para encender» en Ajustes › Tu servidor."
                )

            external = await asyncio.to_thread(self._external_detector.detect)
            if external is not None:
                raise ExternalServerRunningError(external.explanation)

            self._state = ServerState.STARTING
            self._stop_requested = False
            self._start_requested_time = asyncio.get_running_loop().time()
            self._ready_notified = False
            try:
                environment = await asyncio.to_thread(server_environment, self._settings)
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
            await asyncio.to_thread(self._external_detector.remember_panel_process, self._process.pid)
            await self._broadcast_status()
            if not self._dev_mode:
                asyncio.create_task(discord_service.send_server_starting(), name="discord-server-starting")
            return True

    def _apply_memory(self, memory_gb: int) -> None:
        """craftpanel.txt's memory is the source of truth: write it into user_jvm_args.txt before starting."""
        from app.services.jvm_args import JvmArgsMissingError, apply_ram
        from app.services.protected_paths import ProtectedPathError

        try:
            apply_ram(self._settings, memory_gb)
        except JvmArgsMissingError:
            logger.info("No user_jvm_args.txt; the start script decides the server's memory.")
        except ProtectedPathError:
            logger.info("user_jvm_args.txt is protected in craftpanel.txt; its memory is left as it is.")
        except OSError as error:
            raise ServerProcessError(f"No se pudo poner la memoria en user_jvm_args.txt: {error}") from error

    async def stop(self) -> bool:
        """Request a clean stop through the Minecraft console."""
        async with self._exclusive_lifecycle("detención"):
            return await self._request_stop()

    async def _request_stop(self) -> bool:
        if not self.is_running:
            return False
        self._stop_requested = True
        await self.send_command("/stop")
        return True

    async def restart(self, dev_mode: bool | None = None, progress: ProgressCallback | None = None) -> bool:
        """Stop (forcing it after the grace period) and start again as one atomic operation.

        Returns ``False`` when a kill cancelled the restart before the new start.
        ``progress`` receives the ``stop`` and ``start`` steps of :data:`RESTART_STEPS`.
        """
        async with self._exclusive_lifecycle("reinicio"):
            return await self._restart_process(self._dev_mode if dev_mode is None else dev_mode, progress)

    async def graceful_restart(
        self,
        countdown_seconds: int = 10,
        dev_mode: bool | None = None,
        progress: ProgressCallback | None = None,
    ) -> bool:
        """Restart the server, warning players in chat and saving the world.

        ``progress`` receives the steps of :data:`GRACEFUL_RESTART_STEPS` except ``ready``.
        """
        async with self._exclusive_lifecycle("reinicio suave"):
            target_dev_mode = self._dev_mode if dev_mode is None else dev_mode
            if self.is_running:
                await self._announce_restart(countdown_seconds, progress)
            return await self._restart_process(target_dev_mode, progress)

    async def _announce_restart(self, countdown_seconds: int, progress: ProgressCallback | None = None) -> None:
        try:
            when = _describe_countdown(countdown_seconds)
            report(progress, "notice", f"Avisamos en el chat: reinicio en {when}.")
            await self.send_command(
                f"/say §c[Servidor] El servidor se reiniciará en {when}. ¡Guarden sus cosas!"
            )
            if countdown_seconds > 5:
                await asyncio.sleep(countdown_seconds - 5)
                report(progress, "notice", "Avisamos en el chat: reinicio en 5 segundos.")
                await self.send_command("/say §e[Servidor] Reinicio en 5 segundos...")
                await asyncio.sleep(4)
                await self.send_command("/say §4[Servidor] Reiniciando ahora...")
                await asyncio.sleep(1)
            else:
                await asyncio.sleep(countdown_seconds)

            report(progress, "save", "Guardando el mundo en el disco.")
            with contextlib.suppress(Exception):
                await self.send_command("/save-all flush")
                await asyncio.sleep(1.5)
        except Exception:
            pass

    async def _restart_process(self, dev_mode: bool, progress: ProgressCallback | None = None) -> bool:
        self._restart_cancelled = False
        if self.is_running:
            report(progress, "stop", "Esperando a que el servidor se apague.")
            await self._request_stop()
            try:
                await asyncio.wait_for(
                    self.wait_until_stopped(), timeout=self._settings.graceful_stop_timeout_seconds
                )
            except TimeoutError:
                report(progress, "stop", "No respondió a tiempo; forzamos el cierre.")
                await self._kill_process()
                await self.wait_until_stopped()
        if self._restart_cancelled:
            await self._record_log("system", "Reinicio cancelado: se forzó la detención del servidor.")
            return False
        report(progress, "start", "Abriendo el servidor de Minecraft.")
        if not await self._start_process(dev_mode):
            raise ServerProcessError("El servidor seguía en ejecución y no pudo reiniciarse.")
        return True

    async def kill(self) -> bool:
        """Kill the process tree when a clean shutdown does not respond.

        Deliberately bypasses the lifecycle lock so it always works as an emergency
        stop; if a restart is in progress, its pending start is cancelled.
        """
        if self._lifecycle_lock.locked():
            self._restart_cancelled = True
        return await self._kill_process()

    async def _kill_process(self) -> bool:
        process = self._process
        if process is None or process.returncode is not None:
            return False

        self._stop_requested = True
        if os.name == "nt":
            # Use the absolute path: a damaged PATH must not break the emergency stop.
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            try:
                taskkill = await asyncio.create_subprocess_exec(
                    os.path.join(system_root, "System32", "taskkill.exe"),
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await taskkill.wait()
            except OSError as error:
                logger.warning("taskkill unavailable (%s); killing only the launcher process.", error)
                process.kill()
        else:
            process.kill()
        return True

    async def send_command(self, command: str) -> None:
        """Write a single command to STDIN without using a shell."""
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
        """Run a command and wait for its confirmation in the console.

        Used so a backup does not compress files while Minecraft is still
        flushing pending world changes to disk.
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
        """Shut the process down cleanly when FastAPI stops."""
        # The panel is going away: never let an in-flight restart start a new process.
        self._restart_cancelled = True
        if not self.is_running:
            return

        process = self._process
        assert process is not None
        await self._request_stop()
        try:
            await asyncio.wait_for(process.wait(), timeout=self._settings.graceful_stop_timeout_seconds)
        except TimeoutError:
            logger.warning("El servidor no respondió a /stop; se forzará su cierre.")
            await self._kill_process()
            await process.wait()

    async def wait_until_ready(self, timeout_seconds: float = 120.0) -> None:
        """Wait for Minecraft's readiness line without guessing a fixed startup delay."""
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            if self._state == ServerState.RUNNING:
                return
            if not self.is_running:
                raise ServerProcessError("El servidor se cerró antes de terminar de encender.")
            await asyncio.sleep(0.2)
        raise ServerStartTimeoutError("El servidor todavía no terminó de encender.")

    async def wait_until_stopped(self) -> None:
        """Cooperatively wait for the current process to exit."""
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

        await asyncio.to_thread(self._external_detector.forget_panel_process)
        await self._record_log("system", f"Proceso del servidor finalizado con código {exit_code}.")
        await self._broadcast_status()
        if not self._dev_mode:
            if self._state == ServerState.STOPPED:
                asyncio.create_task(discord_service.send_server_stopped(), name="discord-server-stopped")
            else:
                report = await crash_analyzer.get_latest_crash_report()
                asyncio.create_task(discord_service.send_crash(report), name="discord-server-crashed")
        # Test runs (dev mode) never trigger automatic restarts.
        crashed = self._state == ServerState.CRASHED and not self._dev_mode
        self._dev_mode = False
        if crashed:
            for listener in tuple(self._crash_listeners):
                asyncio.create_task(listener(), name="server-crash-listener")

    async def _record_log(self, stream: str, message: str) -> None:
        # Java and mods print absolute paths; never show the host's user folder in the console.
        message = redact_personal_paths(message)
        self._log_seq += 1
        line = TerminalLine(
            timestamp=datetime.now(UTC).isoformat(),
            stream=stream,
            message=message,
            seq=self._log_seq,
        )
        self._log_buffer.append(line)

        # Detect when the server finishes starting up ("Done (X.XXs)!")
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

        # Track player join and leave events (debounced against duplicates)
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
