"""REST endpoints to configure and test Discord webhooks."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_admin
from app.core.rate_limit import rate_limit
from app.schemas.discord import DiscordActionResponse, DiscordBridgeStatus, DiscordConfig, DiscordTestRequest
from app.services.discord_bridge import discord_bridge_service
from app.services.discord_service import discord_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/discord",
    tags=["discord"],
    dependencies=[Depends(get_current_admin)],
)


@router.get("/config", response_model=DiscordConfig)
async def get_discord_config() -> DiscordConfig:
    """Return the current Discord webhook and alert settings."""
    return discord_service.get_config()


@router.get("/bridge", response_model=DiscordBridgeStatus)
async def get_discord_bridge() -> DiscordBridgeStatus:
    """Whether a mod links the game chat with Discord (the panel's own notices need none)."""
    return await discord_bridge_service.status()


@router.post("/config", response_model=DiscordActionResponse)
async def save_discord_config(config: DiscordConfig) -> DiscordActionResponse:
    """Save the persistent settings to .discord_config.json."""
    try:
        discord_service.save_config(config)
        return DiscordActionResponse(
            success=True,
            message="Configuración de Discord guardada correctamente.",
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except Exception as error:
        logger.error("Error guardando configuración de Discord: %s", error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No se pudo guardar la configuración: {error}",
        ) from error


@router.post("/test", response_model=DiscordActionResponse, dependencies=[Depends(rate_limit("discord-test", 10, 60))])
async def test_discord_webhook(req: DiscordTestRequest) -> DiscordActionResponse:
    """Send a test message to the given webhook or the configured one."""
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
