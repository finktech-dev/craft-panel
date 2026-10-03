"""Read-only registry discovery plus live player and gamerule commands."""

from __future__ import annotations

import asyncio
import json
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.core.config import settings
from app.core.security import get_current_admin
from app.schemas.universal import Gamerule, PlayerAction, PlayerItem, RegistryItem
from app.services.server_process import ServerProcessError, server_manager

router = APIRouter(tags=["registry-players"], dependencies=[Depends(get_current_admin)])

_registry_cache: list[RegistryItem] | None = None
_registry_mtime: float = 0
_icon_cache: dict[str, bytes] = {}
_gamerules = {"keepInventory": "false", "naturalRegeneration": "true", "mobGriefing": "true", "doFireTick": "true", "doDaylightCycle": "true", "doWeatherCycle": "true", "randomTickSpeed": "3", "maxEntityCramming": "24"}


@router.get("/registry/items", response_model=list[RegistryItem])
async def registry_items(mod: str | None = None, search: str = "", limit: int = Query(100, ge=1, le=500)):
    return await asyncio.to_thread(_items, mod, search.lower(), limit)


@router.get("/registry/icon/{item_id:path}")
async def registry_item_icon(item_id: str):
    if ":" not in item_id:
        raise HTTPException(400, "ID de ítem inválido.")
    mod_id, item_name = item_id.split(":", 1)
    icon_bytes = await asyncio.to_thread(_find_item_icon, mod_id, item_name)
    if not icon_bytes:
        raise HTTPException(404, "Ícono no encontrado.")
    return Response(content=icon_bytes, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


def _find_item_icon(mod_id: str, item_name: str) -> bytes | None:
    cache_key = f"{mod_id}:{item_name}"
    if cache_key in _icon_cache:
        return _icon_cache[cache_key]
    assert settings.mods_directory
    if not settings.mods_directory.is_dir():
        return None
    clean_item = item_name.replace("/", "_")
    candidates = tuple(f"assets/{mod_id}/textures/{kind}/{clean_item}{suffix}" for kind in ("item", "items", "gui", "block") for suffix in (".icon.png", ".png"))
    for jar in sorted(settings.mods_directory.glob("*.jar"), key=lambda candidate: 0 if mod_id in candidate.name.lower() else 1):
        try:
            with zipfile.ZipFile(jar) as archive:
                names = set(archive.namelist())
                for candidate in candidates:
                    if candidate in names:
                        data = archive.read(candidate)
                        _icon_cache[cache_key] = data
                        return data
        except (OSError, zipfile.BadZipFile):
            continue
    return None


def _get_registry() -> list[RegistryItem]:
    global _registry_cache, _registry_mtime
    assert settings.mods_directory
    mods_dir = settings.mods_directory
    if not mods_dir.is_dir():
        return []
    current_mtime = mods_dir.stat().st_mtime
    if _registry_cache is not None and current_mtime == _registry_mtime:
        return _registry_cache
    items, seen = [], set()
    for jar in sorted(mods_dir.glob("*.jar")):
        try:
            with zipfile.ZipFile(jar) as archive:
                for name in archive.namelist():
                    if not name.endswith(".json"):
                        continue
                    parts, mod_id = name.split("/"), None
                    if len(parts) >= 5 and parts[0] == "assets" and parts[2] in {"models", "items"} and parts[3] == "item":
                        mod_id = parts[1]
                    elif len(parts) == 4 and parts[0] in {"data", "assets"} and parts[2] == "items":
                        mod_id = parts[1]
                    if mod_id:
                        item_id = f"{mod_id}:{Path(name).stem}"
                        if item_id not in seen:
                            seen.add(item_id)
                            items.append(RegistryItem(item_id=item_id, mod_id=mod_id, source_jar=jar.name))
        except (OSError, zipfile.BadZipFile):
            continue
    _registry_cache, _registry_mtime = items, current_mtime
    return items


def _items(mod: str | None, search: str, limit: int) -> list[RegistryItem]:
    return [item for item in _get_registry() if (not mod or item.mod_id == mod) and (not search or search in item.item_id.lower())][:limit]


@router.get("/players", response_model=list[PlayerItem])
async def players() -> list[PlayerItem]:
    return await asyncio.to_thread(_players)


def _players() -> list[PlayerItem]:
    assert settings.server_directory
    def read(filename: str) -> list[dict[str, str]]:
        try:
            return json.loads((settings.server_directory / filename).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
    whitelist = {entry.get("name", ""): entry.get("uuid") for entry in read("whitelist.json")}
    ops = {entry.get("name", ""): entry.get("uuid") for entry in read("ops.json")}
    bans = {entry.get("name", ""): entry.get("uuid") for entry in read("banned-players.json")}
    return [PlayerItem(username=name, uuid=whitelist.get(name) or ops.get(name) or bans.get(name), is_whitelisted=name in whitelist, is_op=name in ops, is_banned=name in bans) for name in sorted(set(whitelist) | set(ops) | set(bans))]


@router.post("/players/{action}")
async def player_action(action: str, payload: PlayerAction):
    commands = {"kick": f'/kick {payload.username} {payload.reason or "Expulsado por administración"}', "ban": f'/ban {payload.username} {payload.reason or "Baneado por administración"}', "pardon": f"/pardon {payload.username}", "op": f"/op {payload.username}", "deop": f"/deop {payload.username}", "spawn": f"/tp {payload.username} 0 100 0", "gamemode": f"/gamemode {payload.mode} {payload.username}"}
    if action not in commands or (action == "gamemode" and not payload.mode):
        raise HTTPException(400, "Acción inválida.")
    try:
        await server_manager.send_command(commands[action])
    except ServerProcessError as error:
        raise HTTPException(409, str(error)) from error
    return {"success": True, "message": "Comando enviado."}


@router.get("/gamerules", response_model=list[Gamerule])
async def gamerules() -> list[Gamerule]:
    return [Gamerule(name=name, value=value, kind="boolean" if value in {"true", "false"} else "number") for name, value in _gamerules.items()]


@router.post("/gamerules/{name}", response_model=Gamerule)
async def set_gamerule(name: str, value: str) -> Gamerule:
    if name not in _gamerules or (value not in {"true", "false"} and not value.isdigit()):
        raise HTTPException(400, "Regla o valor inválido.")
    try:
        await server_manager.send_command(f"/gamerule {name} {value}")
    except ServerProcessError as error:
        raise HTTPException(409, str(error)) from error
    _gamerules[name] = value
    return Gamerule(name=name, value=value, kind="boolean" if value in {"true", "false"} else "number")
