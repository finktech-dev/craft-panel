"""Available Minecraft and loader versions, read from the official sources.

Only HTTPS endpoints published by Mojang, NeoForged and FabricMC are used.
Results are cached briefly; when the sources cannot be reached the service
raises a clear error instead of inventing a list.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from app.services.java_runtime_service import JavaRuntimeService, JavaRuntimeValidationError
from app.services.server_version_service import neoforge_to_minecraft, version_key

CatalogFlavor = Literal["vanilla", "neoforge", "fabric"]

MOJANG_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
NEOFORGE_METADATA_URL = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
NEOFORGE_MAVEN_URL = "https://maven.neoforged.net/releases/net/neoforged/neoforge"
FABRIC_GAME_URL = "https://meta.fabricmc.net/v2/versions/game"
FABRIC_LOADER_URL = "https://meta.fabricmc.net/v2/versions/loader/{minecraft_version}"
FABRIC_INSTALLER_URL = "https://meta.fabricmc.net/v2/versions/installer"
FABRIC_MAVEN_URL = "https://maven.fabricmc.net/net/fabricmc/fabric-installer"

_CACHE_SECONDS = 600.0
_FAILURE_CACHE_SECONDS = 30.0
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_SAFE_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}$")
_MAVEN_VERSION = re.compile(r"<version>\s*([^<\s]+)\s*</version>")


class VersionCatalogError(RuntimeError):
    status_code = 503


class VersionCatalogValidationError(VersionCatalogError):
    status_code = 422


@dataclass(frozen=True)
class CatalogEntry:
    minecraft_version: str
    stable: bool
    java_major: int | None
    loader_version: str | None = None


@dataclass(frozen=True)
class VersionCatalog:
    flavor: CatalogFlavor
    include_snapshots: bool
    versions: list[CatalogEntry]
    source: str
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def latest(self) -> str | None:
        return next((entry.minecraft_version for entry in self.versions if entry.stable), None)


def is_safe_version(value: str) -> bool:
    """Version strings end up in URLs and file names; keep them boring."""
    return bool(_SAFE_VERSION.match(value)) and ".." not in value


def _java_major(minecraft_version: str) -> int | None:
    try:
        return JavaRuntimeService.required_major(minecraft_version)
    except JavaRuntimeValidationError:
        return None


# Parsers (pure, tested with recorded payloads) -------------------------------

def parse_mojang_manifest(payload: Any, include_snapshots: bool = False) -> list[CatalogEntry]:
    """Releases (and optionally snapshots) from Mojang's manifest, newest first."""
    versions = payload.get("versions") if isinstance(payload, dict) else None
    if not isinstance(versions, list):
        raise VersionCatalogError("La lista oficial de versiones de Minecraft llegó con un formato inesperado.")
    allowed = {"release", "snapshot"} if include_snapshots else {"release"}
    rows: list[tuple[str, CatalogEntry]] = []
    for item in versions:
        if not isinstance(item, dict):
            continue
        identifier, kind = item.get("id"), item.get("type")
        if not isinstance(identifier, str) or kind not in allowed or not is_safe_version(identifier):
            continue
        released = item.get("releaseTime") if isinstance(item.get("releaseTime"), str) else ""
        rows.append((released, CatalogEntry(identifier, kind == "release", _java_major(identifier))))
    rows.sort(key=lambda row: row[0], reverse=True)
    return [entry for _released, entry in rows]


def parse_fabric_game_versions(payload: Any, include_snapshots: bool = False) -> list[CatalogEntry]:
    """Game versions Fabric supports; Fabric already lists them newest first."""
    if not isinstance(payload, list):
        raise VersionCatalogError("La lista de versiones de Fabric llegó con un formato inesperado.")
    entries: list[CatalogEntry] = []
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("version"), str):
            continue
        identifier, stable = item["version"], item.get("stable") is True
        if (stable or include_snapshots) and is_safe_version(identifier):
            entries.append(CatalogEntry(identifier, stable, _java_major(identifier)))
    return entries


def parse_fabric_loader_versions(payload: Any) -> str | None:
    """Latest stable Fabric Loader for one game version (the list is newest first)."""
    if not isinstance(payload, list):
        raise VersionCatalogError("La lista de Fabric Loader llegó con un formato inesperado.")
    for item in payload:
        loader = item.get("loader") if isinstance(item, dict) else None
        if isinstance(loader, dict) and loader.get("stable") is True and isinstance(loader.get("version"), str):
            if is_safe_version(loader["version"]):
                return loader["version"]
    return None


def parse_fabric_installer_versions(payload: Any) -> str | None:
    if not isinstance(payload, list):
        raise VersionCatalogError("La lista del instalador de Fabric llegó con un formato inesperado.")
    for item in payload:
        if isinstance(item, dict) and item.get("stable") is True and isinstance(item.get("version"), str):
            if is_safe_version(item["version"]):
                return item["version"]
    return None


def parse_neoforge_metadata(xml_text: str) -> dict[str, dict[str, list[str]]]:
    """Group NeoForge builds by Minecraft version: ``{mc: {"stable": [...], "beta": [...]}}``.

    Builds with no suffix are stable, ``-beta`` builds are kept apart, and
    alpha/snapshot builds (made for Minecraft snapshots) are ignored. Each list
    is sorted newest first.
    """
    if "<metadata" not in xml_text:
        raise VersionCatalogError("La lista de versiones de NeoForge llegó con un formato inesperado.")
    grouped: dict[str, dict[str, list[str]]] = {}
    for build in _MAVEN_VERSION.findall(xml_text):
        if not is_safe_version(build) or "alpha" in build or "+snapshot" in build:
            continue
        minecraft = neoforge_to_minecraft(build)
        if minecraft is None:
            continue
        channel = "stable" if "-" not in build and "+" not in build else "beta" if build.endswith("-beta") else None
        if channel is None:
            continue
        grouped.setdefault(minecraft, {"stable": [], "beta": []})[channel].append(build)
    for channels in grouped.values():
        for builds in channels.values():
            builds.sort(key=version_key, reverse=True)
    return grouped


