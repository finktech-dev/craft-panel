"""Gestor de Whitelist (Lista blanca) con avatares e interacción en vivo."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings, settings
from app.services.server_process import MinecraftServerManager, ServerProcessError, server_manager
from app.services.server_properties_service import server_properties_service

_MOJANG_PROFILE_URL = "https://api.mojang.com/users/profiles/minecraft/{name}"


def offline_uuid(name: str) -> str:
    """Minecraft's offline-mode UUID: Java's UUID.nameUUIDFromBytes("OfflinePlayer:" + name).

    It is a version-3 UUID of the raw MD5, with no namespace (uuid.uuid3 would add one).
    """
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{name}".encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


class WhitelistPlayer:
    def __init__(self, name: str, player_uuid: str | None = None) -> None:
        self.name = name
        self.uuid = player_uuid or offline_uuid(name)
        self.avatar_url = f"https://mc-heads.net/avatar/{name}/64"

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "uuid": self.uuid,
            "avatar_url": self.avatar_url,
        }


class WhitelistServiceError(RuntimeError):
    status_code = 409


class WhitelistService:
    def __init__(
        self,
        configured_settings: Settings = settings,
        manager: MinecraftServerManager = server_manager,
    ) -> None:
        self._settings = configured_settings
        self._manager = manager
        self._lock = asyncio.Lock()

    @property
    def file_path(self) -> Path:
        assert self._settings.server_directory
        return self._settings.server_directory / "whitelist.json"

    def is_enabled(self) -> bool:
        props = server_properties_service.read_properties()
        return props.get("white-list", "false").lower() == "true"

    def _read_file(self) -> list[dict[str, Any]]:
        if not self.file_path.is_file():
            return []
        try:
            return json.loads(self.file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

    def _cached_uuid(self, name: str) -> str | None:
        """UUID the server itself recorded when this player joined (usercache.json)."""
        assert self._settings.server_directory
        try:
            entries = json.loads((self._settings.server_directory / "usercache.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if isinstance(entry, dict) and str(entry.get("name", "")).lower() == name.lower() and entry.get("uuid"):
                return str(entry["uuid"])
        return None

    async def _mojang_uuid(self, name: str) -> tuple[str, str]:
        """Official account UUID and exact name, required when online-mode is on."""
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
                response = await client.get(_MOJANG_PROFILE_URL.format(name=name))
        except httpx.HTTPError as error:
            raise WhitelistServiceError(
                "No pudimos comprobar ese nombre con Minecraft. Revisá la conexión a Internet e intentá de nuevo."
            ) from error
        if response.status_code in {204, 404}:
            raise ValueError(f"No existe una cuenta de Minecraft con el nombre {name}.")
        if response.status_code != 200:
            raise WhitelistServiceError("Minecraft no respondió al comprobar el nombre. Probá de nuevo en un rato.")
        data = response.json()
        raw = str(data.get("id", ""))
        if len(raw) != 32:
            raise WhitelistServiceError("Minecraft devolvió una respuesta inesperada al comprobar el nombre.")
        return str(uuid.UUID(raw)), str(data.get("name") or name)

    async def resolve_player(self, name: str) -> WhitelistPlayer:
        """Pick the UUID the server will actually check for this player."""
        cached = await asyncio.to_thread(self._cached_uuid, name)
        if cached:
            return WhitelistPlayer(name, cached)
        properties = server_properties_service.read_properties()
        if properties.get("online-mode", "true").lower() == "true":
            player_uuid, exact_name = await self._mojang_uuid(name)
            return WhitelistPlayer(exact_name, player_uuid)
        return WhitelistPlayer(name)

    def _write_file(self, data: list[dict[str, Any]]) -> None:
        temporary = self.file_path.with_name(f".{self.file_path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.file_path)

    async def _confirm_live_command(self, command: str, confirmation: str) -> None:
        """Do not claim a live whitelist change unless Java confirms it."""
        try:
            await self._manager.send_command_and_wait_for_log(command, confirmation)
        except ServerProcessError as error:
            raise WhitelistServiceError(
                "Minecraft no confirmó el cambio de whitelist; no se modificó el archivo local. "
                "Revisá la consola e intentá nuevamente."
            ) from error

    async def get_status(self) -> dict[str, Any]:
        enabled = await asyncio.to_thread(self.is_enabled)
        raw_list = await asyncio.to_thread(self._read_file)
        
        players = []
        for item in raw_list:
            name = item.get("name", "")
            if name:
                p = WhitelistPlayer(name, item.get("uuid"))
                players.append(p.to_dict())

        players.sort(key=lambda p: p["name"].lower())
        return {
            "enabled": enabled,
            "total": len(players),
            "players": players,
        }

    async def toggle(self, enabled: bool) -> dict[str, Any]:
        async with self._lock:
            val_str = "true" if enabled else "false"
            if self._manager.is_running:
                command = f"/whitelist {'on' if enabled else 'off'}"
                confirmation = f"Whitelist is now turned {'on' if enabled else 'off'}"
                await self._confirm_live_command(command, confirmation)
                return {
                    "success": True,
                    "enabled": enabled,
                    "message": f"Lista blanca {'activada' if enabled else 'desactivada'} en el servidor activo.",
                }

            await server_properties_service.update_properties({"white-list": val_str})
            return {
                "success": True,
                "enabled": enabled,
                "message": f"Lista blanca {'activada' if enabled else 'desactivada'}.",
            }

    async def add_player(self, username: str) -> dict[str, Any]:
        async with self._lock:
            cleaned = username.strip()
            if not cleaned:
                raise ValueError("Nombre de usuario inválido.")

            current = await asyncio.to_thread(self._read_file)
            if any(item.get("name", "").lower() == cleaned.lower() for item in current):
                return {"success": True, "message": f"{cleaned} ya está en la lista blanca."}

            # Enviar comando si el servidor está en ejecución
            if self._manager.is_running:
                await self._confirm_live_command(
                    f"/whitelist add {cleaned}",
                    f"Added {cleaned} to the whitelist",
                )
                return {
                    "success": True,
                    "message": f"Jugador {cleaned} agregado a la lista blanca en el servidor activo.",
                    "player": WhitelistPlayer(cleaned).to_dict(),
                }

            p = await self.resolve_player(cleaned)
            current.append({"name": p.name, "uuid": p.uuid})
            await asyncio.to_thread(self._write_file, current)

            return {
                "success": True,
                "message": f"Jugador {cleaned} agregado a la lista blanca.",
                "player": p.to_dict(),
            }

    async def remove_player(self, username: str) -> dict[str, Any]:
        async with self._lock:
            cleaned = username.strip()
            current = await asyncio.to_thread(self._read_file)
            updated = [item for item in current if item.get("name", "").lower() != cleaned.lower()]

            if self._manager.is_running:
                await self._confirm_live_command(
                    f"/whitelist remove {cleaned}",
                    f"Removed {cleaned} from the whitelist",
                )
                return {
                    "success": True,
                    "message": f"Jugador {cleaned} eliminado de la lista blanca en el servidor activo.",
                }

            await asyncio.to_thread(self._write_file, updated)
            return {
                "success": True,
                "message": f"Jugador {cleaned} eliminado de la lista blanca.",
            }


whitelist_service = WhitelistService()
