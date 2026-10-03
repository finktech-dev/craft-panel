"""Routes for live WorldEdit and restriction controls."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import get_current_admin
from app.schemas.universal import (
    BlacklistItemRequest,
    BlacklistState,
    RestrictionItemRequest,
    RestrictionMobRequest,
    RestrictionVillagerRequest,
    WorldEditToggleRequest,
)
from app.services.luckperms_service import luckperms_service
from app.services.restriction_service import restriction_service

router = APIRouter(tags=["restrictions"], dependencies=[Depends(get_current_admin)])


@router.get("/worldedit/status")
async def worldedit_status():
    return luckperms_service.get_worldedit_status()


@router.post("/worldedit/toggle")
async def worldedit_toggle(payload: WorldEditToggleRequest):
    return await luckperms_service.set_worldedit_status(payload.enabled)


@router.get("/restrictions/summary")
async def restrictions_summary():
    data = restriction_service.get_summary()
    data["worldedit"] = luckperms_service.get_worldedit_status()
    return data


@router.get("/restrictions/catalog")
async def restrictions_catalog():
    return await restriction_service.discover_catalog()


@router.post("/restrictions/items")
async def restrictions_item_toggle(payload: RestrictionItemRequest):
    if payload.action == "remove":
        items = await restriction_service.remove_restricted_item(payload.item_id)
        message = f"Ítem {payload.item_id} removido de la restricción."
    else:
        items = await restriction_service.add_restricted_item(payload.item_id)
        message = f"Ítem {payload.item_id} restringido."
    return {"success": True, "items": items, "message": message}


@router.delete("/restrictions/items/{item_id:path}")
async def restrictions_item_delete(item_id: str):
    items = await restriction_service.remove_restricted_item(item_id)
    return {"success": True, "items": items, "message": f"Ítem {item_id} removido de la restricción."}


@router.post("/restrictions/mobs")
async def restrictions_mob_toggle(payload: RestrictionMobRequest):
    if payload.action == "remove":
        mobs = await restriction_service.remove_restricted_mob(payload.entity_id)
        message = f"Spawn de {payload.entity_id} restaurado."
    else:
        mobs = await restriction_service.add_restricted_mob(payload.entity_id)
        message = f"Spawn de {payload.entity_id} bloqueado en Overworld, Nether y End."
    return {"success": True, "mobs": mobs, "message": message}


@router.delete("/restrictions/mobs/{entity_id:path}")
async def restrictions_mob_delete(entity_id: str):
    mobs = await restriction_service.remove_restricted_mob(entity_id)
    return {"success": True, "mobs": mobs, "message": f"Spawn de {entity_id} restaurado."}


@router.post("/restrictions/villagers")
async def restrictions_villager_toggle(payload: RestrictionVillagerRequest):
    is_disabled = payload.disabled if payload.disable is None else payload.disable
    professions = await restriction_service.set_villager_restricted(payload.profession_id, is_disabled)
    status_label = "desactivada" if is_disabled else "activada"
    return {
        "success": True,
        "villagers": professions,
        "message": f"Profesión {payload.profession_id} {status_label} correctamente.",
    }


@router.get("/blacklist", response_model=BlacklistState)
async def blacklist():
    items = restriction_service.get_restricted_items()
    return BlacklistState(items=items, enforcement_available=True, message=f"{len(items)} ítems en la lista de bloqueo.")


@router.post("/blacklist", response_model=BlacklistState)
async def blacklist_add(payload: BlacklistItemRequest):
    items = await restriction_service.add_restricted_item(payload.item_id)
    return BlacklistState(items=items, enforcement_available=True, message=f"{payload.item_id} agregado.")


@router.delete("/blacklist/{item_id:path}", response_model=BlacklistState)
async def blacklist_remove(item_id: str):
    if ":" not in item_id:
        from fastapi import HTTPException
        raise HTTPException(400, "ID de ítem inválido.")
    items = await restriction_service.remove_restricted_item(item_id)
    return BlacklistState(items=items, enforcement_available=True, message=f"{item_id} quitado.")
