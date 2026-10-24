"""Safe, observable installation of a server runtime chosen by the host."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import locale
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx

from app.core.config import Settings, settings
from app.core.net_safety import (
    FABRIC_HOSTS,
    MOJANG_HOSTS,
    NEOFORGE_HOSTS,
    UnsafeDownloadError,
    allowed_client,
    download_to_file,
)
from app.services.progress import ProgressCallback, StepPlan, download_message, report
from app.services.runtime_discovery import RuntimeDiscoveryService
from app.services.runtime_guard import ServerActiveError, require_server_stopped
from app.services.protected_paths import ProtectedPathError, require_not_protected
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
_INSTALLER_HOSTS = MOJANG_HOSTS | FABRIC_HOSTS | NEOFORGE_HOSTS
_MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024

# Steps announced through the ``progress`` callback. Vanilla has no installer
# program to run, so its ``install`` step is reported as skipped.
INSTALL_SERVER_STEPS: StepPlan = (
    ("prepare", "Revisando la carpeta del servidor"),
    ("download", "Descargando el servidor oficial"),
    ("install", "Instalando"),
    ("finish", "Dejando todo listo"),
)


def _decode_process_line(raw_line: bytes) -> str:
    """Decode installer output that may not be UTF-8.

    On Windows, Java writes redirected output in the ANSI code page (for
    example cp1252), so paths such as a user folder with accents are not UTF-8.
    """
    try:
        return raw_line.decode("utf-8")
    except UnicodeDecodeError:
        return raw_line.decode(locale.getpreferredencoding(False) or "utf-8", errors="replace")


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
        self._progress: ProgressCallback | None = None
        self._current_step = "prepare"

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
        progress: ProgressCallback | None = None,
    ) -> None:
        """Install only missing runtime files; never replace worlds or settings.

        ``progress`` receives the steps in :data:`INSTALL_SERVER_STEPS`.
        """
        if not accept_eula:
            raise InstallerValidationError("Accept the Minecraft EULA before installing a server.")
        async with self._lock:
            # The lock serializes installs, so per-run progress can live on the instance.
            self._progress = progress
            try:
                await self._install_locked(flavor, minecraft_version)
            finally:
                self._progress = None
                self._current_step = "prepare"

    def preflight(self, minecraft_version: str, *, accept_eula: bool) -> None:
        """Cheap checks that let a request fail right away instead of inside a job."""
        if not accept_eula:
            raise InstallerValidationError("Accept the Minecraft EULA before installing a server.")
        if self._lock.locked():
            raise InstallerConflictError("Ya hay una instalación en curso. Esperá a que termine.")
        try:
            require_server_stopped(self._server, "install or replace a server runtime")
        except ServerActiveError as error:
            raise InstallerConflictError(str(error)) from error
        if not _MINECRAFT_VERSION.match(minecraft_version or ""):
            raise InstallerValidationError("Elegí una versión de Minecraft válida, por ejemplo 1.21.1.")
        self._assert_runtime_is_not_already_installed()
        self._assert_targets_not_protected()

    def _assert_targets_not_protected(self) -> None:
        """The installer writes these files and folders; refuse up front if the user protected any."""
        assert self._settings.server_directory is not None
        root = self._settings.server_directory
        targets = [root / name for name in ("eula.txt", "user_jvm_args.txt", "run.bat", "run.sh", "server.jar", "libraries", "versions")]
        try:
            require_not_protected(*targets, configured=self._settings)
        except ProtectedPathError as error:
            raise InstallerConflictError(str(error)) from error

    async def _install_locked(self, flavor: str, minecraft_version: str) -> None:
        self._step("prepare", "Revisando la carpeta del servidor.")
        try:
            require_server_stopped(self._server, "install or replace a server runtime")
        except ServerActiveError as error:
            raise InstallerConflictError(str(error)) from error
        if not _MINECRAFT_VERSION.match(minecraft_version or ""):
            raise InstallerValidationError("Elegí una versión de Minecraft válida, por ejemplo 1.21.1.")
        self._assert_runtime_is_not_already_installed()
        self._assert_targets_not_protected()
        if flavor in {"neoforge", "fabric"}:
            await self._assert_java_is_compatible(minecraft_version)
        assert self._settings.server_directory is not None
        await asyncio.to_thread(self._settings.server_directory.mkdir, parents=True, exist_ok=True)
        await self._publish(f"Preparando Minecraft {minecraft_version} ({flavor}).")
        if flavor == "vanilla":
            await self._install_vanilla(minecraft_version)
        elif flavor == "fabric":
            await self._install_fabric(minecraft_version)
        else:
            await self._install_neoforge(minecraft_version)
        self._step("finish", "Dejando listos los archivos de inicio.")
        await asyncio.to_thread(self._write_safe_server_files, flavor)
        await self._publish("Servidor instalado. No se reemplazaron mundos ni ajustes existentes.")

    def _step(self, key: str, message: str | None = None) -> None:
        self._current_step = key
        report(self._progress, key, message)

    def _download_progress(self, done: int, total: int | None) -> None:
        message, percent = download_message(done, total)
        report(self._progress, "download", message, percent)

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
        self._step("download")
        await self._publish("Buscando la descarga oficial del servidor de Minecraft.")
        try:
            async with allowed_client(_INSTALLER_HOSTS, timeout=60.0) as client:
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
        self._step("download")
        await self._publish("Buscando la versión oficial de NeoForge.")
        build = await self._resolve_neoforge_build(minecraft_version)
        url = self.neoforge_installer_url(build)
        await self._publish(f"Descargando el instalador oficial de NeoForge {build}.")
        async with allowed_client(_INSTALLER_HOSTS, timeout=120.0) as client:
            checksum = await self._published_sha1(client, url)
            await self._download(client, url, self._settings.neoforge_installer_path, checksum)
        assert self._settings.server_directory is not None
        self._step("install")
        await self._publish("Instalando NeoForge. Puede tardar varios minutos.")
        await self._run_java(
            "-jar", str(self._settings.neoforge_installer_path), "--install-server", str(self._settings.server_directory)
        )

    async def _install_fabric(self, minecraft_version: str) -> None:
        self._step("download")
        await self._publish("Buscando el instalador de Fabric.")
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
        async with allowed_client(_INSTALLER_HOSTS, timeout=120.0) as client:
            checksum = await self._published_sha1(client, url)
            await self._download(client, url, installer, checksum)
        assert self._settings.server_directory is not None
        self._step("install")
        await self._publish(f"Instalando Fabric Loader {loader}. Puede tardar unos minutos.")
        await self._run_java(
            "-jar", str(installer), "server", "-dir", str(self._settings.server_directory),
            "-mcversion", minecraft_version, "-loader", loader, "-downloadMinecraft",
        )

    async def _run_java(self, *args: str) -> None:
        java = self._settings.server_java_executable or self._settings.local_java_executable_path
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
            line = _decode_process_line(raw_line).rstrip()
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
        except (httpx.HTTPError, UnsafeDownloadError) as error:
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
        try:
            await download_to_file(
                client,
                url,
                destination,
                max_bytes=_MAX_DOWNLOAD_BYTES,
                expected_hash=("sha1", sha1) if sha1 else None,
                on_progress=self._download_progress if self._progress else None,
            )
        except UnsafeDownloadError as error:
            raise InstallerServiceError("The download was rejected (unexpected host, size or checksum) and discarded.") from error
        except (httpx.HTTPError, OSError) as error:
            raise InstallerServiceError("The official server download failed. Check the connection and try again.") from error

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
        # newline="" writes the line endings exactly as given. Text mode on
        # Windows would otherwise turn run.bat into CR CR LF and run.sh into
        # CRLF, which breaks the script when the server folder is moved to Linux.
        (root / "run.bat").write_text(bat, encoding="utf-8", newline="")
        shell_path = root / "run.sh"
        shell_path.write_text(shell, encoding="utf-8", newline="")
        with contextlib.suppress(OSError):
            os.chmod(shell_path, 0o700)

    async def _publish(self, message: str) -> None:
        """Show a line in the console and as the current step's sentence."""
        report(self._progress, self._current_step, message[:300])
        await self._connections.broadcast_json({
            "type": "log",
            "line": {"timestamp": datetime.now(UTC).isoformat(), "stream": "installer", "message": f"[Installer] {message}"},
        })


installer_service = InstallerService()
