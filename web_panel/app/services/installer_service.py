"""Safe, observable installation of a server runtime chosen by the host."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import aiofiles
import httpx

from app.core.config import Settings, settings
from app.services.runtime_discovery import RuntimeDiscoveryService
from app.services.runtime_guard import ServerActiveError, require_server_stopped
from app.services.server_process import MinecraftServerManager, server_manager
from app.services.server_version_service import neoforge_to_minecraft
from app.services.version_catalog_service import (
    FABRIC_MAVEN_URL,
    MOJANG_MANIFEST_URL,
    NEOFORGE_MAVEN_URL,
    VersionCatalogError,
    VersionCatalogService,
    VersionCatalogValidationError,
    is_safe_version,
    version_catalog_service,
)
from app.websocket.manager import ConnectionManager, connection_manager

_DOWNLOAD_CHUNK_SIZE = 64 * 1024
_MOJANG_MANIFEST = MOJANG_MANIFEST_URL
_MINECRAFT_VERSION = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
_SHA1 = re.compile(r"^[0-9a-fA-F]{40}$")


class InstallerServiceError(RuntimeError):
    status_code = 502


class InstallerConflictError(InstallerServiceError):
    status_code = 409


class InstallerValidationError(InstallerServiceError):
    status_code = 422


class InstallerService:
    def __init__(
        self,
        configured_settings: Settings = settings,
        manager: ConnectionManager = connection_manager,
        server: MinecraftServerManager = server_manager,
        catalog: VersionCatalogService = version_catalog_service,
        discovery: RuntimeDiscoveryService | None = None,
    ) -> None:
        self._settings = configured_settings
        self._connections = manager
        self._server = server
        self._catalog = catalog
        self._discovery = discovery or RuntimeDiscoveryService(configured_settings)
        self._lock = asyncio.Lock()

    @staticmethod
    def neoforge_installer_url(build: str) -> str:
        if not is_safe_version(build):
            raise InstallerValidationError("La versión de NeoForge no es válida.")
        return f"{NEOFORGE_MAVEN_URL}/{build}/neoforge-{build}-installer.jar"

    async def install_neoforge(self, minecraft_version: str | None = None) -> None:
        """Compatibility entrypoint for the former NeoForge-only API."""
        await self.install_server(
            "neoforge", minecraft_version or self._settings.minecraft_version or "", accept_eula=True
        )

    async def install_server(
        self,
        flavor: Literal["vanilla", "neoforge", "fabric"],
        minecraft_version: str,
        *,
        accept_eula: bool,
    ) -> None:
        """Install only missing runtime files; never replace worlds or settings."""
        if not accept_eula:
            raise InstallerValidationError("Accept the Minecraft EULA before installing a server.")
        async with self._lock:
            try:
                require_server_stopped(self._server, "install or replace a server runtime")
            except ServerActiveError as error:
                raise InstallerConflictError(str(error)) from error
            if not _MINECRAFT_VERSION.match(minecraft_version or ""):
                raise InstallerValidationError("Elegí una versión de Minecraft válida, por ejemplo 1.21.1.")
            self._assert_runtime_is_not_already_installed()
            if flavor in {"neoforge", "fabric"}:
                await self._assert_java_is_compatible(minecraft_version)
            assert self._settings.server_directory is not None
            await asyncio.to_thread(self._settings.server_directory.mkdir, parents=True, exist_ok=True)
            await self._publish(f"Preparing Minecraft {minecraft_version} ({flavor})…")
            if flavor == "vanilla":
                await self._install_vanilla(minecraft_version)
            elif flavor == "fabric":
                await self._install_fabric(minecraft_version)
            else:
                await self._install_neoforge(minecraft_version)
            await asyncio.to_thread(self._write_safe_server_files, flavor)
            await self._publish("Server runtime installed. Your worlds and existing settings were not replaced.")

    def _assert_runtime_is_not_already_installed(self) -> None:
        assert self._settings.server_directory is not None
        root = self._settings.server_directory
        runtime_markers = (
            root / "server.jar",
            root / "fabric-server-launch.jar",
            root / "paper.jar",
            root / "libraries" / "net" / "neoforged" / "neoforge",
            root / "libraries" / "net" / "minecraftforge" / "forge",
        )
        if any(marker.exists() for marker in runtime_markers) or any(root.glob("*.jar")):
            raise InstallerConflictError(
                "A server runtime already exists here. Choose Import existing server instead; the wizard will not overwrite it."
            )

    async def _assert_java_is_compatible(self, minecraft_version: str) -> None:
        """Loader installers run Java, so check it before downloading anything."""
        status = await asyncio.to_thread(self._discovery.java_status, minecraft_version)
        if status.state != "available":
            raise InstallerValidationError(status.message)

    async def _install_vanilla(self, minecraft_version: str) -> None:
        await self._publish("Finding the official Vanilla server download…")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0), follow_redirects=True) as client:
                manifest_response = await client.get(_MOJANG_MANIFEST)
                manifest_response.raise_for_status()
                manifest = manifest_response.json()
                versions = manifest.get("versions", []) if isinstance(manifest, dict) else []
                selected = next((item for item in versions if item.get("id") == minecraft_version), None)
                if not isinstance(selected, dict) or not isinstance(selected.get("url"), str):
                    raise InstallerValidationError(f"Minecraft {minecraft_version} was not found in Mojang's official manifest.")
                if not selected["url"].startswith("https://"):
                    raise InstallerServiceError("The official manifest pointed to an insecure address.")
                details_response = await client.get(selected["url"])
                details_response.raise_for_status()
                expected_details_sha1 = selected.get("sha1")
                if isinstance(expected_details_sha1, str) and _SHA1.match(expected_details_sha1):
                    if hashlib.sha1(details_response.content).hexdigest() != expected_details_sha1.casefold():
                        raise InstallerServiceError("The official version details checksum did not match.")
                details = details_response.json()
                server = details.get("downloads", {}).get("server", {}) if isinstance(details, dict) else {}
                url, checksum = server.get("url"), server.get("sha1")
                if not isinstance(url, str) or not isinstance(checksum, str):
                    raise InstallerServiceError("The official manifest did not provide a server download.")
                assert self._settings.server_directory is not None
                await self._download(client, url, self._settings.server_directory / "server.jar", checksum)
        except InstallerServiceError:
            raise
        except (httpx.HTTPError, ValueError) as error:
            raise InstallerServiceError("The official server manifest could not be reached. Check the connection and try again.") from error

    async def _resolve_neoforge_build(self, minecraft_version: str) -> str:
        """Configured override when it targets this version, else the latest stable build."""
        override = (self._settings.neoforge_version or "").strip()
        if override and neoforge_to_minecraft(override) == minecraft_version:
            return override
        try:
            return await self._catalog.latest_neoforge_build(minecraft_version)
        except VersionCatalogValidationError as error:
            raise InstallerValidationError(str(error)) from error
        except VersionCatalogError as error:
            raise InstallerServiceError(str(error)) from error

    async def _install_neoforge(self, minecraft_version: str) -> None:
        await self._publish("Finding the official NeoForge build…")
        build = await self._resolve_neoforge_build(minecraft_version)
        url = self.neoforge_installer_url(build)
        await self._publish(f"Downloading the official NeoForge {build} installer…")
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0), follow_redirects=True) as client:
            checksum = await self._published_sha1(client, url)
            await self._download(client, url, self._settings.neoforge_installer_path, checksum)
        assert self._settings.server_directory is not None
        await self._publish("Installing NeoForge…")
        await self._run_java(
            "-jar", str(self._settings.neoforge_installer_path), "--install-server", str(self._settings.server_directory)
        )

    async def _install_fabric(self, minecraft_version: str) -> None:
        await self._publish("Finding the Fabric installer…")
        try:
            loader = await self._catalog.latest_fabric_loader(minecraft_version)
            version = await self._catalog.latest_fabric_installer()
        except VersionCatalogValidationError as error:
            raise InstallerValidationError(str(error)) from error
        except VersionCatalogError as error:
            raise InstallerServiceError(
                "The Fabric installer manifest could not be reached. Check the connection and try again."
            ) from error
        url = f"{FABRIC_MAVEN_URL}/{version}/fabric-installer-{version}.jar"
        assert self._settings.tools_directory is not None
        installer = self._settings.tools_directory / f"fabric-installer-{version}.jar"
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0), follow_redirects=True) as client:
            checksum = await self._published_sha1(client, url)
            await self._download(client, url, installer, checksum)
        assert self._settings.server_directory is not None
        await self._publish(f"Installing Fabric Loader {loader}…")
        await self._run_java(
            "-jar", str(installer), "server", "-dir", str(self._settings.server_directory),
            "-mcversion", minecraft_version, "-loader", loader, "-downloadMinecraft",
        )

    async def _run_java(self, *args: str) -> None:
        java = self._settings.local_java_executable_path
        command = str(java) if java.is_file() else "java"
        try:
            process = await asyncio.create_subprocess_exec(
                command, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )
        except OSError as error:
            raise InstallerValidationError(
                "No se encontró Java compatible. Instalalo en el sistema o descomprimilo en tools/java, y elegí una versión de Minecraft compatible."
            ) from error
        assert process.stdout is not None
        async for raw_line in process.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if line:
                await self._publish(line)
        if await process.wait() != 0:
            raise InstallerServiceError("The installer stopped with an error. No world or existing configuration was replaced.")

    @staticmethod
    async def _published_sha1(client: httpx.AsyncClient, url: str) -> str:
        """Maven repositories publish ``<artifact>.sha1``; refuse artifacts without one."""
        try:
            response = await client.get(f"{url}.sha1")
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise InstallerServiceError("No se pudo obtener la suma de verificación oficial del instalador.") from error
        text = response.text.strip()
        checksum = text.split()[0] if text else ""
        if not _SHA1.match(checksum):
            raise InstallerServiceError("La suma de verificación oficial del instalador no es válida.")
        return checksum

    async def _download(self, client: httpx.AsyncClient, url: str, destination: Path, sha1: str | None = None) -> None:
        if not url.startswith("https://"):
            raise InstallerServiceError("Only official HTTPS downloads are allowed.")
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.download")
        digest = hashlib.sha1()
        try:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                async with aiofiles.open(temporary, "wb") as file:
                    async for chunk in response.aiter_bytes(_DOWNLOAD_CHUNK_SIZE):
                        digest.update(chunk)
                        await file.write(chunk)
            if sha1 and digest.hexdigest().casefold() != sha1.casefold():
                raise InstallerServiceError("The official download checksum did not match; it was discarded.")
            await asyncio.to_thread(os.replace, temporary, destination)
        except (httpx.HTTPError, OSError) as error:
            raise InstallerServiceError("The official server download failed. Check the connection and try again.") from error
        finally:
            if temporary.exists():
                await asyncio.to_thread(temporary.unlink)

    def _write_safe_server_files(self, flavor: str) -> None:
        assert self._settings.server_directory is not None
        root = self._settings.server_directory
        # EULA is only written after the explicit checkbox in the wizard.
        (root / "eula.txt").write_text("eula=true\n", encoding="utf-8")
        args = root / "user_jvm_args.txt"
        if not args.exists():
            args.write_text("-Xms1G\n-Xmx5G\n", encoding="utf-8")
        # NeoForge generates its own launch scripts; preserve them exactly.
        if flavor == "neoforge":
            return
        jar = "server.jar" if flavor == "vanilla" else "fabric-server-launch.jar"
        bat = f"@echo off\r\njava @user_jvm_args.txt -jar {jar} %*\r\n"
        shell = f"#!/usr/bin/env sh\nexec java @user_jvm_args.txt -jar {jar} \"$@\"\n"
        (root / "run.bat").write_text(bat, encoding="utf-8")
        shell_path = root / "run.sh"
        shell_path.write_text(shell, encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(shell_path, 0o700)

    async def _publish(self, message: str) -> None:
        await self._connections.broadcast_json({
            "type": "log",
            "line": {"timestamp": datetime.now(UTC).isoformat(), "stream": "installer", "message": f"[Installer] {message}"},
        })


installer_service = InstallerService()
