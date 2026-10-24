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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.core.config import Settings, settings
from app.schemas.runtime import (
    AccountProtectionStatus,
    HostRuntimeDiscovery,
    JavaRuntimeStatus,
    MinecraftInstallationStatus,
)
from app.services.java_runtime_service import JavaRuntimeService, JavaRuntimeValidationError
from app.services.server_version_service import ServerVersionInfo, ServerVersionService

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
JavaSource = Literal["craftpanel.txt", "tools/java", "system", "minecraft_launcher"]

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Vendor keys under HKLM\SOFTWARE (and WOW6432Node) whose subkeys hold a Java install folder.
_REGISTRY_KEYS = (
    "JavaSoft",
    "Eclipse Adoptium",
    "Eclipse Foundation",
    "AdoptOpenJDK",
    r"Microsoft\JDK",
    r"Azul Systems\Zulu",
    "BellSoft",
    r"Amazon Corretto",
)
_REGISTRY_VALUES = ("JavaHome", "Path", "InstallationPath")
_REGISTRY_MAX_DEPTH = 4
_REGISTRY_MAX_KEYS = 400
# Default install folders inside Program Files, for installs that left no registry entry.
_COMMON_JAVA_FOLDERS = (
    "Eclipse Adoptium/*/bin/java.exe",
    "Java/*/bin/java.exe",
    "Microsoft/jdk-*/bin/java.exe",
    "Zulu/*/bin/java.exe",
    "BellSoft/*/bin/java.exe",
    "AdoptOpenJDK/*/bin/java.exe",
    "Amazon Corretto/*/bin/java.exe",
)
# The Minecraft Launcher keeps its own Java runtimes (Store app and classic installer).
_LAUNCHER_PACKAGE = "Microsoft.4297127D64EC6_*/LocalCache/Local"
_LAUNCHER_RUNTIMES = ("runtime/*/windows-x64/*/bin/java.exe", "runtime/*/windows-x86/*/bin/java.exe")
_JAVA_MISSING = (
    "No encontramos Java en esta computadora. Con \"Descargar Java\" lo bajamos dentro de la carpeta "
    "del panel, sin instalar nada en Windows."
)
_JAVA_BROKEN = "Encontramos Java, pero no respondió bien. Probá con \"Descargar Java\"."
_VENDORS = (
    ("temurin", "Adoptium"),
    ("adoptium", "Adoptium"),
    ("adoptopenjdk", "AdoptOpenJDK"),
    ("microsoft", "Microsoft"),
    ("zulu", "Azul Zulu"),
    ("corretto", "Amazon Corretto"),
    ("liberica", "BellSoft Liberica"),
    ("bellsoft", "BellSoft Liberica"),
    ("graalvm", "GraalVM"),
    ("java(tm)", "Oracle"),
    ("java hotspot", "Oracle"),
)
_SOURCE_PHRASES: dict[str, str] = {
    "craftpanel.txt": "el que elegiste en craftpanel.txt",
    "tools/java": "en la carpeta tools/java del panel",
    "system": "en tu computadora",
    "minecraft_launcher": "el que trae el launcher de Minecraft",
}


@dataclass(frozen=True, slots=True)
class JavaCandidate:
    path: Path
    source: JavaSource


@dataclass(frozen=True, slots=True)
class JavaProbe:
    version: str
    major: int
    vendor: str | None


_PROBE_CACHE: dict[tuple[str, int, int], JavaProbe] = {}


def java_vendor(version_output: str) -> str | None:
    """Who built a Java, from its ``java -version`` text (None for a plain OpenJDK build)."""
    text = version_output.casefold()
    return next((name for marker, name in _VENDORS if marker in text), None)


