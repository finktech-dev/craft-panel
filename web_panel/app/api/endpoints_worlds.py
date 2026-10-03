"""Endpoints protegidos para el gestor de mundos y editor de server.properties."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_admin
from app.schemas.worlds import (
    ServerPropertiesResponse,
    ServerPropertiesSaveRequest,
    WorldCreateRequest,
    WorldItem,
    WorldSwitchRequest,
)
from app.services.server_properties_service import server_properties_service
from app.services.runtime_guard import ServerActiveError
from app.services.world_service import world_service

router = APIRouter(tags=["worlds"], dependencies=[Depends(get_current_admin)])


@router.get("/worlds", response_model=list[WorldItem])
async def list_worlds() -> list[WorldItem]:
    return await world_service.list_worlds()


@router.post("/worlds/switch")
async def switch_world(req: WorldSwitchRequest) -> dict[str, Any]:
    try:
        return await world_service.switch_world(req.world_name)
    except ServerActiveError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/worlds/create")
async def create_world(req: WorldCreateRequest) -> dict[str, Any]:
    try:
        return await world_service.create_world(req)
    except ServerActiveError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.delete("/worlds/{world_name}")
async def delete_world(world_name: str) -> dict[str, Any]:
    try:
        return await world_service.delete_world(world_name)
    except ServerActiveError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/server-properties", response_model=ServerPropertiesResponse)
async def get_server_properties() -> ServerPropertiesResponse:
    return await server_properties_service.get_properties_response()


@router.post("/server-properties", response_model=ServerPropertiesResponse)
async def update_server_properties(req: ServerPropertiesSaveRequest) -> ServerPropertiesResponse:
    try:
        return await server_properties_service.update_properties(req.properties)
    except ServerActiveError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
