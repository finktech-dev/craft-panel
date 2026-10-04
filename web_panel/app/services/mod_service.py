"""Operaciones seguras sobre mods locales y la API pública de Modrinth."""

from __future__ import annotations

import asyncio
import json
import logging
import tomllib
import uuid
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import aiofiles
import httpx
from fastapi import UploadFile

from app.core.config import Settings, settings
from app.schemas.mod import (
    ModBulkActionResponse,
    ModItem,
    ModrinthSearchHit,
    ModToggleResponse,
    ModUpdateItem,
)
from app.services.runtime_guard import ServerActiveError, require_server_stopped
from app.services.server_process import MinecraftServerManager, server_manager

logger = logging.getLogger(__name__)
_MEBIBYTE: Final = 1024 * 1024
_MODRINTH_API: Final = "https://api.modrinth.com/v2"
_MAX_UPLOAD_BYTES: Final = 1_024 * _MEBIBYTE
_DOWNLOAD_CHUNK_SIZE: Final = 64 * 1024
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


class ModService:
    """Servicio de archivos de mods; no ejecuta cambios sobre el servidor vivo."""

    def __init__(
        self,
        configured_settings: Settings = settings,
        manager: MinecraftServerManager = server_manager,
    ) -> None:
        self._settings = configured_settings
        self._manager = manager

    def _require_server_stopped(self, operation: str) -> None:
        try:
            require_server_stopped(self._manager, operation)
        except ServerActiveError as error:
            raise ModConflictError(str(error)) from error

    @property
    def mods_directory(self) -> Path:
        assert self._settings.mods_directory is not None
        return self._settings.mods_directory

    @property
    def client_pack_path(self) -> Path:
        assert self._settings.client_pack_directory is not None
        return self._settings.client_pack_directory / self._settings.client_pack_filename

    async def list_mods(self) -> list[ModItem]:
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

        try:
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

        temporary_path = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.uploading")
        written_bytes = 0
        try:
            async with aiofiles.open(temporary_path, "wb") as target_file:
                while chunk := await uploaded_file.read(_DOWNLOAD_CHUNK_SIZE):
                    written_bytes += len(chunk)
                    if written_bytes > _MAX_UPLOAD_BYTES:
                        raise ModServiceError("El archivo supera el límite de 1024 MB.")
                    await target_file.write(chunk)
            await asyncio.to_thread(temporary_path.rename, destination)
        except FileExistsError as error:
            raise ModConflictError("Ya existe un mod con ese nombre.") from error
        except OSError as error:
            raise ModServiceError(f"No se pudo guardar el mod: {error}") from error
        finally:
            await uploaded_file.close()
            if temporary_path.exists():
                await asyncio.to_thread(temporary_path.unlink)

        return await asyncio.to_thread(self._mod_item_from_path, destination)

    async def delete_mod(self, filename: str) -> None:
        self._require_server_stopped("eliminar mods")
        target = self._resolve_mod_path(filename)
        if not target.is_file():
            raise ModNotFoundError("No existe el mod indicado.")
        try:
            await asyncio.to_thread(target.unlink)
        except OSError as error:
            raise ModServiceError(f"No se pudo eliminar el mod: {error}") from error

    async def bulk_action(self, action: str, filenames: list[str]) -> ModBulkActionResponse:
        """Aplica una acción en lote (enable, disable, delete) de forma segura."""
        self._require_server_stopped(f"operación en lote: {action}")
        affected = 0
        errors: list[str] = []

        for name in filenames:
            try:
                target = self._resolve_mod_path(name)
                if not target.is_file():
                    errors.append(f"{name}: no existe.")
                    continue

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

    def get_environment(self) -> dict[str, str]:
        """Detecta dinámicamente el cargador de mods (loader) y versión de Minecraft del servidor."""
        loader = "neoforge"
        version = self._settings.minecraft_version or "1.21.1"

        server_root = self._settings.server_directory
        if server_root and server_root.is_dir():
            markers = {
                "neoforge": server_root / "libraries" / "net" / "neoforged" / "neoforge",
                "forge": server_root / "libraries" / "net" / "minecraftforge" / "forge",
                "fabric": server_root / "fabric-server-launch.jar",
                "paper": server_root / "paper.jar",
                "vanilla": server_root / "server.jar",
            }
            for name, marker in markers.items():
                if marker.exists():
                    loader = name
                    break

            try:
                neoforge_dir = server_root / "libraries" / "net" / "neoforged" / "neoforge"
                if neoforge_dir.is_dir():
                    versions = [p.name for p in neoforge_dir.iterdir() if p.is_dir()]
                    if versions:
                        latest_ver = sorted(versions)[-1]
                        parts = latest_ver.split(".")
                        if len(parts) >= 2 and parts[0].isdigit():
                            loader = "neoforge"
                            version = f"1.{parts[0]}.{parts[1]}" if parts[0] != "1" else latest_ver

                forge_dir = server_root / "libraries" / "net" / "minecraftforge" / "forge"
                if forge_dir.is_dir():
                    versions = [p.name for p in forge_dir.iterdir() if p.is_dir()]
                    if versions:
                        latest_ver = sorted(versions)[-1]
                        mc_part = latest_ver.split("-")[0]
                        if mc_part.startswith("1."):
                            loader = "forge"
                            version = mc_part
            except Exception:
                pass

        return {"loader": loader, "minecraft_version": version}

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
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
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
    ) -> ModItem:
        self._require_server_stopped("instalar mods")
        version = await self._get_compatible_version(project_id, version_id, loader, game_version)
        file_data = self._select_download_file(version)
        filename = self._validate_filename(str(file_data.get("filename", "")))
        if not filename.endswith(".jar"):
            raise ModrinthServiceError("La versión seleccionada no contiene un archivo .jar válido.")

        await asyncio.to_thread(self.mods_directory.mkdir, parents=True, exist_ok=True)
        destination = self._resolve_mod_path(filename)
        if destination.exists():
            raise ModConflictError("Ese archivo ya está instalado.")

        download_url = file_data.get("url")
        if not isinstance(download_url, str) or not download_url.startswith("https://"):
            raise ModrinthServiceError("Modrinth no entregó una URL de descarga segura.")

        temporary_path = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.downloading")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(90.0), follow_redirects=True) as client:
                async with client.stream("GET", download_url) as response:
                    response.raise_for_status()
                    async with aiofiles.open(temporary_path, "wb") as target_file:
                        async for chunk in response.aiter_bytes(_DOWNLOAD_CHUNK_SIZE):
                            await target_file.write(chunk)
            await asyncio.to_thread(temporary_path.rename, destination)
        except (httpx.HTTPError, OSError) as error:
            logger.warning("Falló la descarga de %s: %s", project_id, error)
            raise ModrinthServiceError("No se pudo descargar el mod desde Modrinth.") from error
        finally:
            if temporary_path.exists():
                await asyncio.to_thread(temporary_path.unlink)

        # Resolución automática de dependencias requeridas
        if install_dependencies:
            if visited_projects is None:
                visited_projects = set()
            visited_projects.add(project_id)

            dependencies = version.get("dependencies")
            if isinstance(dependencies, list):
                for dep in dependencies:
                    if dep.get("dependency_type") == "required" and dep.get("project_id"):
                        dep_proj = dep["project_id"]
                        if dep_proj not in visited_projects:
                            visited_projects.add(dep_proj)
                            try:
                                await self.install_modrinth_mod(
                                    dep_proj,
                                    version_id=dep.get("version_id"),
                                    install_dependencies=True,
                                    visited_projects=visited_projects,
                                )
                                logger.info("Dependencia requerida %s instalada con éxito", dep_proj)
                            except ModConflictError:
                                pass  # Ya existía en disco
                            except Exception as dep_err:
                                logger.warning("No se pudo autoinstalar dependencia requerida %s: %s", dep_proj, dep_err)

        return await asyncio.to_thread(self._mod_item_from_path, destination)

    async def check_updates(self) -> list[ModUpdateItem]:
        """Comprueba de forma asíncrona si hay versiones más nuevas en Modrinth para los mods instalados."""
        installed = await self.list_mods()
        candidates = [m for m in installed if m.is_enabled and (m.mod_id or m.name)]
        if not candidates:
            return []

        env = self.get_environment()
        loader = env["loader"].lower()
        mc_version = env["minecraft_version"].lower()

        query_params: dict[str, Any] = {}
        if loader not in ("all", "any", "vanilla", "custom", ""):
            query_params["loaders"] = json.dumps([loader])
        if mc_version not in ("all", "any", ""):
            query_params["game_versions"] = json.dumps([mc_version])

        results: list[ModUpdateItem] = []
        semaphore = asyncio.Semaphore(5)

        async def _check_single(mod: ModItem) -> ModUpdateItem:
            target_id = mod.mod_id or mod.name
            update_item = ModUpdateItem(
                filename=mod.filename,
                mod_id=mod.mod_id,
                name=mod.name,
                current_version=mod.version,
                latest_version=None,
                project_id=None,
                has_update=False,
            )
            async with semaphore:
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                        resp = await client.get(
                            f"{_MODRINTH_API}/project/{target_id}/version",
                            params=query_params or None,
                        )
                        if resp.status_code == 200:
                            versions = resp.json()
                            if isinstance(versions, list) and versions:
                                latest = max(versions, key=lambda v: v.get("date_published", ""))
                                latest_ver = latest.get("version_number")
                                update_item.latest_version = latest_ver
                                update_item.project_id = latest.get("project_id")
                                if (
                                    mod.version
                                    and latest_ver
                                    and mod.version.strip().casefold() != latest_ver.strip().casefold()
                                ):
                                    update_item.has_update = True
                except Exception as err:
                    logger.debug("Error comprobando actualización para %s: %s", mod.filename, err)
            return update_item

        updates = await asyncio.gather(*[_check_single(m) for m in candidates], return_exceptions=True)
        for item in updates:
            if isinstance(item, ModUpdateItem):
                results.append(item)
        return results

    async def export_client_pack(self) -> Path:
        """Empaqueta mods activos y configuraciones presentes sin bloquear FastAPI."""
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
        env = self.get_environment()
        effective_loader = (loader if loader is not None else env["loader"]).lower()
        effective_version = (game_version if game_version is not None else env["minecraft_version"]).lower()

        loaders_filter = [effective_loader] if effective_loader not in ("all", "any", "vanilla", "custom", "") else []
        versions_filter = [effective_version] if effective_version not in ("all", "any", "") else []

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
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
    def _select_download_file(version: dict[str, Any]) -> dict[str, Any]:
        files = version.get("files", [])
        if not isinstance(files, list) or not files:
            raise ModrinthServiceError("La versión no contiene archivos descargables.")
        return next((item for item in files if item.get("primary") is True), files[0])

    def _build_client_pack_sync(self, destination: Path) -> None:
        with zipfile.ZipFile(destination, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            written_names: set[str] = set()
            for mod_file in self._iter_active_mod_files():
                if self._is_server_only_mod(mod_file):
                    continue
                archive.write(mod_file, arcname=Path("mods") / mod_file.name)
                written_names.add(mod_file.name.lower())
            assert self._settings.server_directory is not None
            client_mods_dir = self._settings.server_directory / "client_only_mods"
            if client_mods_dir.is_dir():
                for client_mod in client_mods_dir.glob("*.jar"):
                    if client_mod.name.lower() not in written_names:
                        archive.write(client_mod, arcname=Path("mods") / client_mod.name)
                        written_names.add(client_mod.name.lower())
            for directory_name in ("config", "defaultconfigs", "pointblank"):
                source_directory = self._settings.server_directory / directory_name
                if source_directory.is_dir():
                    self._add_directory_to_archive(archive, source_directory, Path(directory_name))

    @staticmethod
    def _add_directory_to_archive(archive: zipfile.ZipFile, source: Path, archive_root: Path) -> None:
        server_only_dirs = frozenset({"luckperms", "bluemap", "spark", "chunky", "worldedit", "skinrestorer"})
        for file_path in source.rglob("*"):
            if file_path.is_file():
                rel = file_path.relative_to(source)
                if any(part.lower() in server_only_dirs for part in rel.parts):
                    continue
                archive.write(file_path, arcname=archive_root / rel)

    def _list_mods_sync(self) -> list[ModItem]:
        items = [self._mod_item_from_path(path) for path in self._iter_mod_files()]
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
                    raw_toml = archive.read(toml_candidate).decode("utf-8", errors="replace")
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
                    raw_json = archive.read("fabric.mod.json").decode("utf-8", errors="replace")
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
    def _is_server_only_mod(mod_file: Path, mod_id: str | None = None) -> bool:
        if mod_id and mod_id.casefold() in SERVER_ONLY_MODS:
            return True
        normalized_name = mod_file.name.casefold()
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
            is_server_only=cls._is_server_only_mod(path, mod_id),
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
        if not filename or Path(filename).name != filename:
            raise ModServiceError("El nombre del archivo no es válido.")
        if not (filename.endswith(".jar") or filename.endswith(".jar.disabled")):
            raise ModServiceError("El archivo debe terminar en .jar o .jar.disabled.")
        return filename


mod_service = ModService()