def describe_java(major: int, vendor: str | None, source: str) -> str:
    """"Encontramos Java 21 de Adoptium en tu computadora." with no path in it."""
    who = f" de {vendor}" if vendor else ""
    where = _SOURCE_PHRASES.get(source, "en tu computadora")
    separator = ", " if where.startswith("el que") else " "
    return f"Encontramos Java {major}{who}{separator}{where}."


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
        registry: Any = None,
    ) -> None:
        """``registry`` is a ``winreg``-like module; the real one is used only for the real host
        (no ``environ`` given), so tests never read this computer's registry by accident."""
        self._settings = configured_settings
        self._system_name = system_name or platform.system()
        if registry is None and environ is None and self._system_name.casefold() == "windows":
            try:
                import winreg as registry  # noqa: PLC0415 - Windows only
            except ImportError:
                registry = None
        self._registry = registry
        self._environ = environ if environ is not None else os.environ
        self._which = which
        self._command_runner = command_runner
        self._versions = ServerVersionService(configured_settings)

    def discover(self, minecraft_version: str | None = None) -> HostRuntimeDiscovery:
        """Inspect the host; ``minecraft_version`` is the user's pick when no server exists yet."""
        installed = self._versions.detect()
        return HostRuntimeDiscovery(
            operating_system=self._operating_system(),
            java=self._discover_java(installed.minecraft_version or minecraft_version),
            minecraft=self._discover_minecraft(installed),
            accounts=self._discover_account_protection(),
        )

    def java_status(self, minecraft_version: str | None) -> JavaRuntimeStatus:
        """Java check for one specific Minecraft version, used before running an installer."""
        return self._discover_java(minecraft_version)

    def _operating_system(self) -> Literal["windows", "linux", "macos", "other"]:
        normalized = self._system_name.casefold()
        if normalized == "windows":
            return "windows"
        if normalized == "linux":
            return "linux"
        if normalized == "darwin":
            return "macos"
        return "other"

    # --- Java --------------------------------------------------------------------------------

    def _program_files(self) -> list[Path]:
        folders: list[Path] = []
        for name in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
            value = self._environ.get(name)
            if value and Path(value) not in folders:
                folders.append(Path(value))
        return folders

    def _registry_java_homes(self) -> list[Path]:
        """Install folders that Java installers wrote under HKLM (64- and 32-bit views)."""
        registry = self._registry
        if registry is None:
            return []
        homes: list[Path] = []
        access = registry.KEY_READ | getattr(registry, "KEY_WOW64_64KEY", 0)
        budget = [_REGISTRY_MAX_KEYS]

        def walk(path: str, depth: int) -> None:
            if budget[0] <= 0:
                return
            budget[0] -= 1
            try:
                key = registry.OpenKey(registry.HKEY_LOCAL_MACHINE, path, 0, access)
            except OSError:
                return
            try:
                for value_name in _REGISTRY_VALUES:
                    try:
                        value, _kind = registry.QueryValueEx(key, value_name)
                    except OSError:
                        continue
                    if isinstance(value, str) and value.strip():
                        homes.append(Path(value.strip().strip('"')))
                if depth >= _REGISTRY_MAX_DEPTH:
                    return
                children: list[str] = []
                index = 0
                while True:
                    try:
                        children.append(registry.EnumKey(key, index))
                    except OSError:
                        break
                    index += 1
            finally:
                registry.CloseKey(key)
            for child in children:
                walk(f"{path}\\{child}", depth + 1)

        for vendor_key in _REGISTRY_KEYS:
            for view in ("SOFTWARE", r"SOFTWARE\WOW6432Node"):
                walk(f"{view}\\{vendor_key}", 0)
        return homes

    def _java_candidates(self) -> tuple[JavaCandidate, ...]:
        """Every Java worth checking, in the order the panel trusts them."""
        windows = self._operating_system() == "windows"
        executable_name = "java.exe" if windows else "java"
        # A Java chosen in craftpanel.txt is the one the server runs with, so it is the only one checked.
        if (chosen := self._settings.server_java_executable) is not None:
            return (JavaCandidate(chosen, "craftpanel.txt"),)
        candidates: list[JavaCandidate] = []
        assert self._settings.tools_directory is not None
        local_java = self._settings.tools_directory / "java" / "bin" / executable_name
        if local_java.is_file():
            candidates.append(JavaCandidate(local_java, "tools/java"))
        if java_home := self._environ.get("JAVA_HOME"):
            candidates.append(JavaCandidate(Path(java_home.strip('"')) / "bin" / executable_name, "system"))
        if located := self._which("java"):
            candidates.append(JavaCandidate(Path(located), "system"))
        if windows:
            for home in self._registry_java_homes():
                for executable in (home / "bin" / executable_name, home / executable_name):
                    if executable.is_file():
                        candidates.append(JavaCandidate(executable, "system"))
                        break
            for folder in self._program_files():
                for pattern in _COMMON_JAVA_FOLDERS:
                    candidates.extend(JavaCandidate(path, "system") for path in sorted(folder.glob(pattern)) if path.is_file())
            launcher_roots: list[Path] = []
            if local_app_data := self._environ.get("LOCALAPPDATA"):
                launcher_roots.extend(sorted(Path(local_app_data, "Packages").glob(_LAUNCHER_PACKAGE)))
            if program_files_x86 := self._environ.get("ProgramFiles(x86)"):
                launcher_roots.append(Path(program_files_x86) / "Minecraft Launcher")
            for root in launcher_roots:
                for pattern in _LAUNCHER_RUNTIMES:
                    candidates.extend(
                        JavaCandidate(path, "minecraft_launcher") for path in sorted(root.glob(pattern)) if path.is_file()
                    )

        unique: list[JavaCandidate] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = os.path.normcase(os.path.normpath(str(candidate.path)))
            if key not in seen:
                seen.add(key)
                unique.append(candidate)
        return tuple(unique)

    def _probe_java(self, executable: Path) -> JavaProbe | None:
        """Run ``java -version`` (it prints to stderr on every Java); None when it does not work."""
        try:
            stat = executable.stat()
            cache_key: tuple[str, int, int] | None = (str(executable), stat.st_mtime_ns, stat.st_size)
        except OSError:
            cache_key = None
        if cache_key is not None and (cached := _PROBE_CACHE.get(cache_key)) is not None:
            return cached
        try:
            result = self._command_runner(
                [str(executable), "-version"],
                capture_output=True,
                text=True,
                # Console output uses the OEM/ANSI code page; never fail on an unexpected byte.
                errors="replace",
                timeout=15,
                check=False,
                **({"creationflags": _NO_WINDOW} if self._operating_system() == "windows" and _NO_WINDOW else {}),
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        version = self._parse_java_version(output)
        major = self._java_major(version) if version else None
        probe = JavaProbe(version, major, java_vendor(output)) if result.returncode == 0 and major is not None else None
        if cache_key is not None and probe is not None:
            if len(_PROBE_CACHE) > 64:
                _PROBE_CACHE.clear()
            _PROBE_CACHE[cache_key] = probe
        return probe

    def _discover_java(self, minecraft_version: str | None) -> JavaRuntimeStatus:
        candidates = self._java_candidates()
        if not candidates:
            return JavaRuntimeStatus(state="missing", message=_JAVA_MISSING)

        required_major = self._required_java_major(minecraft_version)
        target = f"Minecraft {minecraft_version}" if minecraft_version and required_major else "Minecraft"
        working = [(candidate, probe) for candidate in candidates if (probe := self._probe_java(candidate.path)) is not None]
        if not working:
            return JavaRuntimeStatus(state="unusable", source=candidates[0].source, executable=str(candidates[0].path), message=_JAVA_BROKEN)

        compatible = [item for item in working if item[1].major >= (required_major or 0)]
        if compatible:
            # The lowest Java that is new enough is the one mods are tested with; with no
            # version known yet, the newest one is the most likely to fit what gets picked.
            pick = min if required_major else max
            candidate, probe = pick(compatible, key=lambda item: item[1].major)
            found = describe_java(probe.major, probe.vendor, candidate.source)
            message = f"{found} Sirve para {target}." if required_major else found
            return JavaRuntimeStatus(
                state="available",
                executable=str(candidate.path),
                source=candidate.source,
                vendor=probe.vendor,
                version=probe.version,
                major_version=probe.major,
                message=message,
            )
        candidate, probe = max(working, key=lambda item: item[1].major)
        found = describe_java(probe.major, probe.vendor, candidate.source).rstrip(".")
        return JavaRuntimeStatus(
            state="unusable",
            executable=str(candidate.path),
            source=candidate.source,
            vendor=probe.vendor,
            version=probe.version,
            major_version=probe.major,
            message=f"{found}, pero {target} necesita Java {required_major} o más nuevo.",
        )

    def server_java(self) -> JavaRuntimeStatus:
        """The Java to run the installed server with (its version sets the requirement)."""
        return self._discover_java(self._versions.detect().minecraft_version or self._settings.minecraft_version)

    @staticmethod
    def _required_java_major(minecraft_version: str | None) -> int | None:
        """None when the version is unknown: any working Java counts until one is chosen."""
        if not minecraft_version:
            return None
        try:
            return JavaRuntimeService.required_major(minecraft_version)
        except JavaRuntimeValidationError:
            return None

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

    def _discover_minecraft(self, installed: ServerVersionInfo) -> MinecraftInstallationStatus:
        root = self._server_root()
        # The "start_script" from craftpanel.txt wins; otherwise the script native to this system.
        native_script = (
            self._settings.server_start_script
            if self._settings._server_file_settings().start_script
            else root / ("run.bat" if self._operating_system() == "windows" else "run.sh")
        )
        markers = {
            "neoforge": root / "libraries" / "net" / "neoforged" / "neoforge",
            "forge": root / "libraries" / "net" / "minecraftforge" / "forge",
            "fabric": root / "fabric-server-launch.jar",
            "paper": root / "paper.jar",
            "vanilla": root / "server.jar",
        }
        detected_loader = installed.loader if installed.loader != "unknown" else None
        loader = detected_loader or next((name for name, marker in markers.items() if marker.exists()), None)
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
            loader_version=installed.loader_version,
            minecraft_version=installed.minecraft_version,
            start_script=str(start_script) if start_script else None,
            start_script_name=start_script.name if start_script else None,
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
