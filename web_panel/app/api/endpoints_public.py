"""Deliberately limited public information for the landing page."""

from fastapi import APIRouter

from app.schemas.server import PublicServerStatus
from app.services.playit_service import playit_service
from app.services.server_process import server_manager

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/status", response_model=PublicServerStatus)
async def public_server_status() -> PublicServerStatus:
    """Exposes no console, players, IPs, metrics or admin controls."""
    tunnel = playit_service.status()
    return PublicServerStatus(
        online=server_manager.is_running,
        state=str(server_manager.state),
        address=tunnel.public_address,
    )
