"""Creación, listado y restauración segura de copias del mundo."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings, settings
from app.schemas.backup import BackupAuditItem, BackupAuditResponse, BackupItem, BackupSafetyItem, BackupSafetyOverview
from app.services.discord_service import DiscordService, discord_service
from app.services.server_process import MinecraftServerManager, ServerProcessError, server_manager
from app.services.runtime_guard import ServerActiveError, require_server_stopped

_MEBIBYTE = 1024 * 1024
_GIBIBYTE = 1024 * 1024 * 1024
_TEMPORARY_BACKUP_MAX_AGE_SECONDS = 48 * 60 * 60


class BackupServiceError(RuntimeError):
    status_code = 400


class BackupNotFoundError(BackupServiceError):
    status_code = 404


class BackupConflictError(BackupServiceError):
    status_code = 409


class BackupService:
    def __init__(
        self,
        configured_settings: Settings = settings,
        manager: MinecraftServerManager = server_manager,
        discord: DiscordService = discord_service,
    ) -> None:
        self._settings = configured_settings
        self._manager = manager
        self._discord = discord
        self._operation_lock = asyncio.Lock()

    @property
    def backups_directory(self) -> Path:
        assert self._settings.backups_directory is not None
        return self._settings.backups_directory

    @property
    def world_directory(self) -> Path:
        from app.services.server_properties_service import server_properties_service
        props = server_properties_service.read_properties()
        active_world = props.get("level-name", "world")
        if self._settings.server_directory:
            target = self._settings.server_directory / active_world
            if target.is_dir():
                return target
        return self._settings.world_directory or (self._settings.server_directory / "world" if self._settings.server_directory else Path("world"))

    async def create_backup(self) -> BackupItem:
        if not self.world_directory.is_dir():
            raise BackupNotFoundError("No existe el mundo para respaldar.")
        async with self._operation_lock:
            await asyncio.to_thread(self.backups_directory.mkdir, parents=True, exist_ok=True)
            backup_path = self.backups_directory / f"backup_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.zip"
            if backup_path.exists():
                raise BackupServiceError("Ya existe un backup con ese timestamp; intentá nuevamente.")
            temporary_path = backup_path.with_name(f".{backup_path.name}.{uuid.uuid4().hex}.part")
            saves_paused = False
            try:
                if self._manager.is_running:
                    await self._manager.send_command_and_wait_for_log("save-all flush", "Saved the game")
                    await self._manager.send_command("save-off")
                    saves_paused = True
                    # El comando anterior se procesa en el hilo principal del servidor.
                    await asyncio.sleep(0.2)
                await asyncio.to_thread(self._create_archive_sync, temporary_path)
                verification_error = await asyncio.to_thread(self._verify_archive_sync, temporary_path)
                if verification_error:
                    raise BackupServiceError(f"El backup creado no pasó la verificación de integridad: {verification_error}")
                await asyncio.to_thread(temporary_path.replace, backup_path)
            except (OSError, ServerProcessError) as error:
                raise BackupServiceError(f"No se pudo crear el backup: {error}") from error
            finally:
                if temporary_path.exists():
                    await asyncio.to_thread(temporary_path.unlink)
                if saves_paused and self._manager.is_running:
                    with contextlib.suppress(ServerProcessError):
                        await self._manager.send_command("save-on")
                        await self._manager.send_command_and_wait_for_log("save-all flush", "Saved the game")

        backup = await asyncio.to_thread(self._backup_item_from_path, backup_path)
        await self._discord.send_backup_created(backup)
        return backup

    async def list_backups(self) -> list[BackupItem]:
        return await asyncio.to_thread(self._list_backups_sync)

    async def safety_overview(self) -> BackupSafetyOverview:
        """Inspecciona archivos existentes sin crear, borrar o restaurar nada."""
        return await asyncio.to_thread(self._safety_overview_sync)

    async def audit_and_purge_backups(self) -> BackupAuditResponse:
        """Comprueba CRCs y purga sólo copias válidas que excedan la política."""
        async with self._operation_lock:
            return await asyncio.to_thread(self._audit_and_purge_sync)

    async def delete_backup(self, filename: str) -> None:
        backup_path = self.get_backup_path(filename)
        if not backup_path.is_file():
            raise BackupNotFoundError("No existe el backup indicado.")
        async with self._operation_lock:
            try:
                await asyncio.to_thread(backup_path.unlink)
            except OSError as error:
                raise BackupServiceError(f"No se pudo eliminar el backup: {error}") from error

    async def restore_backup(self, filename: str) -> BackupItem:
        try:
            require_server_stopped(self._manager, "restaurar un backup")
        except ServerActiveError as error:
            raise BackupConflictError(str(error)) from error

        backup_path = self.get_backup_path(filename)
        if not backup_path.is_file():
            raise BackupNotFoundError("No existe el backup indicado.")

        async with self._operation_lock:
            try:
                await asyncio.to_thread(self._restore_archive_sync, backup_path)
            except (OSError, zipfile.BadZipFile) as error:
                raise BackupServiceError(f"No se pudo restaurar el backup: {error}") from error
        return await asyncio.to_thread(self._backup_item_from_path, backup_path)

    def _create_archive_sync(self, backup_path: Path) -> None:
        with zipfile.ZipFile(backup_path, mode="x", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in self.world_directory.rglob("*"):
                if path.is_file():
                    archive.write(path, arcname=Path("world") / path.relative_to(self.world_directory))

    def _restore_archive_sync(self, backup_path: Path) -> None:
        assert self._settings.server_directory is not None
        staging_root = self._settings.server_directory / f".world-restore-{uuid.uuid4().hex}"
        staged_world = staging_root / "world"
        previous_world = self._settings.server_directory / f".world-before-restore-{uuid.uuid4().hex}"
        try:
            staging_root.mkdir(parents=False, exist_ok=False)
            with zipfile.ZipFile(backup_path) as archive:
                self._extract_world_safely(archive, staging_root)
            if not staged_world.is_dir():
                raise BackupServiceError("El backup no contiene una carpeta world válida.")

            if self.world_directory.exists():
                self.world_directory.rename(previous_world)
            try:
                staged_world.rename(self.world_directory)
            except OSError:
                if previous_world.exists() and not self.world_directory.exists():
                    previous_world.rename(self.world_directory)
                raise
            if previous_world.exists():
                shutil.rmtree(previous_world)
        finally:
            if staging_root.exists():
                shutil.rmtree(staging_root)

    @staticmethod
    def _extract_world_safely(archive: zipfile.ZipFile, target_directory: Path) -> None:
        for member in archive.infolist():
            member_path = Path(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts or not member_path.parts:
                raise BackupServiceError("El backup contiene una ruta inválida.")
            if member_path.parts[0] != "world":
                raise BackupServiceError("El backup contiene archivos fuera de world/.")
            destination = (target_directory / member_path).resolve()
            if not destination.is_relative_to(target_directory.resolve()):
                raise BackupServiceError("El backup contiene una ruta inválida.")
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)

    def _list_backups_sync(self) -> list[BackupItem]:
        return sorted(
            (self._backup_item_from_path(path) for path in self._backup_paths_sync()),
            key=lambda item: item.created_at,
            reverse=True,
        )

    def _safety_overview_sync(self) -> BackupSafetyOverview:
        items: list[BackupSafetyItem] = []
        server_running = self._manager.is_running
        for path in self._backup_paths_sync():
            error = self._verify_archive_sync(path)
            verified = error is None
            if not verified:
                integrity_message = f"No se debe restaurar: la verificación falló ({error})."
            else:
                integrity_message = "Verificación ZIP correcta. Esto no reemplaza una restauración de prueba."

            if server_running:
                restore_ready = False
                restore_message = "El servidor está encendido. Apagalo antes de preparar una restauración."
            elif not verified:
                restore_ready = False
                restore_message = "La copia no pasó integridad y está bloqueada para restaurar."
            else:
                restore_ready = True
                restore_message = "Lista para una confirmación explícita. Restaurar reemplaza el mundo actual."

            items.append(
                BackupSafetyItem(
                    **self._backup_item_from_path(path).model_dump(),
                    provenance=self._backup_provenance(path),
                    integrity="verified" if verified else "corrupt",
                    integrity_message=integrity_message,
                    restore_ready=restore_ready,
                    restore_message=restore_message,
                )
            )
        items.sort(key=lambda item: item.created_at, reverse=True)
        verified_backups = sum(item.integrity == "verified" for item in items)
        return BackupSafetyOverview(
            backups=items,
            total_backups=len(items),
            verified_backups=verified_backups,
            corrupted_backups=len(items) - verified_backups,
            server_running=server_running,
            restore_warning=(
                "Restaurar reemplaza el mundo actual. El panel nunca debe hacerlo sin una confirmación explícita."
            ),
            retention_count=self._settings.backup_retention_count,
            max_disk_gb=self._settings.backup_max_disk_gb,
        )

    def _backup_provenance(self, path: Path) -> Literal["panel", "simplebackups", "external"]:
        """Clasifica sólo por ubicación conocida, sin asumir quién creó un ZIP externo."""
        try:
            path.resolve().relative_to(self.backups_directory.resolve())
            return "panel"
        except ValueError:
            pass
        if self._settings.server_directory:
            simplebackups = self._settings.server_directory / "simplebackups"
            try:
                path.resolve().relative_to(simplebackups.resolve())
                return "simplebackups"
            except ValueError:
                pass
        return "external"

    def _backup_paths_sync(self) -> list[Path]:
        paths: list[Path] = []
        for directory in self._backup_directories():
            if directory.is_dir():
                paths.extend(path for path in directory.rglob("*.zip") if path.is_file())
        return paths

    def _backup_directories(self) -> list[Path]:
        directories = [self.backups_directory]
        if self._settings.server_directory:
            directories.append(self._settings.server_directory / "simplebackups")
        return directories

    @staticmethod
    def _verify_archive_sync(path: Path) -> str | None:
        try:
            if path.stat().st_size == 0:
                return "el archivo está vacío"
            with zipfile.ZipFile(path) as archive:
                if not archive.infolist():
                    return "el ZIP no contiene archivos"
                invalid_member = archive.testzip()
                if invalid_member is not None:
                    return f"falló el CRC de {invalid_member}"
        except (OSError, RuntimeError, zipfile.BadZipFile) as error:
            return str(error)
        return None

    def _audit_and_purge_sync(self) -> BackupAuditResponse:
        checked: list[BackupAuditItem] = []
        valid_paths: list[Path] = []
        corrupt_paths: list[Path] = []
        for path in self._backup_paths_sync():
            error = self._verify_archive_sync(path)
            checked.append(BackupAuditItem(**self._backup_item_from_path(path).model_dump(), healthy=error is None, error=error))
            (valid_paths if error is None else corrupt_paths).append(path)

        valid_paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        kept = valid_paths[:self._settings.backup_retention_count]
        purge_candidates = valid_paths[self._settings.backup_retention_count:]
        total_bytes = sum(path.stat().st_size for path in kept)
        max_bytes = self._settings.backup_max_disk_gb * _GIBIBYTE
        while total_bytes > max_bytes and kept:
            path = kept.pop()
            total_bytes -= path.stat().st_size
            purge_candidates.append(path)

        deleted: list[str] = []
        for path in purge_candidates:
            path.unlink()
            deleted.append(str(path))
        return BackupAuditResponse(
            checked=checked,
            deleted=deleted,
            skipped_corrupt=[str(path) for path in corrupt_paths],
            deleted_temporary=self._delete_stale_temporary_archives_sync(),
        )

    def _delete_stale_temporary_archives_sync(self) -> list[str]:
        cutoff = datetime.now(UTC).timestamp() - _TEMPORARY_BACKUP_MAX_AGE_SECONDS
        deleted: list[str] = []
        for directory in self._backup_directories():
            if not directory.is_dir():
                continue
            for path in directory.rglob("*.tmp"):
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    deleted.append(str(path))
        return deleted

    @staticmethod
    def _backup_item_from_path(path: Path) -> BackupItem:
        return BackupItem(
            filename=path.name,
            size_mb=round(path.stat().st_size / _MEBIBYTE, 2),
            created_at=datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
        )

    def get_backup_path(self, filename: str) -> Path:
        if not filename or Path(filename).name != filename or not filename.endswith(".zip"):
            raise BackupServiceError("El nombre del backup no es válido.")
        candidate = self.backups_directory / filename
        for directory in self._backup_directories():
            if not directory.is_dir():
                continue
            direct = (directory / filename).resolve()
            if direct.is_file() and direct.is_relative_to(directory.resolve()):
                return direct
            matches = [path for path in directory.rglob(filename) if path.is_file()]
            if len(matches) == 1:
                return matches[0]
        return candidate


backup_service = BackupService()
