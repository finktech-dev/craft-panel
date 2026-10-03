"""Endpoints protegidos del túnel Playit."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_admin
from app.schemas.runtime import TunnelLogLine, TunnelSetupRequest, TunnelStatus
from app.services.playit_service import PlayitServiceError, playit_service

router = APIRouter(prefix="/tunnel", tags=["tunnel"], dependencies=[Depends(get_current_admin)])


@router.get("/status", response_model=TunnelStatus)
async def tunnel_status() -> TunnelStatus:
    return playit_service.status()


@router.get("/logs", response_model=list[TunnelLogLine])
async def tunnel_logs() -> tuple[TunnelLogLine, ...]:
    """Historial acotado del agente para diagnóstico sin exponerlo públicamente."""
    return playit_service.history


@router.post("/begin-claim", response_model=TunnelStatus)
async def begin_tunnel_claim() -> TunnelStatus:
    try:
        return await playit_service.begin_claim()
    except PlayitServiceError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.post("/complete-claim", response_model=TunnelStatus)
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
