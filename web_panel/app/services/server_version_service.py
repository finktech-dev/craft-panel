"""Offline detection of the installed server runtime and its versions.

Everything here reads local files only: it never opens the network, starts
Java, or changes the server directory. Results are cached by the
modification times of the directories that installers touch, so callers can
ask on every request without rescanning the libraries tree.
"""

from __future__ import annotations

import contextlib
import json
import re
import threading
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from app.core.config import Settings, settings

Loader = Literal["neoforge", "forge", "fabric", "quilt", "paper", "vanilla", "unknown"]

LOADER_NAMES: dict[str, str] = {
    "neoforge": "NeoForge",
    "forge": "Forge",
    "fabric": "Fabric",
    "quilt": "Quilt",
    "paper": "Paper",
}

_NEOFORGE_LIBS = ("libraries", "net", "neoforged", "neoforge")
_FORGE_LIBS = ("libraries", "net", "minecraftforge", "forge")
_FABRIC_LOADER_LIBS = ("libraries", "net", "fabricmc", "fabric-loader")
_FABRIC_INTERMEDIARY_LIBS = ("libraries", "net", "fabricmc", "intermediary")
_QUILT_LOADER_LIBS = ("libraries", "org", "quiltmc", "quilt-loader")
_SCRIPT_NAMES = ("run.bat", "run.sh", "user_jvm_args.txt", "start.bat", "start.sh")
_SCRIPT_LIBRARY = re.compile(
    r"libraries[/\\]net[/\\](neoforged[/\\]neoforge|minecraftforge[/\\]forge)[/\\]([^/\\\s\"']+)[/\\]"
)
_RELEASE_ID = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
_FABRIC_LAUNCHER = re.compile(r"^fabric-server-mc\.(?P<mc>[^-]+)-loader\.(?P<loader>[^-]+)-launcher\..+\.jar$")
_FORGE_ROOT_JAR = re.compile(r"^forge-(?P<mc>1\.\d+(?:\.\d+)?)-(?P<forge>[\d.]+)(?:-universal|-server)?\.jar$")
_VANILLA_ROOT_JAR = re.compile(r"^minecraft_server\.(?P<mc>\d+\.\d+(?:\.\d+)?)\.jar$")
_MAX_METADATA_BYTES = 256 * 1024


@dataclass(frozen=True)
class ServerVersionInfo:
    """What is installed, as far as the files on disk can tell."""

    loader: Loader = "unknown"
    loader_version: str | None = None
    minecraft_version: str | None = None
    source: str = "none"

    @property
    def is_installed(self) -> bool:
        return self.loader != "unknown" or self.minecraft_version is not None

    @property
    def label(self) -> str | None:
        """Plain display text such as "Minecraft 1.21.1 con NeoForge 21.1.250"."""
        minecraft = f"Minecraft {self.minecraft_version}" if self.minecraft_version else "Minecraft"
        loader_name = LOADER_NAMES.get(self.loader)
        if loader_name:
            loader_text = f"{loader_name} {self.loader_version}" if self.loader_version else loader_name
            return f"{minecraft} con {loader_text}"
        if self.minecraft_version:
            return minecraft
        return None


def version_key(version: str) -> tuple[int, ...]:
    """Numeric sort key that ignores pre-release suffixes ("21.0.10-beta" -> (21, 0, 10))."""
    numeric = re.match(r"^\d+(?:\.\d+)*", version.strip())
    if not numeric:
        return ()
    return tuple(int(part) for part in numeric.group(0).split("."))


def neoforge_to_minecraft(neoforge_version: str) -> str | None:
    """Map a NeoForge build to the Minecraft release it targets.

    Up to Minecraft 1.21.11 NeoForge used ``<mc minor>.<mc patch>.<build>``
    (``21.1.250`` -> ``1.21.1``, ``21.0.x`` -> ``1.21``). Since Minecraft
    moved to year-based numbers, NeoForge uses ``<year>.<drop>.<hotfix>.<build>``
    (``26.1.0.12`` -> ``26.1``, ``26.1.2.120`` -> ``26.1.2``).
    """
    parts = version_key(neoforge_version)
    if len(parts) == 4:
        year, drop, hotfix, _build = parts
        return f"{year}.{drop}" if hotfix == 0 else f"{year}.{drop}.{hotfix}"
    if len(parts) == 3:
        minor, patch, _build = parts
        # The three-part scheme only ever covered Minecraft 1.20.x and 1.21.x.
        if minor not in (20, 21):
            return None
        return f"1.{minor}" if patch == 0 else f"1.{minor}.{patch}"
    return None


