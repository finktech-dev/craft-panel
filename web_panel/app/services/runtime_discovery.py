"""Portable, read-only host discovery for the panel's first-run assistant.

This module intentionally never starts Java, manages processes, or opens,
enumerates, or changes worlds, backups, or secrets.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

from app.core.config import Settings, settings
from app.schemas.runtime import (
    AccountProtectionStatus,
    HostRuntimeDiscovery,
    JavaRuntimeStatus,
    MinecraftInstallationStatus,
)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class RuntimeDiscoveryService:
    """Inspects minimal host capabilities without mutating them.

    Dependencies are injectable so the behavior is testable for Windows, Linux,
    and macOS without relying on the host running the test suite.
    """

    def __init__(
        self,
        configured_settings: Settings = settings,
        *,
        system_name: str | None = None,
        environ: Mapping[str, str] | None = None,
        which: Callable[[str], str | None] = shutil.which,
        command_runner: CommandRunner = subprocess.run,
    ) -> None:
        self._settings = configured_settings
        self._system_name = system_name or platform.system()
        self._environ = environ if environ is not None else os.environ
        self._which = which
        self._command_runner = command_runner

    def discover(self) -> HostRuntimeDiscovery:
        return HostRuntimeDiscovery(
            operating_system=self._operating_system(),
            java=self._discover_java(),
            minecraft=self._discover_minecraft(),
            accounts=self._discover_account_protection(),
        )

    def _operating_system(self) -> Literal["windows", "linux", "macos", "other"]:
        normalized = self._system_name.casefold()
        if normalized == "windows":
            return "windows"
        if normalized == "linux":
            return "linux"
        if normalized == "darwin":
            return "macos"
        return "other"

    def _java_candidates(self) -> tuple[Path, ...]:
        executable_name = "java.exe" if self._operating_system() == "windows" else "java"
        candidates: list[Path] = []
        assert self._settings.tools_directory is not None
        local_java = self._settings.tools_directory / "java" / "bin" / executable_name
        if local_java.is_file():
            candidates.append(local_java)
        java_home = self._environ.get("JAVA_HOME")
        if java_home:
            candidates.append(Path(java_home) / "bin" / executable_name)
        if located := self._which("java"):
            candidates.append(Path(located))

        unique: list[Path] = []
        for candidate in candidates:
            if candidate not in unique:
                unique.append(candidate)
        return tuple(unique)

    def _discover_java(self) -> JavaRuntimeStatus:
        candidates = self._java_candidates()
        if not candidates:
            return JavaRuntimeStatus(state="missing", message="No se encontró Java. Podés instalarlo en el sistema o descomprimirlo en tools/java/bin dentro de este proyecto.")

        required_major = self._required_java_major()
        first_available: tuple[Path, str, int | None] | None = None
        for executable in candidates:
            for version_flag in ("--version", "-version"):
                try:
                    result = self._command_runner([str(executable), version_flag], capture_output=True, text=True, timeout=5, check=False)
                except (OSError, subprocess.SubprocessError):
                    break
                output = "\n".join(part for part in (result.stdout, result.stderr) if part)
                version = self._parse_java_version(output)
                if result.returncode == 0 and version is not None:
                    major_version = self._java_major(version)
                    if major_version is not None and major_version >= required_major:
                        return JavaRuntimeStatus(state="available", executable=str(executable), version=version, major_version=major_version, message=f"Java {major_version} está disponible y es compatible con Minecraft {self._settings.minecraft_version}.")
                    if first_available is None:
                        first_available = (executable, version, major_version)
                    break
        if first_available is not None:
            executable, version, major_version = first_available
            return JavaRuntimeStatus(state="unusable", executable=str(executable), version=version, major_version=major_version, message=f"Se encontró Java {major_version or version}, pero Minecraft {self._settings.minecraft_version} necesita Java {required_major} o superior.")
        return JavaRuntimeStatus(state="unusable", executable=str(candidates[0]), message="Se encontró Java, pero ninguna instalación detectada respondió correctamente a la consulta de versión.")

    def _required_java_major(self) -> int:
        parts = self._settings.minecraft_version.split(".")
        try:
            minor = int(parts[1])
            patch = int(parts[2]) if len(parts) > 2 else 0
        except (IndexError, ValueError):
            return 21
        if minor > 20 or (minor == 20 and patch >= 5):
            return 21
        if minor >= 18:
            return 17
        if minor == 17:
            return 16
        return 8
    @staticmethod
    def _parse_java_version(output: str) -> str | None:
        match = re.search(r'(?:openjdk|java)\s+(?:version\s+)?["\']?(\d+(?:[._]\d+)*)', output, re.IGNORECASE)
        return match.group(1) if match else None

    @staticmethod
    def _java_major(version: str) -> int | None:
        parts = version.replace("_", ".").split(".")
        try:
            return int(parts[1] if parts[0] == "1" and len(parts) > 1 else parts[0])
        except ValueError:
            return None

    def _server_root(self) -> Path:
        assert self._settings.server_directory is not None
        return self._settings.server_directory

    def _discover_minecraft(self) -> MinecraftInstallationStatus:
        root = self._server_root()
        native_script = root / ("run.bat" if self._operating_system() == "windows" else "run.sh")
        markers = {
            "neoforge": root / "libraries" / "net" / "neoforged" / "neoforge",
            "forge": root / "libraries" / "net" / "minecraftforge" / "forge",
            "fabric": root / "fabric-server-launch.jar",
            "paper": root / "paper.jar",
            "vanilla": root / "server.jar",
        }
        loader = next((name for name, marker in markers.items() if marker.exists()), None)
        has_runtime = loader is not None or any(root.glob("*.jar"))
        if not has_runtime:
            return MinecraftInstallationStatus(
                state="not_detected",
                root=str(root),
                message="No se detectó un runtime de servidor. Podés instalar uno desde este panel.",
            )
        start_script = native_script if native_script.is_file() else None
        return MinecraftInstallationStatus(
            state="detected",
            root=str(root),
            loader=loader or "custom",
            start_script=str(start_script) if start_script else None,
            message="Se detectó una instalación local sin iniciar ni modificar el servidor.",
        )
    def _discover_account_protection(self) -> AccountProtectionStatus:
        properties_path = self._server_root() / "server.properties"
        if not properties_path.is_file():
            return AccountProtectionStatus(
                state="unknown",
                message="No hay server.properties para comprobar cómo se protegen las cuentas.",
            )
        try:
            properties = self._read_properties(properties_path)
        except OSError:
            return AccountProtectionStatus(state="unknown", message="No se pudo leer server.properties.")

        online_mode = properties.get("online-mode", "true").casefold() == "true"
        whitelist_enabled = properties.get("white-list", "false").casefold() == "true"
        if online_mode:
            state: Literal["online_accounts", "whitelist", "unrestricted", "unknown"] = "online_accounts"
            message = "El servidor valida las cuentas con los servicios de Minecraft."
        elif whitelist_enabled:
            state = "whitelist"
            message = "El servidor usa lista blanca; el panel no lee ni muestra identidades de jugadores."
        else:
            state = "unrestricted"
            message = "El servidor no valida cuentas ni tiene lista blanca activa."
        return AccountProtectionStatus(
            state=state,
            online_mode=online_mode,
            whitelist_enabled=whitelist_enabled,
            message=message,
        )

    @staticmethod
    def _read_properties(path: Path) -> dict[str, str]:
        properties: dict[str, str] = {}
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            properties[key.strip()] = value.strip()
        return properties


runtime_discovery_service = RuntimeDiscoveryService()
