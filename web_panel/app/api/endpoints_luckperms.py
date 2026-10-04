"""Endpoints para integración y control de LuckPerms."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends

from app.core.security import get_current_admin
from app.schemas.luckperms import (
    LuckPermsAvailability,
    LuckPermsCommandRequest,
    LuckPermsEditorResponse,
    LuckPermsPanelConfig,
)
from app.services.luckperms_service import luckperms_service

router = APIRouter(prefix="/luckperms", tags=["luckperms"], dependencies=[Depends(get_current_admin)])


@router.get("/config", response_model=LuckPermsAvailability)
async def get_luckperms_configuration() -> LuckPermsAvailability:
    """Return the non-secret per-installation settings needed by the UI."""
    return luckperms_service.get_configuration()


@router.post("/config", response_model=LuckPermsAvailability)
async def update_luckperms_configuration(payload: LuckPermsPanelConfig) -> LuckPermsAvailability:
    """Persist LuckPerms panel configuration."""
    luckperms_service.save_configuration(payload)
    return luckperms_service.get_configuration()


@router.post("/editor", response_model=LuckPermsEditorResponse)
async def generate_luckperms_editor() -> LuckPermsEditorResponse:
    return await luckperms_service.get_editor_url()


@router.post("/command")
async def execute_luckperms_command(req: LuckPermsCommandRequest) -> dict[str, Any]:
    return await luckperms_service.execute_command(req.command)
