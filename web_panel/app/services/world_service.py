"""Gestor de mundos de Minecraft en server/."""

from __future__ import annotations

import asyncio
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings, settings
from app.schemas.worlds import WorldCreateRequest, WorldItem
from app.services.server_properties_service import server_properties_service
from app.services.runtime_guard import require_server_stopped
from app.services.server_process import MinecraftServerManager, server_manager


def _format_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024.0:
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{num_bytes} B"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"


def _get_dir_size(path: Path) -> int:
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat().st_size
            elif entry.is_dir(follow_symlinks=False):
                total += _get_dir_size(Path(entry.path))
    except (PermissionError, FileNotFoundError):
        pass
    return total


class WorldService:
    def __init__(
        self,
        configured_settings: Settings = settings,
        manager: MinecraftServerManager = server_manager,
    ) -> None:
        self._settings = configured_settings
        self._manager = manager
        self._lock = asyncio.Lock()

    @property
    def server_dir(self) -> Path:
        assert self._settings.server_directory
        return self._settings.server_directory

    async def list_worlds(self) -> list[WorldItem]:
        return await asyncio.to_thread(self._list_sync)

    def _list_sync(self) -> list[WorldItem]:
        props = server_properties_service.read_properties()
        active_world = props.get("level-name", "world")
        
        worlds: list[WorldItem] = []
        if not self.server_dir.is_dir():
            return []

        for entry in self.server_dir.iterdir():
            if not entry.is_dir():
                continue
            # Verificamos si contiene level.dat o es el mundo activo
            is_world = (entry / "level.dat").is_file() or entry.name == active_world
            if not is_world:
                continue

            size_bytes = _get_dir_size(entry)
            mtime = entry.stat().st_mtime
            has_nether = (entry / "DIM-1").is_dir()
            has_the_end = (entry / "DIM1").is_dir()

            worlds.append(
                WorldItem(
                    name=entry.name,
                    is_active=(entry.name == active_world),
                    size_bytes=size_bytes,
                    size_formatted=_format_size(size_bytes),
                    last_modified=datetime.fromtimestamp(mtime, UTC).strftime("%Y-%m-%d %H:%M:%S"),
                    has_nether=has_nether,
                    has_the_end=has_the_end,
                )
            )

        # Ordenar primero el activo, luego alfabéticamente
        worlds.sort(key=lambda w: (not w.is_active, w.name.lower()))
        return worlds

    async def switch_world(self, world_name: str) -> dict[str, Any]:
        async with self._lock:
            require_server_stopped(self._manager, "cambiar el mundo activo")
            worlds = await self.list_worlds()
            target = next((w for w in worlds if w.name == world_name), None)
            if not target:
                raise ValueError(f"El mundo '{world_name}' no existe en el servidor.")

            await server_properties_service.update_properties({"level-name": world_name})
            return {
                "success": True,
                "message": f"Mundo activo cambiado a '{world_name}'. Si el servidor está encendido, reinicialo para que cargue.",
                "world_name": world_name,
            }

    async def create_world(self, req: WorldCreateRequest) -> dict[str, Any]:
        async with self._lock:
            require_server_stopped(self._manager, "crear mundos")
            name = req.world_name.strip()
            target_path = self.server_dir / name
            if target_path.exists():
                raise ValueError(f"Ya existe una carpeta o mundo con el nombre '{name}'.")

            # Crear directorio base para el mundo
            target_path.mkdir(parents=True, exist_ok=True)

            # Actualizar server.properties para que al iniciar cree el mundo con estas propiedades
            updates: dict[str, str] = {
                "level-name": name,
                "gamemode": req.gamemode,
                "difficulty": req.difficulty,
                "generate-structures": "true" if req.generate_structures else "false",
                "hardcore": "true" if req.hardcore else "false",
            }
            if req.seed:
                updates["level-seed"] = req.seed.strip()

            await server_properties_service.update_properties(updates)
            return {
                "success": True,
                "message": f"Mundo '{name}' preparado y activado. Al iniciar el servidor, se generará el terreno automáticamente.",
                "world_name": name,
            }

    async def delete_world(self, world_name: str) -> dict[str, Any]:
        async with self._lock:
            require_server_stopped(self._manager, "eliminar mundos")
            props = server_properties_service.read_properties()
            active_world = props.get("level-name", "world")
            if world_name == active_world:
                raise ValueError("No se puede eliminar el mundo que está actualmente activo. Cambiá a otro mundo primero.")

            target_path = (self.server_dir / world_name).resolve()
            if not target_path.is_relative_to(self.server_dir.resolve()):
                raise ValueError("Ruta de mundo inválida.")

            if not target_path.is_dir():
                raise ValueError(f"El mundo '{world_name}' no existe.")

            await asyncio.to_thread(shutil.rmtree, target_path)
            return {
                "success": True,
                "message": f"Mundo '{world_name}' eliminado correctamente.",
            }


world_service = WorldService()