# Data pack ``pack_format`` by the first Minecraft release that introduced it.
_DATA_PACK_FORMATS: tuple[tuple[tuple[int, ...], int], ...] = (
    ((1, 13), 4),
    ((1, 15), 5),
    ((1, 16, 2), 6),
    ((1, 17), 7),
    ((1, 18), 8),
    ((1, 18, 2), 9),
    ((1, 19), 10),
    ((1, 19, 4), 12),
    ((1, 20), 15),
    ((1, 20, 2), 18),
    ((1, 20, 3), 26),
    ((1, 20, 5), 41),
    ((1, 21), 48),
    ((1, 21, 2), 57),
    ((1, 21, 4), 61),
    ((1, 21, 5), 71),
    ((1, 21, 6), 80),
    ((1, 21, 7), 81),
    ((1, 21, 9), 88),
)
# From 1.21.9 on, packs declare ``min_format``/``max_format`` instead of one number.
_RANGED_PACK_FORMAT_SINCE = (1, 21, 9)
_OPEN_MAX_FORMAT = 2_147_483_647


def data_pack_metadata(minecraft_version: str | None) -> dict[str, int]:
    """``pack`` format fields for a data pack meant to load on ``minecraft_version``.

    Known older releases get their exact ``pack_format``. Newer or unknown
    releases get an open-ended ``min_format``/``max_format`` range (plus
    ``pack_format`` for older readers), so a release newer than this table
    still loads the pack instead of rejecting it.
    """
    key = version_key(minecraft_version) if minecraft_version else ()
    if key and key < _RANGED_PACK_FORMAT_SINCE:
        selected = None
        for since, pack_format in _DATA_PACK_FORMATS:
            if key >= since:
                selected = pack_format
        if selected is not None:
            return {"pack_format": selected}
    newest = _DATA_PACK_FORMATS[-1][1]
    return {"pack_format": newest, "min_format": newest, "max_format": _OPEN_MAX_FORMAT}


