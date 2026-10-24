"""Protected endpoints for the Playit tunnel."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import settings
from app.core.security import get_current_admin
from app.core.rate_limit import rate_limit
from app.schemas.runtime import (
    FriendAddressRequest,
    FriendAddressResponse,
    TunnelLogLine,
    TunnelSetupRequest,
    TunnelStatus,
)
from app.services.friend_address import FriendAddressError, normalize_address, save_address
from app.services.playit_host import PlayitAddressError
from app.services.playit_service import PlayitServiceError, playit_service
from app.services.server_properties_service import server_properties_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tunnel", tags=["tunnel"], dependencies=[Depends(get_current_admin)])


@router.get("/status", response_model=TunnelStatus)
async def tunnel_status() -> TunnelStatus:
    return playit_service.status()


@router.get("/logs", response_model=list[TunnelLogLine])
async def tunnel_logs() -> tuple[TunnelLogLine, ...]:
    """Bounded agent history for diagnostics, never exposed publicly."""
    return playit_service.history


@router.post("/begin-claim", response_model=TunnelStatus, dependencies=[Depends(rate_limit("playit-claim", 10, 300))])
async def begin_tunnel_claim() -> TunnelStatus:
    try:
        return await playit_service.begin_claim()
    except PlayitServiceError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.post("/complete-claim", response_model=TunnelStatus, dependencies=[Depends(rate_limit("playit-complete", 30, 300))])
async def complete_tunnel_claim() -> TunnelStatus:
    try:
        return await playit_service.complete_claim()
    except PlayitServiceError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

@router.post("/setup", response_model=TunnelStatus)
async def configure_tunnel(payload: TunnelSetupRequest) -> TunnelStatus:
    try:
        return await playit_service.configure_secret(payload.agent_secret)
    except PlayitServiceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/start", response_model=TunnelStatus)
async def start_tunnel() -> TunnelStatus:
    try:
        return await playit_service.start()
    except PlayitServiceError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.post("/external/start", response_model=TunnelStatus, dependencies=[Depends(rate_limit("playit-external-start", 10, 300))])
async def start_external_tunnel() -> TunnelStatus:
    """Turn on the official Playit app's service, like its Start menu shortcut does."""
    try:
        return await playit_service.start_external_agent()
    except PlayitServiceError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def _server_port() -> int:
    value = str(server_properties_service.read_properties().get("server-port", "25565")).strip()
    return int(value) if value.isdigit() else 25565


async def _save(address: str, message: str) -> FriendAddressResponse:
    try:
        saved_to = await asyncio.to_thread(save_address, settings, address)
    except FriendAddressError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return FriendAddressResponse(public_address=address, saved_to=saved_to, message=message)


@router.post("/external/address", response_model=FriendAddressResponse, dependencies=[Depends(rate_limit("playit-external-address", 10, 300))])
async def use_external_tunnel_address(use_agent_key: bool = True) -> FriendAddressResponse:
    """Copy the Minecraft address from the official Playit app; only the address is kept.

    ``use_agent_key=false`` asks only the app's local status pipe, never its agent key
    (used automatically after a start); the default also allows the one-off API fallback.
    """
    try:
        address = await playit_service.read_external_address(_server_port(), use_agent_key=use_agent_key)
    except PlayitAddressError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return await _save(address, f"Listo. Tus amigos entran con {address}")


@router.post("/address", response_model=FriendAddressResponse)
async def save_friend_address(payload: FriendAddressRequest) -> FriendAddressResponse:
    """Save an address the host pasted from Playit."""
    try:
        address = normalize_address(payload.public_address)
    except FriendAddressError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return await _save(address, f"Listo. Tus amigos entran con {address}")
