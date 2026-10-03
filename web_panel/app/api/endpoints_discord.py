"""Endpoints REST para configuración y pruebas de Webhooks de Discord."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_admin
from app.schemas.discord import DiscordActionResponse, DiscordConfig, DiscordTestRequest
from app.services.discord_service import discord_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/discord",
    tags=["discord"],
    dependencies=[Depends(get_current_admin)],
)


@router.get("/config", response_model=DiscordConfig)
async def get_discord_config() -> DiscordConfig:
    """Retorna la configuración actual de webhooks y alertas de Discord."""
    return discord_service.get_config()


@router.post("/config", response_model=DiscordActionResponse)
async def save_discord_config(config: DiscordConfig) -> DiscordActionResponse:
    """Guarda la configuración persistente en .discord_config.json."""
    try:
        discord_service.save_config(config)
        return DiscordActionResponse(
            success=True,
            message="Configuración de Discord guardada correctamente.",
        )
    except Exception as error:
        logger.error("Error guardando configuración de Discord: %s", error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No se pudo guardar la configuración: {error}",
        ) from error


@router.post("/test", response_model=DiscordActionResponse)
async def test_discord_webhook(req: DiscordTestRequest) -> DiscordActionResponse:
    """Envía un mensaje de prueba al webhook especificado o al configurado."""
    target_url = req.webhook_url.strip() if req.webhook_url else None
    test_type = req.test_type.strip() if req.test_type else "status"
    mention_role = req.mention_role.strip() if req.mention_role else ""
    success, message = await discord_service.send_test(
        webhook_url=target_url,
        test_type=test_type,
        mention_role=mention_role,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
    return DiscordActionResponse(success=True, message=message)
