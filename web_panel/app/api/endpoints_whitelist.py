"""Endpoints protegidos para la gestión visual de la Whitelist."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.security import get_current_admin
from app.services.whitelist_service import WhitelistServiceError, whitelist_service

router = APIRouter(prefix="/whitelist", tags=["whitelist"], dependencies=[Depends(get_current_admin)])


class WhitelistToggleRequest(BaseModel):
    enabled: bool


class WhitelistPlayerRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")


@router.get("")
async def get_whitelist_status() -> dict[str, Any]:
    return await whitelist_service.get_status()


@router.post("/toggle")
async def toggle_whitelist(req: WhitelistToggleRequest) -> dict[str, Any]:
    try:
        return await whitelist_service.toggle(req.enabled)
    except WhitelistServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e


@router.post("/add")
async def add_to_whitelist(req: WhitelistPlayerRequest) -> dict[str, Any]:
    try:
        return await whitelist_service.add_player(req.username)
    except WhitelistServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/remove")
async def remove_from_whitelist(req: WhitelistPlayerRequest) -> dict[str, Any]:
    try:
        return await whitelist_service.remove_player(req.username)
    except WhitelistServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
