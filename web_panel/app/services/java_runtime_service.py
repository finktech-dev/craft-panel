"""Download and install a version-appropriate Java runtime inside this clone."""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import tarfile
import uuid
import zipfile
from pathlib import Path

import httpx

from app.core.config import Settings, settings

_ADOPTIUM_API = "https://api.adoptium.net/v3/assets/latest/{major}/hotspot"


class JavaRuntimeServiceError(RuntimeError):
    status_code = 502


class JavaRuntimeValidationError(JavaRuntimeServiceError):
    status_code = 422


class JavaRuntimeService:
    """Installs only the runtime in ``tools/java``; it never changes system Java."""

    def __init__(self, configured_settings: Settings = settings) -> None:
        self._settings = configured_settings
        self._lock = asyncio.Lock()

    @staticmethod
    def required_major(minecraft_version: str) -> int:
        """Minecraft's general Java baseline; mod loaders can impose stricter rules."""
        try:
            major, minor, *patch = (int(part) for part in minecraft_version.split("."))
        except ValueError as error:
            raise JavaRuntimeValidationError("La versión de Minecraft no es válida.") from error
        if major != 1:
            raise JavaRuntimeValidationError("Solo se admiten versiones modernas de Minecraft 1.x.")
        if minor >= 20 and (minor > 20 or (patch and patch[0] >= 5)):
            return 21
        if minor >= 18:
            return 17
        if minor == 17:
            return 16
        return 8

    async def install_for(self, minecraft_version: str) -> str:
        required = self.required_major(minecraft_version)
        destination = self._settings.local_java_executable_path
        if destination.is_file():
            return f"Ya existe Java local en tools/java. No se reemplazó."
        assert self._settings.tools_directory is not None
        target = self._settings.tools_directory / "java"
        if target.exists():
            raise JavaRuntimeValidationError("tools/java ya existe, pero no contiene un ejecutable Java válido. Corregilo o eliminá esa carpeta antes de descargar otro runtime.")
        async with self._lock:
            if destination.is_file():
                return "Ya existe Java local en tools/java. No se reemplazó."
            await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
            archive = target.parent / f".java-{uuid.uuid4().hex}.download"
            staging = target.parent / f".java-{uuid.uuid4().hex}.extract"
            try:
                package = await self._find_package(required)
                await self._download(package["link"], archive)
                await asyncio.to_thread(self._extract_runtime, archive, staging)
                executable = self._find_java(staging)
                if executable is None:
                    raise JavaRuntimeServiceError("La descarga oficial no contenía un ejecutable Java utilizable.")
                runtime_root = executable.parents[1]
                await asyncio.to_thread(os.replace, runtime_root, target)
            except (httpx.HTTPError, OSError, tarfile.TarError, zipfile.BadZipFile) as error:
                if isinstance(error, JavaRuntimeServiceError):
                    raise
                raise JavaRuntimeServiceError("No se pudo descargar o preparar Java desde Adoptium. Revisá la conexión e intentá de nuevo.") from error
            finally:
                await asyncio.to_thread(self._remove_path, archive)
                await asyncio.to_thread(self._remove_path, staging)
        return f"Java {required} se descargó dentro de tools/java. No se modificó la instalación de tu computadora."

    async def _find_package(self, major: int) -> dict[str, str]:
        os_name = {"Windows": "windows", "Linux": "linux", "Darwin": "mac"}.get(platform.system())
        if os_name is None:
            raise JavaRuntimeValidationError("Este sistema operativo todavía no está soportado para descarga automática de Java.")
        machine = platform.machine().casefold()
        architecture = "aarch64" if machine in {"arm64", "aarch64"} else "x64"
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0), follow_redirects=True) as client:
            for image_type in ("jre", "jdk"):
                response = await client.get(
                    _ADOPTIUM_API.format(major=major),
                    params={"architecture": architecture, "image_type": image_type, "os": os_name, "vendor": "eclipse"},
                )
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                releases = response.json()
                if not isinstance(releases, list) or not releases:
                    continue
                package = releases[0].get("binary", {}).get("package", {})
                link = package.get("link") if isinstance(package, dict) else None
                if isinstance(link, str) and link.startswith("https://"):
                    return {"link": link}
        raise JavaRuntimeServiceError("Adoptium no ofreció un runtime compatible para esta computadora.")

    async def _download(self, url: str, destination: Path) -> None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0), follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with destination.open("wb") as output:
                    async for chunk in response.aiter_bytes(64 * 1024):
                        output.write(chunk)

    def _extract_runtime(self, archive: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=False)
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as contents:
                self._safe_extract_zip(contents, destination)
            return
        with tarfile.open(archive, "r:*") as contents:
            self._safe_extract_tar(contents, destination)

    @staticmethod
    def _safe_extract_zip(contents: zipfile.ZipFile, destination: Path) -> None:
        root = destination.resolve()
        for member in contents.infolist():
            candidate = (destination / member.filename).resolve()
            if not candidate.is_relative_to(root):
                raise JavaRuntimeServiceError("El archivo descargado contenía una ruta insegura.")
        contents.extractall(destination)

    @staticmethod
    def _safe_extract_tar(contents: tarfile.TarFile, destination: Path) -> None:
        root = destination.resolve()
        for member in contents.getmembers():
            candidate = (destination / member.name).resolve()
            if not candidate.is_relative_to(root) or member.issym() or member.islnk():
                raise JavaRuntimeServiceError("El archivo descargado contenía una ruta insegura.")
        contents.extractall(destination)

    def _find_java(self, root: Path) -> Path | None:
        executable = "java.exe" if os.name == "nt" else "java"
        candidates = [path for path in root.rglob(executable) if path.parent.name == "bin" and path.is_file()]
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _remove_path(path: Path) -> None:
        if path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


java_runtime_service = JavaRuntimeService()