"""Detect Minecraft servers running outside the panel (run.bat, another tool, a previous panel session)."""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import psutil

from app.core.config import Settings, settings

logger = logging.getLogger(__name__)

_DEFAULT_SERVER_PORT = 25565
_JAVA_NAMES = frozenset({"java.exe", "javaw.exe", "java", "javaw"})
_PID_FILENAME = ".server_process.json"

ExternalReason = Literal["previous_panel_session", "server_directory", "port"]


@dataclass(frozen=True, slots=True)
class ExternalServer:
    pid: int
    name: str
    reason: ExternalReason
    port: int

    @property
    def message(self) -> str:
        if self.reason == "previous_panel_session":
            origin = "Quedó abierto de una vez anterior que usaste el panel."
        elif self.reason == "server_directory":
            origin = "Lo abrieron fuera del panel, por ejemplo con run.bat."
        else:
            origin = f"Otro programa está usando el puerto {self.port}, que el servidor necesita."
        return f"{origin} Cerralo desde su ventana o desde acá para poder manejarlo con el panel."


class ExternalServerDetector:
    """Find server processes the panel did not start, so it never opens a second instance."""

    def __init__(self, configured_settings: Settings = settings) -> None:
        self._settings = configured_settings

    @property
    def pid_file(self) -> Path:
        assert self._settings.panel_directory is not None
        return self._settings.panel_directory / _PID_FILENAME

    def server_port(self) -> int:
        assert self._settings.server_directory is not None
        properties = self._settings.server_directory / "server.properties"
        try:
            for line in properties.read_text(encoding="utf-8", errors="replace").splitlines():
                key, separator, value = line.partition("=")
                if separator and key.strip() == "server-port":
                    port = int(value.strip())
                    if 1 <= port <= 65535:
                        return port
        except (OSError, ValueError):
            pass
        return _DEFAULT_SERVER_PORT

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

    def detect(self, own_pid: int | None = None) -> ExternalServer | None:
        """Return the first foreign server process, ignoring the tree the panel itself runs."""
        own_tree = self._process_tree(own_pid)
        previous_tree = self._process_tree(self._remembered_pid())
        found = self._find_in_server_directory(own_tree) or self._find_on_port(own_tree)
        if found is None:
            return None
        pid, name, reason = found
        if pid in previous_tree:
            reason = "previous_panel_session"
        return ExternalServer(pid=pid, name=name, reason=reason, port=self.server_port())

    def terminate(self, pid: int, own_pid: int | None = None) -> bool:
        """Kill a detected external server tree; refuses PIDs that are not currently detected."""
        detected = self.detect(own_pid)
        if detected is None or detected.pid != pid:
            return False
        try:
            process = psutil.Process(pid)
            for child in process.children(recursive=True):
                child.kill()
            process.kill()
            process.wait(timeout=15)
        except psutil.NoSuchProcess:
            pass
        except (psutil.AccessDenied, psutil.TimeoutExpired) as error:
            logger.warning("Could not terminate external server %s: %s", pid, error)
            return False
        self.forget_panel_process()
        return True

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

    def _find_in_server_directory(self, own_tree: set[int]) -> tuple[int, str, ExternalReason] | None:
        assert self._settings.server_directory is not None
        server_directory = os.path.normcase(str(self._settings.server_directory.resolve()))
        for process in psutil.process_iter(["pid", "name"]):
            name = (process.info.get("name") or "").lower()
            if process.info["pid"] in own_tree or name not in _JAVA_NAMES:
                continue
            try:
                cwd = os.path.normcase(str(Path(process.cwd()).resolve()))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
                continue
            if cwd == server_directory:
                return process.info["pid"], name, "server_directory"
        return None

    def _find_on_port(self, own_tree: set[int]) -> tuple[int, str, ExternalReason] | None:
        port = self.server_port()
        try:
            connections = psutil.net_connections(kind="tcp")
        except (psutil.AccessDenied, OSError):
            return None
        for connection in connections:
            if (
                connection.status == psutil.CONN_LISTEN
                and connection.laddr
                and connection.laddr.port == port
                and connection.pid
                and connection.pid not in own_tree
            ):
                try:
                    name = psutil.Process(connection.pid).name().lower()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    name = "desconocido"
                return connection.pid, name, "port"
        return None


external_server_detector = ExternalServerDetector()
