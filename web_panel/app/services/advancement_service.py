"""Servicio para inspección, reinicio y gestión de logros (advancements) de jugadores en cualquier mundo."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings, settings
from app.services.server_process import server_manager
from app.services.server_properties_service import server_properties_service


def _friendly_name(adv_id: str) -> str:
    """Genera un nombre legible a partir del ID de un logro."""
    clean = adv_id.split(":")[-1]
    last_part = clean.split("/")[-1]
    return " ".join(word.capitalize() for word in last_part.replace("_", " ").split())


def _categorize(adv_id: str) -> str:
    """Clasifica el logro según el mod o la rama de Minecraft."""
    if adv_id.startswith("minecraft:recipes/"):
        return "Recetas de crafteo"
    if adv_id.startswith("minecraft:story/"):
        return "Historia principal (Vanilla)"
    if adv_id.startswith("minecraft:nether/"):
        return "El Nether"
    if adv_id.startswith("minecraft:end/"):
        return "The End"
    if adv_id.startswith("minecraft:adventure/"):
        return "Aventura y Exploración"
    if adv_id.startswith("minecraft:husbandry/"):
        return "Agricultura y Animales"

    namespace = adv_id.split(":")[0].replace("_", " ").title()
    return f"Mod: {namespace}"


class AdvancementService:
    def __init__(self, configured_settings: Settings = settings) -> None:
        self._settings = configured_settings
        self._lock = asyncio.Lock()

    @property
    def server_dir(self) -> Path:
        assert self._settings.server_directory
        return self._settings.server_directory

    def _resolve_world_dir(self, world_name: str | None = None) -> tuple[Path, bool]:
        props = server_properties_service.read_properties()
        active_world = props.get("level-name", "world")
        
        target_name = (world_name.strip() if world_name else "") or active_world
        world_dir = self.server_dir / target_name
        if not world_dir.is_dir():
            world_dir = self.server_dir / active_world
            target_name = active_world

        is_active = (target_name == active_world)
        return world_dir, is_active

    async def list_worlds(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_worlds_sync)

    def _list_worlds_sync(self) -> list[dict[str, Any]]:
        props = server_properties_service.read_properties()
        active_world = props.get("level-name", "world")

        result = []
        if not self.server_dir.is_dir():
            return []

        for entry in self.server_dir.iterdir():
            if not entry.is_dir():
                continue
            is_world = (entry / "level.dat").is_file() or (entry / "advancements").is_dir()
            if not is_world:
                continue

            adv_count = 0
            adv_dir = entry / "advancements"
            if adv_dir.is_dir():
                adv_count = len(list(adv_dir.glob("*.json")))

            result.append({
                "name": entry.name,
                "is_active": (entry.name == active_world),
                "players_with_advancements": adv_count,
            })

        result.sort(key=lambda w: (not w["is_active"], w["name"].lower()))
        return result

    def _get_uuid_map(self) -> dict[str, str]:
        """Obtiene el mapa de username -> uuid a partir de usercache.json y ops.json."""
        user_to_uuid: dict[str, str] = {}
        cache_file = self.server_dir / "usercache.json"
        if cache_file.is_file():
            try:
                for entry in json.loads(cache_file.read_text(encoding="utf-8")):
                    name = entry.get("name")
                    uid = entry.get("uuid")
                    if name and uid:
                        user_to_uuid[name.lower()] = uid
            except Exception:
                pass

        ops_file = self.server_dir / "ops.json"
        if ops_file.is_file():
            try:
                for entry in json.loads(ops_file.read_text(encoding="utf-8")):
                    name = entry.get("name")
                    uid = entry.get("uuid")
                    if name and uid:
                        user_to_uuid[name.lower()] = uid
            except Exception:
                pass

        return user_to_uuid

    def _get_name_for_uuid(self, target_uuid: str) -> str:
        uuid_map = self._get_uuid_map()
        for name, uid in uuid_map.items():
            if uid.lower() == target_uuid.lower():
                return name
        return target_uuid[:8]

    async def list_players(self, world_name: str | None = None) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_players_sync, world_name)

    def _list_players_sync(self, world_name: str | None = None) -> list[dict[str, Any]]:
        world_dir, is_active = self._resolve_world_dir(world_name)
        adv_dir = world_dir / "advancements"
        uuid_map = self._get_uuid_map()

        players: list[dict[str, Any]] = []
        known_uuids = set()

        if adv_dir.is_dir():
            for f in adv_dir.glob("*.json"):
                uid = f.stem
                known_uuids.add(uid.lower())
                name = self._get_name_for_uuid(uid)
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    completed_count = sum(1 for k, v in data.items() if isinstance(v, dict) and v.get("done") and not k.startswith("minecraft:recipes/"))
                except Exception:
                    completed_count = 0

                players.append({
                    "username": name,
                    "uuid": uid,
                    "avatar_url": f"https://mc-heads.net/avatar/{name}/64",
                    "advancements_count": completed_count,
                    "has_file": True,
                    "world_name": world_dir.name,
                    "is_active_world": is_active,
                })

        for name, uid in uuid_map.items():
            if uid.lower() not in known_uuids:
                players.append({
                    "username": name,
                    "uuid": uid,
                    "avatar_url": f"https://mc-heads.net/avatar/{name}/64",
                    "advancements_count": 0,
                    "has_file": False,
                    "world_name": world_dir.name,
                    "is_active_world": is_active,
                })

        players.sort(key=lambda p: (not p["has_file"], p["username"].lower()))
        return players

    async def get_player_advancements(self, username: str, world_name: str | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_player_advancements_sync, username, world_name)

    def _get_player_advancements_sync(self, username: str, world_name: str | None = None) -> dict[str, Any]:
        uuid_map = self._get_uuid_map()
        clean_user = username.strip().lower()
        player_uuid = uuid_map.get(clean_user)
        if not player_uuid:
            player_uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, f"OfflinePlayer:{username}"))

        world_dir, is_active = self._resolve_world_dir(world_name)
        adv_file = world_dir / "advancements" / f"{player_uuid}.json"

        advancements = []
        recipes_count = 0

        if adv_file.is_file():
            try:
                data = json.loads(adv_file.read_text(encoding="utf-8"))
                for adv_id, val in data.items():
                    if adv_id == "DataVersion" or not isinstance(val, dict):
                        continue

                    is_done = val.get("done", False)
                    if not is_done:
                        continue

                    if adv_id.startswith("minecraft:recipes/"):
                        recipes_count += 1
                        continue

                    criteria = val.get("criteria", {})
                    ts = next(iter(criteria.values()), "Desconocido") if criteria else "Desconocido"

                    advancements.append({
                        "id": adv_id,
                        "title": _friendly_name(adv_id),
                        "category": _categorize(adv_id),
                        "unlocked_at": ts,
                    })
            except Exception:
                pass

        advancements.sort(key=lambda a: (a["category"], a["title"]))

        return {
            "username": username,
            "uuid": player_uuid,
            "avatar_url": f"https://mc-heads.net/avatar/{username}/64",
            "total_advancements": len(advancements),
            "total_recipes": recipes_count,
            "world_name": world_dir.name,
            "is_active_world": is_active,
            "advancements": advancements,
        }

    async def revoke_advancement(self, username: str, adv_id: str, world_name: str | None = None) -> dict[str, Any]:
        clean_user = username.strip()
        clean_id = adv_id.strip()
        world_dir, is_active = self._resolve_world_dir(world_name)

        # Si es el mundo activo Y el servidor está encendido, enviamos comando en vivo
        if is_active and server_manager.is_running:
            if clean_id.lower() == "everything":
                cmd = f"/advancement revoke {clean_user} everything"
            elif clean_id.startswith("recipes:"):
                cmd = f"/advancement revoke {clean_user} from minecraft:recipes/root"
            else:
                cmd = f"/advancement revoke {clean_user} only {clean_id}"
            await server_manager.send_command(cmd)
            return {
                "success": True,
                "command": cmd,
                "message": f"Se envió el comando '{cmd}' a la consola del servidor.",
            }

        # Si es un mundo inactivo O el servidor está apagado, modificamos directamente el archivo JSON
        async with self._lock:
            uuid_map = await asyncio.to_thread(self._get_uuid_map)
            player_uuid = uuid_map.get(clean_user.lower())
            if not player_uuid:
                player_uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, f"OfflinePlayer:{clean_user}"))

            adv_file = world_dir / "advancements" / f"{player_uuid}.json"
            if not adv_file.is_file():
                return {"success": True, "message": f"El jugador {clean_user} no tiene archivo de logros en el mundo '{world_dir.name}'."}

            try:
                data = json.loads(adv_file.read_text(encoding="utf-8"))
                if clean_id.lower() == "everything":
                    data = {"DataVersion": data.get("DataVersion", 3955)}
                    msg = f"Se reiniciaron todos los logros de {clean_user} en el mundo '{world_dir.name}'."
                elif clean_id == "minecraft:recipes/root" or clean_id.startswith("recipes:"):
                    # Eliminar solo recetas
                    keys_to_remove = [k for k in data if k.startswith("minecraft:recipes/")]
                    for k in keys_to_remove:
                        del data[k]
                    msg = f"Se reiniciaron las {len(keys_to_remove)} recetas de {clean_user} en el mundo '{world_dir.name}'."
                else:
                    if clean_id in data:
                        del data[clean_id]
                        msg = f"Se eliminó el logro '{clean_id}' de {clean_user} en el mundo '{world_dir.name}'."
                    else:
                        msg = f"El jugador {clean_user} no tenía el logro '{clean_id}' en '{world_dir.name}'."

                adv_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                return {"success": True, "message": msg}
            except Exception as e:
                raise RuntimeError(f"Error al editar el archivo de logros: {e}") from e

    async def grant_advancement(self, username: str, adv_id: str, world_name: str | None = None) -> dict[str, Any]:
        clean_user = username.strip()
        clean_id = adv_id.strip()
        world_dir, is_active = self._resolve_world_dir(world_name)

        if is_active and server_manager.is_running:
            if clean_id.lower() == "everything":
                cmd = f"/advancement grant {clean_user} everything"
            else:
                cmd = f"/advancement grant {clean_user} only {clean_id}"
            await server_manager.send_command(cmd)
            return {
                "success": True,
                "command": cmd,
                "message": f"Comando '{cmd}' ejecutado en el servidor.",
            }

        # Si el mundo no está activo o el server está apagado, agregamos el logro en el archivo JSON
        async with self._lock:
            uuid_map = await asyncio.to_thread(self._get_uuid_map)
            player_uuid = uuid_map.get(clean_user.lower())
            if not player_uuid:
                player_uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, f"OfflinePlayer:{clean_user}"))

            adv_file = world_dir / "advancements" / f"{player_uuid}.json"
            adv_file.parent.mkdir(parents=True, exist_ok=True)

            data = {}
            if adv_file.is_file():
                try:
                    data = json.loads(adv_file.read_text(encoding="utf-8"))
                except Exception:
                    data = {}

            now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S +0000")
            data[clean_id] = {
                "criteria": {"manual_grant": now_str},
                "done": True
            }
            adv_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return {
                "success": True,
                "message": f"Logro '{clean_id}' otorgado a {clean_user} en el archivo del mundo '{world_dir.name}'.",
            }


advancement_service = AdvancementService()
