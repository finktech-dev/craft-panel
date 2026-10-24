"""Detect Minecraft servers running outside the panel (run.bat, another tool, a previous panel session).

Detection is evidence based. Only Java processes and whatever listens on the
server port are inspected (never every process on the machine), and for each
one the detector collects signals:

* it holds the active world's ``session.lock`` open (Minecraft keeps it open
  while the world is loaded, so this is the strongest signal);
* its working folder is the server folder;
* its command line mentions the server folder, a Minecraft launch marker
  (``@user_jvm_args.txt``, Forge/NeoForge libraries, Fabric's launcher,
  ``-jar server.jar``, ``nogui``) or one of the user's ``[reconocer]`` words;
* it listens on ``server-port``;
* it belongs to the process tree the panel itself started last time.

A verdict is then given: ``is_our_server`` (a Java process with at least one
confident signal: our world's lock, our folder, our folder in its command
line, a user word, or our previous session), ``other_java_server`` (it looks
like Minecraft but from another folder) or ``other_program_on_port``. Only
``is_our_server`` may be force-closed; starting is refused whenever anything
holds our world's lock or our port, or our own server is already open.
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import psutil

from app.core.config import Settings, settings
from app.core.path_safety import is_safe_component

logger = logging.getLogger(__name__)

_DEFAULT_SERVER_PORT = 25565
_JAVA_NAMES = frozenset({"java.exe", "javaw.exe", "java", "javaw"})
_PID_FILENAME = ".server_process.json"
_PROCESS_ERRORS = (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError)
# Minecraft saves the world when it gets Ctrl+C or SIGTERM; give it this long before forcing.
GRACEFUL_STOP_SECONDS = 60
CloseOutcome = Literal["saved", "forced"]

# Runs in a separate, windowless Python: it joins the server's console and presses Ctrl+C there,
# like typing it in the server window. It refuses when the panel shares that console, because the
# panel would get the Ctrl+C too. Exit code 0 means the keystroke was sent.
_WINDOWS_CTRL_C_HELPER = r"""
import ctypes, sys
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
target, panel = int(sys.argv[1]), int(sys.argv[2])
kernel32.FreeConsole()
if not kernel32.AttachConsole(target):
    sys.exit(2)
pids = (ctypes.c_uint32 * 64)()
count = kernel32.GetConsoleProcessList(pids, 64)
if count == 0 or count > 64 or panel in list(pids)[:count]:
    sys.exit(3)