class ServerVersionService:
    """Detects loader, loader version and Minecraft version from local files."""

    def __init__(self, configured_settings: Settings = settings) -> None:
        self._settings = configured_settings
        self._cache: tuple[tuple[object, ...], ServerVersionInfo] | None = None
        self._lock = threading.Lock()

    def detect(self) -> ServerVersionInfo:
        """Return the installed runtime, with optional config overrides applied."""
        root = self._settings.server_directory
        if root is None or not root.is_dir():
            return self._apply_overrides(ServerVersionInfo())
        signature = self._signature(root)
        with self._lock:
            if self._cache is not None and self._cache[0] == signature:
                return self._apply_overrides(self._cache[1])
        detected = self._detect(root)
        with self._lock:
            self._cache = (signature, detected)
        return self._apply_overrides(detected)

    def _apply_overrides(self, info: ServerVersionInfo) -> ServerVersionInfo:
        minecraft_override = (self._settings.minecraft_version or "").strip() or None
        neoforge_override = (self._settings.neoforge_version or "").strip() or None
        if minecraft_override:
            info = replace(info, minecraft_version=minecraft_override)
        if neoforge_override and info.loader == "neoforge":
            info = replace(info, loader_version=neoforge_override)
        return info

    @staticmethod
    def _signature(root: Path) -> tuple[object, ...]:
        watched = (
            root,
            root.joinpath(*_NEOFORGE_LIBS),
            root.joinpath(*_FORGE_LIBS),
            root.joinpath(*_FABRIC_LOADER_LIBS),
            root.joinpath(*_FABRIC_INTERMEDIARY_LIBS),
            root.joinpath(*_QUILT_LOADER_LIBS),
            root / "versions",
            root / ".fabric",
            root / "server.jar",
            root / "run.bat",
            root / "run.sh",
        )
        stamps: list[object] = [str(root)]
        for path in watched:
            try:
                stamps.append(path.stat().st_mtime_ns)
            except OSError:
                stamps.append(None)
        return tuple(stamps)

    def _detect(self, root: Path) -> ServerVersionInfo:
        script_refs = self._script_library_references(root)
        for detector in (self._detect_neoforge, self._detect_forge):
            found = detector(root, script_refs)
            if found is not None:
                return found
        for detector in (self._detect_fabric, self._detect_quilt):
            found = detector(root)
            if found is not None:
                return found
        vanilla_version, vanilla_source = self._detect_vanilla_version(root)
        if (root / "paper.jar").is_file():
            return ServerVersionInfo(
                loader="paper",
                minecraft_version=self._jar_version(root / "paper.jar") or vanilla_version,
                source="paper.jar",
            )
        if vanilla_version:
            return ServerVersionInfo(loader="vanilla", minecraft_version=vanilla_version, source=vanilla_source)
        if (root / "server.jar").is_file():
            return ServerVersionInfo(loader="vanilla", source="server.jar")
        return ServerVersionInfo()

    # NeoForge / Forge ---------------------------------------------------

    def _detect_neoforge(self, root: Path, script_refs: dict[str, str]) -> ServerVersionInfo | None:
        versions = self._child_directories(root.joinpath(*_NEOFORGE_LIBS))
        referenced = script_refs.get("neoforge")
        if referenced and (not versions or referenced in versions):
            chosen, source = referenced, "start-script"
        elif versions:
            chosen, source = max(versions, key=version_key), "libraries"
        elif root.joinpath(*_NEOFORGE_LIBS).is_dir():
            return ServerVersionInfo(
                loader="neoforge", minecraft_version=self._detect_vanilla_version(root)[0], source="libraries"
            )
        else:
            return None
        return ServerVersionInfo(
            loader="neoforge",
            loader_version=chosen,
            minecraft_version=neoforge_to_minecraft(chosen) or self._detect_vanilla_version(root)[0],
            source=source,
        )

    def _detect_forge(self, root: Path, script_refs: dict[str, str]) -> ServerVersionInfo | None:
        versions = self._child_directories(root.joinpath(*_FORGE_LIBS))
        referenced = script_refs.get("forge")
        if referenced and (not versions or referenced in versions):
            chosen, source = referenced, "start-script"
        elif versions:
            chosen, source = max(versions, key=lambda item: version_key(item.replace("-", "."))), "libraries"
        elif root.joinpath(*_FORGE_LIBS).is_dir():
            return ServerVersionInfo(
                loader="forge", minecraft_version=self._detect_vanilla_version(root)[0], source="libraries"
            )
        else:
            legacy = self._legacy_forge_jar(root)
            if legacy is None:
                return None
            minecraft, forge = legacy
            return ServerVersionInfo(loader="forge", loader_version=forge, minecraft_version=minecraft, source="forge-jar")
        minecraft, _, forge = chosen.partition("-")
        return ServerVersionInfo(
            loader="forge",
            loader_version=forge or None,
            minecraft_version=minecraft if _RELEASE_ID.match(minecraft) else self._detect_vanilla_version(root)[0],
            source=source,
        )

    @staticmethod
    def _legacy_forge_jar(root: Path) -> tuple[str, str] | None:
        with contextlib.suppress(OSError):
            for entry in root.iterdir():
                match = _FORGE_ROOT_JAR.match(entry.name)
                if match and entry.is_file():
                    return match.group("mc"), match.group("forge")
        return None

    @staticmethod
    def _script_library_references(root: Path) -> dict[str, str]:
        references: dict[str, str] = {}
        for name in _SCRIPT_NAMES:
            path = root / name
            if not path.is_file():
                continue
            try:
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    content = handle.read(_MAX_METADATA_BYTES)
            except OSError:
                continue
            for match in _SCRIPT_LIBRARY.finditer(content):
                loader = "neoforge" if "neoforged" in match.group(1) else "forge"
                references.setdefault(loader, match.group(2))
        return references

    # Fabric / Quilt ----------------------------------------------------

    def _detect_fabric(self, root: Path) -> ServerVersionInfo | None:
        launcher = self._fabric_launcher_jar(root)
        if launcher is not None:
            match = _FABRIC_LAUNCHER.match(launcher.name)
            assert match is not None
            return ServerVersionInfo(
                loader="fabric",
                loader_version=match.group("loader"),
                minecraft_version=match.group("mc"),
                source="fabric-launcher",
            )
        loader_versions = self._child_directories(root.joinpath(*_FABRIC_LOADER_LIBS))
        has_marker = (
            bool(loader_versions)
            or (root / "fabric-server-launch.jar").is_file()
            or (root / "fabric-server-launcher.properties").is_file()
            or (root / ".fabric").is_dir()
        )
        if not has_marker:
            return None
        loader_version = max(loader_versions, key=version_key) if loader_versions else None
        intermediary = self._child_directories(root.joinpath(*_FABRIC_INTERMEDIARY_LIBS))
        remapped = self._fabric_remapped_versions(root)
        minecraft: str | None = None
        source = "fabric-files"
        if intermediary:
            minecraft, source = max(intermediary, key=version_key), "libraries"
        elif remapped:
            minecraft, remapped_loader = max(remapped, key=lambda item: version_key(item[0]))
            loader_version = loader_version or remapped_loader
            source = ".fabric"
        else:
            minecraft = self._detect_vanilla_version(root)[0]
        return ServerVersionInfo(loader="fabric", loader_version=loader_version, minecraft_version=minecraft, source=source)

    @staticmethod
    def _fabric_launcher_jar(root: Path) -> Path | None:
        with contextlib.suppress(OSError):
            for entry in sorted(root.iterdir()):
                if _FABRIC_LAUNCHER.match(entry.name) and entry.is_file():
                    return entry
        return None

    @staticmethod
    def _fabric_remapped_versions(root: Path) -> list[tuple[str, str | None]]:
        """``.fabric/remappedJars/minecraft-<mc>-<loader>/`` folders written by Fabric Loader."""
        found: list[tuple[str, str | None]] = []
        remapped = root / ".fabric" / "remappedJars"
        with contextlib.suppress(OSError):
            for entry in remapped.iterdir():
                match = re.match(r"^minecraft-(\d+\.\d+(?:\.\d+)?)(?:-(.+))?$", entry.name)
                if match and entry.is_dir():
                    found.append((match.group(1), match.group(2)))
        return found

    def _detect_quilt(self, root: Path) -> ServerVersionInfo | None:
        loader_versions = self._child_directories(root.joinpath(*_QUILT_LOADER_LIBS))
        if not loader_versions and not (root / "quilt-server-launch.jar").is_file():
            return None
        return ServerVersionInfo(
            loader="quilt",
            loader_version=max(loader_versions, key=version_key) if loader_versions else None,
            minecraft_version=self._detect_vanilla_version(root)[0],
            source="quilt-files",
        )

    # Vanilla -------------------------------------------------------------

    def _detect_vanilla_version(self, root: Path) -> tuple[str | None, str]:
        server_jar = root / "server.jar"
        if server_jar.is_file():
            version = self._jar_version(server_jar)
            if version:
                return version, "server.jar"
        extracted = [
            name for name in self._child_directories(root / "versions")
            if (root / "versions" / name / f"server-{name}.jar").is_file()
        ]
        if extracted:
            return max(extracted, key=version_key), "versions"
        with contextlib.suppress(OSError):
            for entry in root.iterdir():
                match = _VANILLA_ROOT_JAR.match(entry.name)
                if match and entry.is_file():
                    return match.group("mc"), "minecraft_server-jar"
        return None, "none"

    @staticmethod
    def _jar_version(jar: Path) -> str | None:
        """Read ``version.json`` or the bundler's ``META-INF/versions.list``."""
        try:
            with zipfile.ZipFile(jar) as archive:
                names = set(archive.namelist())
                if "version.json" in names and archive.getinfo("version.json").file_size <= _MAX_METADATA_BYTES:
                    with contextlib.suppress(ValueError, UnicodeDecodeError):
                        data = json.loads(archive.read("version.json").decode("utf-8"))
                        identifier = data.get("id") or data.get("name") if isinstance(data, dict) else None
                        if isinstance(identifier, str) and identifier.strip():
                            return identifier.strip()
                listing = "META-INF/versions.list"
                if listing in names and archive.getinfo(listing).file_size <= _MAX_METADATA_BYTES:
                    for line in archive.read(listing).decode("utf-8", errors="replace").splitlines():
                        columns = line.split("\t")
                        if len(columns) >= 2 and columns[1].strip():
                            return columns[1].strip()
        except (OSError, zipfile.BadZipFile, KeyError):
            return None
        return None

    @staticmethod
    def _child_directories(path: Path) -> list[str]:
        try:
            return [entry.name for entry in path.iterdir() if entry.is_dir()]
        except OSError:
            return []


server_version_service = ServerVersionService()
