"""Servicio de marcadores de coordenadas y teletransporte rápido."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from app.core.config import Settings, settings
from app.schemas.waypoints import Waypoint, WaypointCreate
from app.services.server_process import server_manager


class WaypointService:
    def __init__(self, configured_settings: Settings = settings) -> None:
        self._settings = configured_settings
        self._storage_file = Path(self._settings.panel_directory or ".") / ".waypoints.json"
        self._lock = asyncio.Lock()
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        if not self._storage_file.is_file():
            defaults = [
                {
                    "id": "spawn",
                    "name": "Punto de Spawn",
                    "x": 0.0,
                    "y": 100.0,
                    "z": 0.0,
                    "dimension": "minecraft:overworld",
                    "description": "Punto central de aparición del mundo.",
                    "icon": "compass",
                },
                {
                    "id": "coliseo",
                    "name": "Coliseo Romano",
                    "x": 885.0,
                    "y": 87.0,
                    "z": 156.0,
                    "dimension": "minecraft:overworld",
                    "description": "Gran arena de combate romana copiada con WorldEdit.",
                    "icon": "shield",
                },
            ]
            self._storage_file.write_text(json.dumps(defaults, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load(self) -> list[Waypoint]:
        if not self._storage_file.is_file():
            return []
        try:
            data = json.loads(self._storage_file.read_text(encoding="utf-8"))
            return [Waypoint(**item) for item in data]
        except Exception:
            return []

    def _save(self, waypoints: list[Waypoint]) -> None:
        raw = [w.model_dump() for w in waypoints]
        self._storage_file.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

    async def list_waypoints(self) -> list[Waypoint]:
        return await asyncio.to_thread(self._load)

    async def add_waypoint(self, req: WaypointCreate) -> Waypoint:
        async with self._lock:
            wps = await asyncio.to_thread(self._load)
            new_id = str(uuid.uuid4())[:8]
            wp = Waypoint(
                id=new_id,
                name=req.name.strip(),
                x=req.x,
                y=req.y,
                z=req.z,
                dimension=req.dimension,
                description=req.description.strip(),
                icon=req.icon or "map-pin",
            )
            wps.append(wp)
            await asyncio.to_thread(self._save, wps)
            return wp

    async def delete_waypoint(self, waypoint_id: str) -> bool:
        async with self._lock:
            wps = await asyncio.to_thread(self._load)
            initial_count = len(wps)
            filtered = [w for w in wps if w.id != waypoint_id]
            if len(filtered) < initial_count:
                await asyncio.to_thread(self._save, filtered)
                return True
            return False

    async def teleport(self, waypoint_id: str, target: str = "@a") -> dict[str, Any]:
        wps = await self.list_waypoints()
        wp = next((w for w in wps if w.id == waypoint_id), None)
        if not wp:
            raise ValueError(f"No existe el marcador con ID '{waypoint_id}'.")

        target_cleaned = target.strip()
        if not target_cleaned:
            target_cleaned = "@a"

        cmd = f"/execute in {wp.dimension} run tp {target_cleaned} {wp.x:.1f} {wp.y:.1f} {wp.z:.1f}"
        if not server_manager.is_running:
            return {
                "success": False,
                "command": cmd,
                "message": f"Servidor apagado. El comando para cuando esté activo es: {cmd}",
            }

        await server_manager.send_command(cmd)
        return {
            "success": True,
            "command": cmd,
            "message": f"Teletransportando {target_cleaned} hacia '{wp.name}' ({wp.x:.1f}, {wp.y:.1f}, {wp.z:.1f}).",
        }


waypoint_service = WaypointService()
