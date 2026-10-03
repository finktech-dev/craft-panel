"""Endpoints protegidos para la inspección y reinicio de logros de jugadores en cualquier mundo."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.security import get_current_admin
from app.services.advancement_service import advancement_service

router = APIRouter(prefix="/advancements", tags=["advancements"], dependencies=[Depends(get_current_admin)])


class AdvancementActionRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    advancement_id: str = Field(min_length=1, max_length=128)  # 'everything' o ID de logro
    world_name: str | None = Field(default=None, max_length=64)


@router.get("/worlds")
async def list_advancement_worlds() -> list[dict[str, Any]]:
    return await advancement_service.list_worlds()


@router.get("/players")
async def list_advancement_players(world: str | None = Query(default=None)) -> list[dict[str, Any]]:
    return await advancement_service.list_players(world_name=world)


@router.get("/player/{username}")
async def get_player_advancements(username: str, world: str | None = Query(default=None)) -> dict[str, Any]:
    return await advancement_service.get_player_advancements(username, world_name=world)


@router.post("/revoke")
async def revoke_advancement(req: AdvancementActionRequest) -> dict[str, Any]:
    try:
        return await advancement_service.revoke_advancement(req.username, req.advancement_id, world_name=req.world_name)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/grant")
async def grant_advancement(req: AdvancementActionRequest) -> dict[str, Any]:
    try:
        return await advancement_service.grant_advancement(req.username, req.advancement_id, world_name=req.world_name)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
