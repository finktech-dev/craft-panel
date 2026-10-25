"""Endpoints for LuckPerms integration and control."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.core.security import get_current_admin
from app.schemas.luckperms import (
    LuckPermsAvailability,
    LuckPermsCommandRequest,
    LuckPermsCustomRank,
    LuckPermsEditorResponse,
    LuckPermsPanelConfig,
    LuckPermsRankStep,
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


@router.post("/custom-ranks", response_model=LuckPermsAvailability)
async def save_custom_rank(rank: LuckPermsCustomRank) -> LuckPermsAvailability:
    """Remember a rank created from the panel, so every browser lists it."""
    try:
        return luckperms_service.save_custom_rank(rank)
    except (OSError, ValueError) as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "No se pudo guardar el rango en la configuración local.") from error


@router.delete("/custom-ranks/{rank_id}", response_model=LuckPermsAvailability)
async def delete_custom_rank(rank_id: str = Path(pattern=r"^[a-z0-9_-]{1,32}$")) -> LuckPermsAvailability:
    try:
        return luckperms_service.delete_custom_rank(rank_id)
    except (OSError, ValueError) as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "No se pudo borrar el rango de la configuración local.") from error


@router.post("/rank-step")
async def change_primary_rank(step: LuckPermsRankStep) -> dict[str, Any]:
    """Move a player one rank up or down, or back to the initial rank, without a LuckPerms track."""
    return await luckperms_service.change_primary_rank(step.player, step.direction)


@router.post("/editor", response_model=LuckPermsEditorResponse)
async def generate_luckperms_editor() -> LuckPermsEditorResponse:
    return await luckperms_service.get_editor_url()


@router.post("/command")
async def execute_luckperms_command(req: LuckPermsCommandRequest) -> dict[str, Any]:
    return await luckperms_service.execute_command(req.command)