kernel32.SetConsoleCtrlHandler(None, True)
sys.exit(0 if kernel32.GenerateConsoleCtrlEvent(0, 0) else 4)
"""


def request_graceful_stop(pid: int) -> bool:
    """Ask a server process to stop the way Ctrl+C in its window would. True if the request went out."""
    if os.name == "nt":
        try:
            result = subprocess.run(
                [sys.executable, "-I", "-c", _WINDOWS_CTRL_C_HELPER, str(pid), str(os.getpid())],
                timeout=15,
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            logger.warning("Could not ask the server to stop gracefully: %s", error)
            return False
        return result.returncode == 0
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    return True
# Command-line fragments that only a Minecraft server launch tends to have.
_MINECRAFT_MARKERS: tuple[tuple[str, str], ...] = (
    ("@user_jvm_args.txt", "@user_jvm_args.txt"),
    ("@libraries/net/neoforged/", "las librerías de NeoForge"),
    ("@libraries/net/minecraftforge/", "las librerías de Forge"),
    ("fabric-server-launch.jar", "fabric-server-launch.jar"),
    ("-jar server.jar", "server.jar"),
    ("nogui", "nogui"),
)

ExternalReason = Literal[
    "previous_panel_session", "world_lock", "server_directory", "command_line", "hint", "port", "minecraft_like"
]
ExternalKind = Literal["is_our_server", "other_java_server", "other_program_on_port"]


def is_java_name(name: str) -> bool:
    return name.lower() in _JAVA_NAMES


@dataclass(frozen=True, slots=True)
class ExternalServer:
    pid: int
    name: str
    reason: ExternalReason
    port: int
    kind: ExternalKind = "is_our_server"
    reasons: tuple[str, ...] = ()

    @property
    def can_terminate(self) -> bool:
        """Only a Java process confidently identified as this server may be force-closed."""
        return self.kind == "is_our_server" and is_java_name(self.name)

    @property
    def message(self) -> str:
        if self.kind == "other_program_on_port" or (self.kind == "is_our_server" and not is_java_name(self.name)):
            if self.reason == "previous_panel_session":
                return (
                    f"Quedó abierto de una vez anterior que usaste el panel y está usando el puerto {self.port}. "
                    "Cerralo desde su ventana para poder manejar el servidor con el panel."
                )
            return (
                f"Otro programa ({self.name}) está usando el puerto {self.port}, que el servidor necesita. "
                "Cerralo desde su propia ventana para poder encender el servidor."
            )
        if self.kind == "other_java_server":
            return (
                "Hay otro servidor de Minecraft abierto, de otra carpeta, y está usando lo que este necesita. "
                "Cerralo desde su propia ventana para poder encender este."
            )
        if self.reason == "previous_panel_session":
            origin = "Quedó abierto de una vez anterior que usaste el panel."
        else:
            origin = "Lo abrieron fuera del panel, por ejemplo con run.bat."
        return f"{origin} Cerralo desde su ventana o desde acá para poder manejarlo con el panel."

    @property
    def explanation(self) -> str:
        """``message`` plus what the panel found, for refusals such as a blocked start."""
        if not self.reasons:
            return self.message
        return f"{self.message} Lo que encontramos: {'; '.join(self.reasons)}."


@dataclass(slots=True)
class _Evidence:
    pid: int
    name: str
    holds_port: bool = False
    holds_world: bool = False
    cwd_match: bool = False
    command_line_folder: bool = False
    markers: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    previous_session: bool = False

    @property
    def is_java(self) -> bool:
        return is_java_name(self.name)

    @property
    def confident(self) -> bool:
        return self.is_java and (
            self.holds_world or self.cwd_match or self.command_line_folder or bool(self.hints) or self.previous_session
        )


class ExternalServerDetector:
    """Find server processes the panel did not start, so it never opens a second instance."""

    def __init__(
        self,
        configured_settings: Settings = settings,
        graceful_stop: Callable[[int], bool] = request_graceful_stop,
        graceful_timeout: float = GRACEFUL_STOP_SECONDS,
    ) -> None:
        self._settings = configured_settings
        self._graceful_stop = graceful_stop
        self._graceful_timeout = graceful_timeout

    @property
    def pid_file(self) -> Path:
        assert self._settings.panel_directory is not None
        return self._settings.panel_directory / _PID_FILENAME

    def _properties(self) -> dict[str, str]:
        assert self._settings.server_directory is not None
        properties = self._settings.server_directory / "server.properties"
        values: dict[str, str] = {}
        try:
            for line in properties.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.lstrip().startswith(("#", "!")):
                    continue
                key, separator, value = line.partition("=")
                if separator:
                    values[key.strip()] = value.strip()
        except OSError:
            pass
        return values

    def server_port(self) -> int:
        try:
            port = int(self._properties().get("server-port", ""))
        except ValueError:
            return _DEFAULT_SERVER_PORT
        return port if 1 <= port <= 65535 else _DEFAULT_SERVER_PORT

    def level_name(self) -> str:
        name = self._properties().get("level-name", "world") or "world"
        return name if is_safe_component(name) else "world"

    def remember_panel_process(self, pid: int) -> None:
        """Persist the launcher PID so a restarted panel can recognise its own orphan."""
        temporary = self.pid_file.with_name(f".{self.pid_file.name}.{uuid.uuid4().hex}.tmp")
        try:
            self.pid_file.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps({"pid": pid}) + "\n", encoding="utf-8")
            os.replace(temporary, self.pid_file)
        except OSError as error:
            logger.warning("Could not persist the server PID: %s", error)
        finally:
            if temporary.exists():
                temporary.unlink()

    def forget_panel_process(self) -> None:
        try:
            self.pid_file.unlink(missing_ok=True)
        except OSError as error:
            logger.warning("Could not remove the server PID file: %s", error)

    # -- detection ------------------------------------------------------

    def inspect(self, own_pid: int | None = None) -> list[ExternalServer]:
        """Every relevant foreign process with its verdict, most relevant first."""
        own_tree = self._process_tree(own_pid)
        previous_tree = self._process_tree(self._remembered_pid())
        port = self.server_port()
        world = self.level_name()
        port_holders = self._port_holders(port, own_tree)
        candidates: dict[int, str] = dict(port_holders)
        for pid, name in self._java_processes(own_tree):
            candidates.setdefault(pid, name)

        hints = self._hints()
        found: list[tuple[int, ExternalServer]] = []
        for pid, name in candidates.items():
            evidence = self._collect(pid, name, world, hints)
            evidence.holds_port = pid in port_holders
            evidence.previous_session = pid in previous_tree
            verdict = self._verdict(evidence, port, world)
            if verdict is not None:
                found.append(verdict)
        found.sort(key=lambda item: item[0], reverse=True)
        return [server for _, server in found]

    def detect(self, own_pid: int | None = None) -> ExternalServer | None:
        """The foreign process that blocks starting this server, if any."""
        found = self.inspect(own_pid)
        return found[0] if found else None

    def _verdict(self, evidence: _Evidence, port: int, world: str) -> tuple[int, ExternalServer] | None:
        reasons: list[str] = []
        if evidence.holds_world:
            reasons.append(f"Tiene abierto el mundo {world}")
        if evidence.previous_session:
            reasons.append("Lo abrió el panel la vez anterior")
        if evidence.cwd_match:
            reasons.append("Se abrió desde la carpeta del servidor")
        if evidence.command_line_folder:
            reasons.append("Su línea de inicio menciona la carpeta del servidor")
        reasons.extend(f"Coincide con «{hint}», una de tus palabras para reconocerlo" for hint in evidence.hints)
        if evidence.markers and evidence.is_java:
            reasons.append(f"Arranca como un servidor de Minecraft ({', '.join(evidence.markers)})")
        if evidence.holds_port:
            reasons.append(f"Usa el puerto {port}")
        if not evidence.is_java:
            reasons.append(f"Es otro programa ({evidence.name}), no un servidor de Minecraft")

        if evidence.confident:
            kind: ExternalKind = "is_our_server"
            score = 300
        elif evidence.holds_world or evidence.holds_port or evidence.previous_session:
            # Something else really is in the way: it holds our world or our port.
            kind = "other_java_server" if evidence.is_java and evidence.markers else "other_program_on_port"
            score = 200 if evidence.holds_world else 100
        else:
            # A Java program elsewhere that touches nothing of ours never blocks a start.
            return None

        if evidence.previous_session:
            reason: ExternalReason = "previous_panel_session"
        elif evidence.holds_world:
            reason = "world_lock"
        elif evidence.cwd_match:
            reason = "server_directory"
        elif evidence.command_line_folder:
            reason = "command_line"
        elif evidence.hints:
            reason = "hint"
        elif evidence.holds_port:
            reason = "port"
        else:
            reason = "minecraft_like"
        score += len(reasons)
        return score, ExternalServer(
            pid=evidence.pid, name=evidence.name, reason=reason, port=port, kind=kind, reasons=tuple(reasons)
        )

    def _hints(self) -> tuple[str, ...]:
        from app.services.server_settings_file import read_server_settings

        try:
            return read_server_settings(self._settings).recognize
        except Exception as error:  # noqa: BLE001 - a broken settings file must never break detection
            logger.warning("Could not read the recognition words: %s", error)
            return ()

    def _collect(self, pid: int, name: str, world: str, hints: Iterable[str]) -> _Evidence:
        evidence = _Evidence(pid=pid, name=name)
        assert self._settings.server_directory is not None
        server_directory = self._settings.server_directory.resolve()
        normalized_server = os.path.normcase(str(server_directory))
        lock_path = os.path.normcase(str(server_directory / world / "session.lock"))
        try:
            process = psutil.Process(pid)
        except _PROCESS_ERRORS:
            return evidence

        try:
            cwd = os.path.normcase(str(Path(process.cwd()).resolve()))
            evidence.cwd_match = cwd == normalized_server
        except _PROCESS_ERRORS:
            cwd = ""

        try:
            arguments = [str(part) for part in process.cmdline()]
        except _PROCESS_ERRORS:
            arguments = []
        command_line = " ".join(arguments)
        if command_line:
            normalized = os.path.normcase(command_line)
            folder = re.escape(normalized_server)
            evidence.command_line_folder = re.search(rf"{folder}(?=$|[\\/\"'\s])", normalized) is not None
            if os.sep == "\\":
                forward = re.escape(normalized_server.replace("\\", "/"))
                evidence.command_line_folder |= re.search(rf"{forward}(?=$|[/\"'\s])", normalized) is not None
            comparable = command_line.replace("\\", "/").casefold()
            evidence.markers = [label for needle, label in _MINECRAFT_MARKERS if needle in comparable]
            searchable = f"{command_line} {cwd}".casefold()
            evidence.hints = [hint for hint in hints if hint.casefold() in searchable]

        try:
            open_files = process.open_files()
        except _PROCESS_ERRORS:
            open_files = []
        evidence.holds_world = any(os.path.normcase(str(entry.path)) == lock_path for entry in open_files)
        return evidence

    def terminate(self, pid: int, own_pid: int | None = None) -> bool:
        """Close a detected external server; refuses PIDs that are not currently detected."""
        return self.close(pid, own_pid) is not None

    def close(self, pid: int, own_pid: int | None = None) -> CloseOutcome | None:
        """Stop a detected server, saving the world when it can.

        First the server is asked to stop like Ctrl+C in its window (Minecraft then saves and
        exits). Only if that is impossible or it does not finish in time is the tree killed.
        Returns "saved", "forced", or None when nothing was closed.
        """
        detected = self.detect(own_pid)
        if detected is None or detected.pid != pid:
            return None
        # Never close an unrelated program, or a server we are not sure is this one.
        if not detected.can_terminate:
            return None
        try:
            process = psutil.Process(pid)
        except psutil.NoSuchProcess:
            self.forget_panel_process()
            return "saved"
        if self._graceful_stop(pid):
            try:
                process.wait(timeout=self._graceful_timeout)
            except psutil.TimeoutExpired:
                logger.warning("External server %s did not stop in time; forcing it.", pid)
            else:
                self.forget_panel_process()
                return "saved"
        try:
            for child in process.children(recursive=True):
                child.kill()
            process.kill()
            process.wait(timeout=15)
        except psutil.NoSuchProcess:
            pass
        except (psutil.AccessDenied, psutil.TimeoutExpired) as error:
            logger.warning("Could not terminate external server %s: %s", pid, error)
            return None
        self.forget_panel_process()
        return "forced"

    def _remembered_pid(self) -> int | None:
        try:
            pid = json.loads(self.pid_file.read_text(encoding="utf-8")).get("pid")
        except (OSError, json.JSONDecodeError, AttributeError):
            return None
        return pid if isinstance(pid, int) and psutil.pid_exists(pid) else None

    @staticmethod
    def _process_tree(pid: int | None) -> set[int]:
        if pid is None:
            return set()
        try:
            root = psutil.Process(pid)
            return {pid, *(child.pid for child in root.children(recursive=True))}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return set()

    @staticmethod
    def _java_processes(own_tree: set[int]) -> list[tuple[int, str]]:
        found: list[tuple[int, str]] = []
        for process in psutil.process_iter(["pid", "name"]):
            name = (process.info.get("name") or "").lower()
            pid = process.info.get("pid")
            if pid is not None and pid not in own_tree and name in _JAVA_NAMES:
                found.append((pid, name))
        return found

    @staticmethod
    def _port_holders(port: int, own_tree: set[int]) -> dict[int, str]:
        try:
            connections = psutil.net_connections(kind="tcp")
        except (psutil.AccessDenied, OSError):
            return {}
        holders: dict[int, str] = {}
        for connection in connections:
            if (
                connection.status == psutil.CONN_LISTEN
                and connection.laddr
                and connection.laddr.port == port
                and connection.pid
                and connection.pid not in own_tree
                and connection.pid not in holders
            ):
                try:
                    holders[connection.pid] = psutil.Process(connection.pid).name().lower()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    holders[connection.pid] = "desconocido"
        return holders


external_server_detector = ExternalServerDetector()
