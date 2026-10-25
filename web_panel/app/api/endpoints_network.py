"""VPNs on this PC and opening the panel to them."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import get_current_admin, request_is_direct_loopback
from app.services import vpn_service

router = APIRouter(prefix="/network", tags=["network"], dependencies=[Depends(get_current_admin)])


class VpnItem(BaseModel):
    name: str
    address: str
    panel_link: str | None = None


class VpnState(BaseModel):
    networks: list[VpnItem]
    panel_access_enabled: bool
    # The panel listens on these VPNs right now (it was started with access on).
    panel_access_active: bool
    # A restart is needed for a change, or for a VPN connected after the panel started.
    needs_restart: bool
    # Only someone sitting at this PC may open or close the panel to the VPN.
    can_change: bool


class VpnAccessUpdate(BaseModel):
    panel_access: bool


def _state(request: Request) -> VpnState:
    assert settings.panel_directory is not None
    enabled = vpn_service.panel_access_enabled(settings.panel_directory)
    access = vpn_service.panel_vpn_access
    bound = {network.address for network in access.networks}
    networks = vpn_service.detect()
    items = [
        VpnItem(
            name=network.name,
            address=network.address,
            panel_link=f"http://{network.address}:{settings.panel_port}" if network.address in bound else None,
        )
        for network in networks
    ]
    active = access.restrict_peers
    if enabled:
        needs_restart = bool(networks) and any(network.address not in bound for network in networks)
    else:
        needs_restart = active
    return VpnState(
        networks=items,
        panel_access_enabled=enabled,
        panel_access_active=active,
        needs_restart=needs_restart,
        can_change=request_is_direct_loopback(request) and settings.panel_mode == "local",
    )


@router.get("/vpn", response_model=VpnState)
async def vpn_state(request: Request) -> VpnState:
    return await asyncio.to_thread(_state, request)


@router.put("/vpn", response_model=VpnState)
async def update_vpn_access(payload: VpnAccessUpdate, request: Request) -> VpnState:
    if settings.panel_mode != "local":
        raise HTTPException(status.HTTP_409_CONFLICT, "El panel ya está publicado por Internet; la VPN no hace falta.")
    if not request_is_direct_loopback(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Esto solo se cambia desde la computadora del servidor.")
    assert settings.panel_directory is not None
    try:
        await asyncio.to_thread(vpn_service.save_panel_access, settings.panel_directory, payload.panel_access)
    except OSError as error:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "No se pudo guardar el cambio. Probá de nuevo.") from error
    return await asyncio.to_thread(_state, request)
