"""Safe operations on local mods and the public Modrinth API."""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import contextlib
import json
import logging
import re
import tomllib
import uuid
import zipfile
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import aiofiles
import httpx
from fastapi import UploadFile

from app.core.archive_safety import read_member_capped
from app.core.config import Settings, settings
from app.core.net_safety import MODRINTH_HOSTS, allowed_client, download_to_file, is_allowed_url
from app.core.path_safety import is_safe_component
from app.schemas.mod import (
    ModBulkActionResponse,
    ModItem,
    ModrinthSearchHit,
    ModToggleResponse,
    ModUpdateItem,
)
from app.services.mod_history_service import HistoryToken, ModHistoryService, is_mod_filename
from app.services.runtime_guard import ServerActiveError, require_server_stopped
from app.services.protected_paths import require_not_protected
from app.services.server_settings_file import read_server_settings
from app.services.server_process import MinecraftServerManager, server_manager
from app.services.server_version_service import ServerVersionService

logger = logging.getLogger(__name__)
_MEBIBYTE: Final = 1024 * 1024
_MODRINTH_API: Final = "https://api.modrinth.com/v2"
_MAX_UPLOAD_BYTES: Final = 1_024 * _MEBIBYTE
_DOWNLOAD_CHUNK_SIZE: Final = 64 * 1024
_MAX_METADATA_BYTES: Final = 1 * _MEBIBYTE
_MAX_DEPENDENCY_INSTALLS: Final = 30
# Modrinth project/version IDs are base62; slugs add "-", "_" and ".".
_MODRINTH_ID: Final = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_UPDATES_CACHE_SECONDS: Final = 6 * 3600
_ZIP_MAGIC: Final = (b"PK\x03\x04", b"PK\x05\x06")
SERVER_ONLY_MODS: Final[frozenset[str]] = frozenset({
    "chunky",
    "bluemap",
    "spark",
    "alternate_current",
    "alternate-current",
    "ai-improvements",
    "noisium",
    "luckperms",
    "skinrestorer",
    "worldedit",
    "simpletrading",
})


class ModServiceError(RuntimeError):
    status_code = 400


class ModNotFoundError(ModServiceError):
    status_code = 404


class ModConflictError(ModServiceError):
    status_code = 409


class ModrinthServiceError(ModServiceError):
    status_code = 502


def user_server_only_mods(configured: Settings) -> tuple[str, ...]:
    """[server_only_mods] from craftpanel.txt; empty when unavailable."""
    try:
        return read_server_settings(configured).items("server_only_mods")
    except Exception:  # noqa: BLE001 - a broken settings file must not break the mod list
        return ()


def matches_server_only_rule(filename: str, mod_id: str | None, rules: Iterable[str]) -> bool:
    """A rule with * or ? (or ending in .jar) is a file name pattern; anything else is a mod id or name prefix."""
    name = filename.casefold().removesuffix(".disabled")
    for rule in rules:
        lowered = rule.casefold()
        if any(character in lowered for character in "*?") or lowered.endswith(".jar"):
            if fnmatch.fnmatchcase(name, lowered):
                return True
            continue
        if mod_id and mod_id.casefold() == lowered:
            return True
        if name == f"{lowered}.jar" or name.startswith((f"{lowered}-", f"{lowered}_")):
            return True
    return False


