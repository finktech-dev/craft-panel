"""Endpoints protegidos para marcadores de coordenadas y teletransporte."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_admin
from app.schemas.waypoints import Waypoint, WaypointCreate, WaypointTeleportRequest
from app.services.waypoint_service import waypoint_service

router = APIRouter(prefix="/waypoints", tags=["waypoints"], dependencies=[Depends(get_current_admin)])


@router.get("", response_model=list[Waypoint])
async def list_waypoints() -> list[Waypoint]:
    return await waypoint_service.list_waypoints()


@router.post("", response_model=Waypoint)
async def add_waypoint(req: WaypointCreate) -> Waypoint:
    return await waypoint_service.add_waypoint(req)


@router.delete("/{waypoint_id}")
async def delete_waypoint(waypoint_id: str) -> dict[str, Any]:
    deleted = await waypoint_service.delete_waypoint(waypoint_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Marcador no encontrado.")
    return {"success": True, "message": "Marcador eliminado."}


@router.post("/{waypoint_id}/teleport")
async def teleport_to_waypoint(waypoint_id: str, req: WaypointTeleportRequest | None = None) -> dict[str, Any]:
    target = req.target if req else "@a"
    try:
        return await waypoint_service.teleport(waypoint_id, target)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
