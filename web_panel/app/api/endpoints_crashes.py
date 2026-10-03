"""Endpoints para el analizador y registro de desconexiones y crashes por jugador."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import get_current_admin
from app.schemas.player_crashes import PlayerCrashEvent, PlayerCrashesListResponse
from app.services.player_crash_service import player_crash_service

router = APIRouter(prefix="/player-crashes", tags=["crashes"], dependencies=[Depends(get_current_admin)])


@router.get("", response_model=PlayerCrashesListResponse)
async def list_player_crashes(
    player: str | None = None,
    category: str | None = None,
    search: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> PlayerCrashesListResponse:
    return await player_crash_service.list_events(
        player=player,
        category=category,
        search=search,
        limit=limit,
    )


@router.get("/{crash_id}", response_model=PlayerCrashEvent)
async def get_player_crash(crash_id: str) -> PlayerCrashEvent:
    event = await player_crash_service.get_event(crash_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evento no encontrado.")
    return event


@router.post("/scan")
async def scan_player_crashes() -> dict[str, Any]:
    count = await player_crash_service.scan_logs()
    return {"success": True, "new_events": count, "message": f"Escaneo completado: {count} eventos nuevos detectados."}


@router.delete("")
async def clear_player_crashes() -> dict[str, Any]:
    await player_crash_service.clear_events()
    return {"success": True, "message": "Historial de desconexiones y crashes limpiado."}