def neoforge_catalog_entries(
    grouped: dict[str, dict[str, list[str]]], include_snapshots: bool = False
) -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    for minecraft, channels in grouped.items():
        if channels["stable"]:
            entries.append(CatalogEntry(minecraft, True, _java_major(minecraft), channels["stable"][0]))
        elif include_snapshots and channels["beta"]:
            entries.append(CatalogEntry(minecraft, False, _java_major(minecraft), channels["beta"][0]))
    entries.sort(key=lambda entry: version_key(entry.minecraft_version), reverse=True)
    return entries


# Service ---------------------------------------------------------------------

class VersionCatalogService:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._cache: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def list_versions(self, flavor: CatalogFlavor, include_snapshots: bool = False) -> VersionCatalog:
        if flavor == "vanilla":
            payload = await self._get_json(MOJANG_MANIFEST_URL, "Mojang")
            entries = parse_mojang_manifest(payload, include_snapshots)
            source = MOJANG_MANIFEST_URL
        elif flavor == "fabric":
            payload = await self._get_json(FABRIC_GAME_URL, "Fabric")
            entries = parse_fabric_game_versions(payload, include_snapshots)
            source = FABRIC_GAME_URL
        elif flavor == "neoforge":
            grouped = parse_neoforge_metadata(await self._get_text(NEOFORGE_METADATA_URL, "NeoForge"))
            entries = neoforge_catalog_entries(grouped, include_snapshots)
            source = NEOFORGE_METADATA_URL
        else:
            raise VersionCatalogValidationError("Tipo de servidor no soportado.")
        if not entries:
            raise VersionCatalogError("La fuente oficial no devolvió versiones disponibles.")
        return VersionCatalog(flavor=flavor, include_snapshots=include_snapshots, versions=entries, source=source)

    async def latest_neoforge_build(self, minecraft_version: str) -> str:
        grouped = parse_neoforge_metadata(await self._get_text(NEOFORGE_METADATA_URL, "NeoForge"))
        channels = grouped.get(minecraft_version)
        if not channels or not (channels["stable"] or channels["beta"]):
            raise VersionCatalogValidationError(f"NeoForge no tiene versiones para Minecraft {minecraft_version}.")
        if not channels["stable"]:
            raise VersionCatalogValidationError(
                f"NeoForge todavía no tiene una versión estable para Minecraft {minecraft_version}. Elegí otra versión."
            )
        return channels["stable"][0]

    async def latest_fabric_loader(self, minecraft_version: str) -> str:
        if not is_safe_version(minecraft_version):
            raise VersionCatalogValidationError("La versión de Minecraft no es válida.")
        payload = await self._get_json(FABRIC_LOADER_URL.format(minecraft_version=minecraft_version), "Fabric")
        loader = parse_fabric_loader_versions(payload)
        if loader is None:
            raise VersionCatalogValidationError(f"Fabric no tiene una versión estable para Minecraft {minecraft_version}.")
        return loader

    async def latest_fabric_installer(self) -> str:
        installer = parse_fabric_installer_versions(await self._get_json(FABRIC_INSTALLER_URL, "Fabric"))
        if installer is None:
            raise VersionCatalogError("Fabric no ofrece un instalador estable en este momento.")
        return installer

    def clear(self) -> None:
        self._cache.clear()

    def _cached(self, url: str) -> Any:
        """Fresh cached value, re-raising a recent failure so offline hosts fail fast."""
        cached = self._cache.get(url)
        if cached is None or cached[0] <= time.monotonic():
            return None
        if isinstance(cached[1], VersionCatalogError):
            raise VersionCatalogError(str(cached[1]))
        return cached[1]

    async def _get_json(self, url: str, source_name: str) -> Any:
        return await self._fetch(url, source_name, as_json=True)

    async def _get_text(self, url: str, source_name: str) -> str:
        return await self._fetch(url, source_name, as_json=False)

    async def _fetch(self, url: str, source_name: str, *, as_json: bool) -> Any:
        if not url.startswith("https://"):
            raise VersionCatalogError("Solo se consultan fuentes oficiales por HTTPS.")
        cached = self._cached(url)
        if cached is not None:
            return cached
        lock = self._locks.setdefault(url, asyncio.Lock())
        async with lock:
            cached = self._cached(url)
            if cached is not None:
                return cached
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, transport=self._transport) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    if not str(response.url).startswith("https://"):
                        raise VersionCatalogError("La fuente oficial redirigió a una dirección insegura.")
                    value = response.json() if as_json else response.text
            except (httpx.HTTPError, ValueError) as error:
                failure = VersionCatalogError(
                    f"No se pudo consultar la lista oficial de {source_name}. Revisá la conexión a internet e intentá de nuevo."
                )
                self._cache[url] = (time.monotonic() + _FAILURE_CACHE_SECONDS, failure)
                raise failure from error
            self._cache[url] = (time.monotonic() + _CACHE_SECONDS, value)
            return value


version_catalog_service = VersionCatalogService()
