"""Admin controls for the Cloudflare Quick Tunnel."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_admin
from app.core.rate_limit import rate_limit
from app.schemas.runtime import CloudflareQuickTunnelStatus
from app.services.cloudflare_service import CloudflareQuickTunnelError, cloudflare_quick_tunnel_service

router = APIRouter(prefix="/cloudflare", tags=["cloudflare"], dependencies=[Depends(get_current_admin)])


@router.get("/status", response_model=CloudflareQuickTunnelStatus)
async def cloudflare_status() -> CloudflareQuickTunnelStatus:
    return cloudflare_quick_tunnel_service.status()


@router.post("/start", response_model=CloudflareQuickTunnelStatus, dependencies=[Depends(rate_limit("cloudflare-start", 10, 300))])
async def start_cloudflare_tunnel() -> CloudflareQuickTunnelStatus:
    try:
        return await cloudflare_quick_tunnel_service.start()
    except CloudflareQuickTunnelError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.post("/stop", response_model=CloudflareQuickTunnelStatus)
async def stop_cloudflare_tunnel() -> CloudflareQuickTunnelStatus:
    return await cloudflare_quick_tunnel_service.stop()