class ModService:
    """Mod file service; never changes the running server."""

    def __init__(
        self,
        configured_settings: Settings = settings,
        manager: MinecraftServerManager = server_manager,
    ) -> None:
        self._settings = configured_settings
        self._manager = manager
        self._versions = ServerVersionService(configured_settings)
        self.history = ModHistoryService(configured_settings, manager)
        self._updates_cache: tuple[datetime, tuple[tuple[str, str], ...], list[ModUpdateItem]] | None = None

    def _require_server_stopped(self, operation: str) -> None:
        try:
            require_server_stopped(self._manager, operation)
        except ServerActiveError as error:
            raise ModConflictError(str(error)) from error

    @contextlib.asynccontextmanager
    async def _history_step(self, action: str, detail: dict[str, Any] | None = None) -> AsyncIterator[HistoryToken | None]:
        """Snapshot the mods folder before a change; history problems never block the change."""
        token: HistoryToken | None = None
        try:
            token = await asyncio.to_thread(self.history.begin, action, detail)
        except Exception as error:
            logger.warning("No se pudo guardar el historial de mods antes de %s: %s", action, error)
        try:
            yield token
        finally:
            if token is not None:
                try:
                    await asyncio.to_thread(self.history.finish, token)
                except Exception as error:
                    logger.warning("No se pudo completar el historial de mods: %s", error)

    @property
    def mods_directory(self) -> Path:
        assert self._settings.mods_directory is not None
        return self._settings.mods_directory

    @property
    def client_pack_path(self) -> Path:
        assert self._settings.client_pack_directory is not None
        return self._settings.client_pack_directory / self._settings.client_pack_filename

    async def list_mods(self) -> list[ModItem]:
        try:
            await asyncio.to_thread(self.history.record_external_changes)
        except Exception as error:
            logger.warning("No se pudo revisar si cambiaron los mods por fuera del panel: %s", error)
        if not self.mods_directory.is_dir():
            return []
        return await asyncio.to_thread(self._list_mods_sync)

    async def toggle_mod(self, filename: str) -> ModToggleResponse:
        self._require_server_stopped("habilitar o deshabilitar mods")
        source = self._resolve_mod_path(filename)
        if not source.is_file():
            raise ModNotFoundError("No existe el mod indicado.")

        is_enabled = source.name.endswith(".jar")
        target_name = f"{source.name}.disabled" if is_enabled else source.name.removesuffix(".disabled")
        target = self._resolve_mod_path(target_name)
        if target.exists():
            raise ModConflictError("Ya existe un mod con el nombre de destino.")
        require_not_protected(source, target, configured=self._settings)

        try:
            async with self._history_step("toggle", {"filename": source.name}):
                await asyncio.to_thread(source.rename, target)
        except FileExistsError as error:
            raise ModConflictError("Ya existe un mod con el nombre de destino.") from error
        except OSError as error:
            raise ModServiceError(f"No se pudo cambiar el estado del mod: {error}") from error

        enabled_after_toggle = not is_enabled
        return ModToggleResponse(
            filename=target.name,
            is_enabled=enabled_after_toggle,
            message="Mod habilitado." if enabled_after_toggle else "Mod deshabilitado.",
        )

    async def upload_mod(self, uploaded_file: UploadFile) -> ModItem:
        self._require_server_stopped("subir mods")
        filename = self._validate_filename(uploaded_file.filename or "")
        if not filename.endswith(".jar"):
            raise ModServiceError("Solo se permiten archivos .jar.")

        await asyncio.to_thread(self.mods_directory.mkdir, parents=True, exist_ok=True)
        destination = self._resolve_mod_path(filename)
        if destination.exists():
            raise ModConflictError("Ya existe un mod con ese nombre.")
        require_not_protected(destination, configured=self._settings)

        temporary_path = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.uploading")
        written_bytes = 0
        try:
            async with aiofiles.open(temporary_path, "wb") as target_file:
                while chunk := await uploaded_file.read(_DOWNLOAD_CHUNK_SIZE):
                    if written_bytes == 0 and not chunk.startswith(_ZIP_MAGIC):
                        raise ModServiceError("El archivo no es un .jar válido.")
                    written_bytes += len(chunk)
                    if written_bytes > _MAX_UPLOAD_BYTES:
                        raise ModServiceError("El archivo supera el límite de 1024 MB.")
                    await target_file.write(chunk)
            if not await asyncio.to_thread(zipfile.is_zipfile, temporary_path):
                raise ModServiceError("El archivo no es un .jar válido.")
            async with self._history_step("upload", {"filename": destination.name}):
                await asyncio.to_thread(temporary_path.rename, destination)
        except FileExistsError as error:
            raise ModConflictError("Ya existe un mod con ese nombre.") from error
        except OSError as error:
            raise ModServiceError(f"No se pudo guardar el mod: {error}") from error
        finally:
            await uploaded_file.close()
            if temporary_path.exists():
                await asyncio.to_thread(temporary_path.unlink)

        return await asyncio.to_thread(self._mod_item_from_path, destination, self._settings)

    async def delete_mod(self, filename: str) -> None:
        self._require_server_stopped("eliminar mods")
        target = self._resolve_mod_path(filename)
        if not target.is_file():
            raise ModNotFoundError("No existe el mod indicado.")
        require_not_protected(target, configured=self._settings)
        try:
            async with self._history_step("delete", {"filename": target.name}):
                await asyncio.to_thread(target.unlink)
        except OSError as error:
            raise ModServiceError(f"No se pudo eliminar el mod: {error}") from error

    async def bulk_action(self, action: str, filenames: list[str]) -> ModBulkActionResponse:
        """Safely apply a bulk action (enable, disable, delete)."""
        self._require_server_stopped(f"operación en lote: {action}")
        async with self._history_step(f"bulk_{action}", {"count": len(filenames)}):
            affected, errors = await self._apply_bulk_action(action, filenames)

        action_labels = {"enable": "habilitados", "disable": "deshabilitados", "delete": "eliminados"}
        label = action_labels.get(action, action)
        message = (
            f"{affected} mods {label} correctamente."
            if not errors
            else f"{affected} mods {label}, con {len(errors)} advertencias."
        )
        return ModBulkActionResponse(
            action=action,
            affected_count=affected,
            errors=errors,
            message=message,
        )

    async def _apply_bulk_action(self, action: str, filenames: list[str]) -> tuple[int, list[str]]:
        affected = 0
        errors: list[str] = []

        for name in filenames:
            try:
                target = self._resolve_mod_path(name)
                if not target.is_file():
                    errors.append(f"{name}: no existe.")
                    continue
                if action in {"enable", "disable", "delete"}:
                    renamed = target.with_name(
                        target.name.removesuffix(".disabled") if action == "enable" else f"{target.name}.disabled"
                    )
                    require_not_protected(target, renamed, configured=self._settings)

                if action == "enable":
                    if target.name.endswith(".jar.disabled"):
                        dest = target.with_name(target.name.removesuffix(".disabled"))
                        if dest.exists():
                            errors.append(f"{name}: el archivo activo ya existe.")
                            continue
                        await asyncio.to_thread(target.rename, dest)
                        affected += 1
                elif action == "disable":
                    if target.name.endswith(".jar"):
                        dest = target.with_name(f"{target.name}.disabled")
                        if dest.exists():
                            errors.append(f"{name}: el archivo desactivado ya existe.")
                            continue
                        await asyncio.to_thread(target.rename, dest)
                        affected += 1
                elif action == "delete":
                    await asyncio.to_thread(target.unlink)
                    affected += 1
            except Exception as err:
                errors.append(f"{name}: {err}")
        return affected, errors

    def get_environment(self) -> dict[str, str]:
        """Loader and Minecraft version of the installed server; empty strings when unknown.

        Empty values disable the matching Modrinth filter instead of guessing a version.
        """
        info = self._versions.detect()
        return {
            "loader": "" if info.loader == "unknown" else info.loader,
            "minecraft_version": info.minecraft_version or "",
            "loader_version": info.loader_version or "",
            "label": info.label or "",
        }

    async def search_modrinth(
        self,
        query: str,
        loader: str | None = None,
        game_version: str | None = None,
    ) -> list[ModrinthSearchHit]:
        cleaned_query = query.strip()
        if not cleaned_query:
            raise ModServiceError("La búsqueda no puede estar vacía.")

        env = self.get_environment()
        effective_loader = (loader if loader is not None else env["loader"]).lower()
        effective_version = (game_version if game_version is not None else env["minecraft_version"]).lower()

        facets: list[list[str]] = []
        if effective_version and effective_version not in ("all", "any", "cualquiera", ""):
            facets.append([f"versions:{effective_version}"])
        if effective_loader and effective_loader not in ("all", "any", "cualquiera", "vanilla", "custom", ""):
            facets.append([f"categories:{effective_loader}"])

        params: dict[str, Any] = {
            "query": cleaned_query,
            "limit": 20,
        }
        if facets:
            params["facets"] = json.dumps(facets)

        try:
            async with allowed_client(MODRINTH_HOSTS, timeout=20.0, follow_redirects=False) as client:
                response = await client.get(f"{_MODRINTH_API}/search", params=params)
                response.raise_for_status()
            hits = response.json().get("hits", [])
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("Falló la búsqueda en Modrinth: %s", error)
            raise ModrinthServiceError("No se pudo consultar Modrinth.") from error

        return [
            ModrinthSearchHit(
                project_id=hit["project_id"],
                slug=hit["slug"],
                title=hit["title"],
                description=hit.get("description", ""),
                icon_url=hit.get("icon_url"),
                downloads=hit.get("downloads", 0),
            )
            for hit in hits
        ]

    async def install_modrinth_mod(
        self,
        project_id: str,
        version_id: str | None = None,
        loader: str | None = None,
        game_version: str | None = None,
        install_dependencies: bool = True,
        visited_projects: set[str] | None = None,
        replace_filename: str | None = None,
    ) -> ModItem:
        """Install a Modrinth project (and its required dependencies).

        ``replace_filename`` turns the install into an update: the old jar is
        removed once the new one is in place. The whole step is one history entry.
        """
        self._require_server_stopped("instalar mods")
        if visited_projects is not None:
            return await self._install_modrinth_mod(
                project_id, version_id, loader, game_version, install_dependencies, visited_projects
            )
        replaced = self._resolve_mod_path(replace_filename) if replace_filename else None
        if replaced is not None:
            require_not_protected(replaced, configured=self._settings)
        action = "update" if replaced is not None else "install"
        async with self._history_step(action, {"project_id": project_id}) as token:
            item = await self._install_modrinth_mod(
                project_id, version_id, loader, game_version, install_dependencies, None
            )
            if token is not None:
                token.detail["filename"] = item.filename
            if replaced is not None and replaced.name != item.filename and replaced.is_file():
                try:
                    await asyncio.to_thread(replaced.unlink)
                except OSError as error:
                    logger.warning("No se pudo quitar la versión anterior %s: %s", replaced.name, error)
        return item

    async def _install_modrinth_mod(
        self,
        project_id: str,
        version_id: str | None,
        loader: str | None,
        game_version: str | None,
        install_dependencies: bool,
        visited_projects: set[str] | None,
    ) -> ModItem:
        if visited_projects is not None and len(visited_projects) > _MAX_DEPENDENCY_INSTALLS:
            raise ModServiceError("El mod tiene demasiadas dependencias para instalarlas automáticamente.")
        version = await self._get_compatible_version(project_id, version_id, loader, game_version)
        file_data = self._select_download_file(version)
        filename = self._validate_filename(str(file_data.get("filename", "")))
        if not filename.endswith(".jar"):
            raise ModrinthServiceError("La versión seleccionada no contiene un archivo .jar válido.")

        await asyncio.to_thread(self.mods_directory.mkdir, parents=True, exist_ok=True)
        destination = self._resolve_mod_path(filename)
        if destination.exists():
            raise ModConflictError("Ese archivo ya está instalado.")
        require_not_protected(destination, configured=self._settings)

        download_url = file_data.get("url")
        if not isinstance(download_url, str) or not is_allowed_url(download_url, MODRINTH_HOSTS):
            raise ModrinthServiceError("Modrinth no entregó una URL de descarga segura.")
        expected_hash = self._expected_hash(file_data)
        declared_size = file_data.get("size")
        max_bytes = (
            declared_size
            if isinstance(declared_size, int) and 0 < declared_size <= _MAX_UPLOAD_BYTES
            else _MAX_UPLOAD_BYTES
        )

        try:
            async with allowed_client(MODRINTH_HOSTS, timeout=90.0) as client:
                await download_to_file(
                    client, download_url, destination, max_bytes=max_bytes, expected_hash=expected_hash
                )
        except (httpx.HTTPError, OSError) as error:
            logger.warning("Falló la descarga de %s: %s", project_id, error)
            raise ModrinthServiceError("No se pudo descargar el mod desde Modrinth.") from error

        # Automatic resolution of required dependencies
        if install_dependencies:
            if visited_projects is None:
                visited_projects = set()
            visited_projects.add(project_id)

            dependencies = version.get("dependencies")
            if isinstance(dependencies, list):
                for dep in dependencies:
                    if dep.get("dependency_type") == "required" and dep.get("project_id"):
                        dep_proj = dep["project_id"]
                        if dep_proj not in visited_projects and len(visited_projects) <= _MAX_DEPENDENCY_INSTALLS:
                            visited_projects.add(dep_proj)
                            try:
                                await self._install_modrinth_mod(
                                    dep_proj,
                                    dep.get("version_id"),
                                    None,
                                    None,
                                    True,
                                    visited_projects,
                                )
                                logger.info("Dependencia requerida %s instalada con éxito", dep_proj)
                            except ModConflictError:
                                pass  # Already on disk
                            except Exception as dep_err:
                                logger.warning("No se pudo autoinstalar dependencia requerida %s: %s", dep_proj, dep_err)

        return await asyncio.to_thread(self._mod_item_from_path, destination, self._settings)

    async def check_updates(self, *, refresh: bool = False) -> list[ModUpdateItem]:
        """Updates for enabled mods, identified by file hash so version labels never cause false alarms.

        Modrinth answers for the whole folder in two requests. Results are kept for a few hours
        so the mods page can show its "Actualizaciones" tab right away.
        """
        installed = [mod for mod in await self.list_mods() if mod.is_enabled]
        signature = tuple(sorted((mod.filename, mod.modified_at) for mod in installed))
        cached = self._updates_cache
        if (
            not refresh
            and cached is not None
            and cached[1] == signature
            and (datetime.now(UTC) - cached[0]).total_seconds() < _UPDATES_CACHE_SECONDS
        ):
            return cached[2]
        results = await self._check_updates_by_hash(installed)
        self._updates_cache = (datetime.now(UTC), signature, results)
        return results

    async def _check_updates_by_hash(self, installed: list[ModItem]) -> list[ModUpdateItem]:
        if not installed:
            return []
        hashes = await asyncio.to_thread(self._sha1_by_filename, [mod.filename for mod in installed])
        if not hashes:
            return []
        env = self.get_environment()
        loader = (env["loader"] or "").lower()
        mc_version = (env["minecraft_version"] or "").lower()
        update_query: dict[str, Any] = {"hashes": list(hashes.values()), "algorithm": "sha1"}
        if loader not in ("all", "any", "vanilla", "custom", ""):
            update_query["loaders"] = [loader]
        if mc_version not in ("all", "any", ""):
            update_query["game_versions"] = [mc_version]
        try:
            async with allowed_client(MODRINTH_HOSTS, timeout=20.0, follow_redirects=False) as client:
                current_response = await client.post(
                    f"{_MODRINTH_API}/version_files", json={"hashes": update_query["hashes"], "algorithm": "sha1"}
                )
                latest_response = await client.post(f"{_MODRINTH_API}/version_files/update", json=update_query)
        except httpx.HTTPError as error:
            raise ModrinthServiceError("No pudimos consultar Modrinth. Revisá la conexión a internet.") from error
        if current_response.status_code != 200 or latest_response.status_code != 200:
            raise ModrinthServiceError("Modrinth no respondió bien. Probá de nuevo en un rato.")
        current_versions = current_response.json() if isinstance(current_response.json(), dict) else {}
        latest_versions = latest_response.json() if isinstance(latest_response.json(), dict) else {}

        results: list[ModUpdateItem] = []
        for mod in installed:
            digest = hashes.get(mod.filename)
            current = current_versions.get(digest) if digest else None
            if not isinstance(current, dict):
                # Not published on Modrinth (or a custom build): nothing to compare against.
                continue
            latest = latest_versions.get(digest)
            item = ModUpdateItem(
                filename=mod.filename,
                mod_id=mod.mod_id,
                name=mod.name,
                current_version=current.get("version_number") or mod.version,
                latest_version=None,
                project_id=current.get("project_id"),
                version_id=None,
                has_update=False,
            )
            if isinstance(latest, dict) and latest.get("id") and latest.get("id") != current.get("id"):
                newer = str(latest.get("date_published", "")) > str(current.get("date_published", ""))
                if newer:
                    item.latest_version = latest.get("version_number")
                    item.version_id = latest.get("id")
                    item.has_update = True
            results.append(item)
        return results

    def _sha1_by_filename(self, filenames: list[str]) -> dict[str, str]:
        digests: dict[str, str] = {}
        for filename in filenames:
            path = self.mods_directory / filename
            if not is_safe_component(filename) or path.is_symlink() or not path.is_file():
                continue
            digest = hashlib.sha1(usedforsecurity=False)
            try:
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError:
                continue
            digests[filename] = digest.hexdigest()
        return digests

    async def export_client_pack(self) -> Path:
        """Pack enabled mods and existing configs without blocking FastAPI."""
        await asyncio.to_thread(self.client_pack_path.parent.mkdir, parents=True, exist_ok=True)
        temporary_path = self.client_pack_path.with_suffix(".zip.part")
        try:
            await asyncio.to_thread(self._build_client_pack_sync, temporary_path)
            await asyncio.to_thread(temporary_path.replace, self.client_pack_path)
        except OSError as error:
            raise ModServiceError(f"No se pudo generar el modpack: {error}") from error
        finally:
            if temporary_path.exists():
                await asyncio.to_thread(temporary_path.unlink)
        return self.client_pack_path

    async def _get_compatible_version(
        self,
        project_id: str,
        version_id: str | None,
        loader: str | None = None,
        game_version: str | None = None,
    ) -> dict[str, Any]:
        for identifier in (project_id, version_id):
            if identifier is not None and not _MODRINTH_ID.match(identifier):
                raise ModServiceError("El identificador de Modrinth no es válido.")
        env = self.get_environment()
        effective_loader = (loader if loader is not None else env["loader"]).lower()
        effective_version = (game_version if game_version is not None else env["minecraft_version"]).lower()

        loaders_filter = [effective_loader] if effective_loader not in ("all", "any", "vanilla", "custom", "") else []
        versions_filter = [effective_version] if effective_version not in ("all", "any", "") else []

        try:
            async with allowed_client(MODRINTH_HOSTS, timeout=20.0, follow_redirects=False) as client:
                if version_id:
                    response = await client.get(f"{_MODRINTH_API}/version/{version_id}")
                    response.raise_for_status()
                    version = response.json()
                    if version.get("project_id") != project_id:
                        raise ModServiceError("La versión indicada no pertenece a ese proyecto.")
                    candidates = [version]
                else:
                    query_params: dict[str, Any] = {}
                    if loaders_filter:
                        query_params["loaders"] = json.dumps(loaders_filter)
                    if versions_filter:
                        query_params["game_versions"] = json.dumps(versions_filter)

                    response = await client.get(
                        f"{_MODRINTH_API}/project/{project_id}/version",
                        params=query_params or None,
                    )
                    response.raise_for_status()
                    candidates = response.json()
        except httpx.HTTPError as error:
            logger.warning("Falló la consulta de versión de Modrinth: %s", error)
            raise ModrinthServiceError("No se pudo consultar una versión compatible en Modrinth.") from error

        if not candidates:
            raise ModNotFoundError(f"No hay versiones disponibles para el proyecto {project_id}.")

        compatible_versions = []
        for candidate in candidates:
            c_loaders = [str(l).lower() for l in candidate.get("loaders", [])]
            c_versions = [str(v).lower() for v in candidate.get("game_versions", [])]
            match_loader = (not loaders_filter) or any(l in c_loaders for l in loaders_filter)
            match_version = (not versions_filter) or any(v in c_versions for v in versions_filter)
            if match_loader and match_version:
                compatible_versions.append(candidate)

        if not compatible_versions:
            compatible_versions = candidates

        return max(compatible_versions, key=lambda candidate: candidate.get("date_published", ""))


    @staticmethod
    def _expected_hash(file_data: dict[str, Any]) -> tuple[str, str] | None:
        hashes = file_data.get("hashes")
        if not isinstance(hashes, dict):
            return None
        for algorithm, length in (("sha512", 128), ("sha1", 40)):
            value = hashes.get(algorithm)
            if isinstance(value, str) and len(value) == length:
                return algorithm, value
        return None

    @staticmethod
    def _select_download_file(version: dict[str, Any]) -> dict[str, Any]:
        files = version.get("files", [])
        if not isinstance(files, list) or not files:
            raise ModrinthServiceError("La versión no contiene archivos descargables.")
        return next((item for item in files if item.get("primary") is True), files[0])

    def _build_client_pack_sync(self, destination: Path) -> None:
        with zipfile.ZipFile(destination, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            written_names: set[str] = set()
            user_rules = user_server_only_mods(self._settings)
            for mod_file in self._iter_active_mod_files():
                if mod_file.is_symlink():
                    continue
                # Mod ids in [server_only_mods] need the jar's metadata; file name rules do not.
                mod_id = self._extract_jar_metadata(mod_file).get("mod_id") if user_rules else None
                if self._is_server_only_mod(mod_file, mod_id, user_rules):
                    continue
                archive.write(mod_file, arcname=Path("mods") / mod_file.name)
                written_names.add(mod_file.name.lower())
            assert self._settings.server_directory is not None
            client_mods_dir = self._settings.server_directory / "client_only_mods"
            if client_mods_dir.is_dir():
                for client_mod in client_mods_dir.glob("*.jar"):
                    if not client_mod.is_symlink() and client_mod.name.lower() not in written_names:
                        archive.write(client_mod, arcname=Path("mods") / client_mod.name)
                        written_names.add(client_mod.name.lower())
            extra_directories = getattr(self._settings, "client_pack_extra_directories", []) or []
            pack_directories = ("config", "defaultconfigs", *extra_directories)
            for directory_name in pack_directories:
                # Extra directories come from settings; keep them inside server/.
                if not is_safe_component(directory_name):
                    continue
                source_directory = self._settings.server_directory / directory_name
                if source_directory.is_dir() and not source_directory.is_symlink():
                    self._add_directory_to_archive(archive, source_directory, Path(directory_name))

    @staticmethod
    def _add_directory_to_archive(archive: zipfile.ZipFile, source: Path, archive_root: Path) -> None:
        server_only_dirs = frozenset({"luckperms", "bluemap", "spark", "chunky", "worldedit", "skinrestorer"})
        for file_path in source.rglob("*"):
            if file_path.is_file() and not file_path.is_symlink():
                rel = file_path.relative_to(source)
                if any(part.lower() in server_only_dirs for part in rel.parts):
                    continue
                archive.write(file_path, arcname=archive_root / rel)

    def _list_mods_sync(self) -> list[ModItem]:
        items = [self._mod_item_from_path(path, self._settings) for path in self._iter_mod_files()]
        return sorted(items, key=lambda item: item.filename.casefold())

    def _iter_mod_files(self) -> Iterable[Path]:
        yield from self.mods_directory.glob("*.jar")
        yield from self.mods_directory.glob("*.jar.disabled")

    def _iter_active_mod_files(self) -> Iterable[Path]:
        if self.mods_directory.is_dir():
            yield from self.mods_directory.glob("*.jar")

    @staticmethod
    def _extract_jar_metadata(path: Path) -> dict[str, Any]:
        result: dict[str, Any] = {
            "mod_id": None,
            "display_name": None,
            "version": None,
            "description": None,
            "authors": None,
        }
        if not path.is_file() or path.stat().st_size < 100:
            return result

        try:
            with zipfile.ZipFile(path, "r") as archive:
                namelist = set(archive.namelist())

                # 1. NeoForge / Forge mods.toml
                toml_candidate = None
                for candidate in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
                    if candidate in namelist:
                        toml_candidate = candidate
                        break

                if toml_candidate:
                    raw_bytes = read_member_capped(archive, toml_candidate, _MAX_METADATA_BYTES)
                    if raw_bytes is None:
                        return result
                    raw_toml = raw_bytes.decode("utf-8", errors="replace")
                    data = tomllib.loads(raw_toml)
                    mods = data.get("mods")
                    if isinstance(mods, list) and mods:
                        first = mods[0]
                        if isinstance(first, dict):
                            result["mod_id"] = first.get("modId")
                            result["display_name"] = first.get("displayName")
                            raw_version = str(first.get("version", "")).strip()
                            if raw_version and not raw_version.startswith("${"):
                                result["version"] = raw_version
                            result["description"] = first.get("description")
                            authors = first.get("authors")
                            if isinstance(authors, list):
                                result["authors"] = ", ".join(str(a) for a in authors)
                            elif isinstance(authors, str):
                                result["authors"] = authors
                    return result

                # 2. Fabric / Quilt fabric.mod.json
                if "fabric.mod.json" in namelist:
                    raw_bytes = read_member_capped(archive, "fabric.mod.json", _MAX_METADATA_BYTES)
                    if raw_bytes is None:
                        return result
                    raw_json = raw_bytes.decode("utf-8", errors="replace")
                    data = json.loads(raw_json)
                    result["mod_id"] = data.get("id")
                    result["display_name"] = data.get("name")
                    result["version"] = data.get("version")
                    result["description"] = data.get("description")
                    authors = data.get("authors")
                    if isinstance(authors, list):
                        result["authors"] = ", ".join(
                            str(a.get("name", a) if isinstance(a, dict) else a) for a in authors
                        )
                    elif isinstance(authors, str):
                        result["authors"] = authors
                    return result
        except Exception as error:
            logger.debug("No se pudieron extraer metadatos de %s: %s", path.name, error)

        return result

    @staticmethod
    def _find_mod_config(server_directory: Path | None, mod_id: str | None, filename_stem: str) -> str | None:
        if not server_directory:
            return None
        config_dir = server_directory / "config"
        if not config_dir.is_dir():
            return None

        candidates_to_check: list[str] = []
        if mod_id:
            cleaned_id = mod_id.strip().casefold()
            candidates_to_check.extend([
                f"{cleaned_id}.toml",
                f"{cleaned_id}-common.toml",
                f"{cleaned_id}-server.toml",
                f"{cleaned_id}-client.toml",
            ])

        cleaned_stem = filename_stem.strip().casefold()
        candidates_to_check.extend([
            f"{cleaned_stem}.toml",
            f"{cleaned_stem}-common.toml",
            f"{cleaned_stem}-server.toml",
        ])

        for candidate_name in candidates_to_check:
            candidate_path = config_dir / candidate_name
            if candidate_path.is_file():
                return candidate_name

        return None

    @staticmethod
    def _is_server_only_mod(mod_file: Path, mod_id: str | None = None, user_rules: tuple[str, ...] = ()) -> bool:
        if mod_id and mod_id.casefold() in SERVER_ONLY_MODS:
            return True
        normalized_name = mod_file.name.casefold()
        if user_rules and matches_server_only_rule(mod_file.name, mod_id, user_rules):
            return True
        return any(
            normalized_name == f"{mod_name}.jar"
            or normalized_name.startswith(f"{mod_name}-")
            or normalized_name.startswith(f"{mod_name}_")
            for mod_name in SERVER_ONLY_MODS
        )

    @classmethod
    def _mod_item_from_path(cls, path: Path, settings_obj: Settings | None = None) -> ModItem:
        is_enabled = path.name.endswith(".jar")
        suffix = ".jar" if is_enabled else ".jar.disabled"
        stem = path.name.removesuffix(suffix)

        metadata = cls._extract_jar_metadata(path)
        mod_id = metadata.get("mod_id")
        display_name = metadata.get("display_name") or stem
        version = metadata.get("version")
        description = metadata.get("description")
        authors = metadata.get("authors")

        active_settings = settings_obj or settings
        server_dir = getattr(active_settings, "server_directory", None)
        config_filename = cls._find_mod_config(server_dir, mod_id, stem)

        return ModItem(
            filename=path.name,
            name=display_name,
            size_mb=round(path.stat().st_size / _MEBIBYTE, 2),
            is_enabled=is_enabled,
            modified_at=datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
            is_server_only=cls._is_server_only_mod(path, mod_id, user_server_only_mods(active_settings)),
            mod_id=mod_id,
            version=version,
            description=description,
            authors=authors,
            has_config=config_filename is not None,
            config_filename=config_filename,
        )

    def _resolve_mod_path(self, filename: str) -> Path:
        safe_filename = self._validate_filename(filename)
        candidate = (self.mods_directory / safe_filename).resolve()
        if not candidate.is_relative_to(self.mods_directory.resolve()):
            raise ModServiceError("La ruta del mod no es válida.")
        return candidate

    @staticmethod
    def _validate_filename(filename: str) -> str:
        if not filename or Path(filename).name != filename or not is_safe_component(filename):
            raise ModServiceError("El nombre del archivo no es válido.")
        if not is_mod_filename(filename):
            raise ModServiceError("El archivo debe terminar en .jar o .jar.disabled.")
        return filename


mod_service = ModService()
