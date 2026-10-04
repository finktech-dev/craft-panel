"""Controles REST protegidos para el proceso NeoForge y métricas de operación."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import get_current_admin
from app.schemas.server import ServerActionResponse, ServerMetrics
from app.schemas.runtime import FriendConnectionInfo, TunnelStatus
from app.services.backup_service import backup_service
from app.services.metrics_service import metrics_service
from app.services.player_crash_service import player_crash_service
from app.services.playit_service import PlayitServiceError, playit_service
from app.services.server_process import ServerProcessError, server_manager
from app.services.server_properties_service import server_properties_service
from app.services.spark_service import spark_service

router = APIRouter(
    prefix="/server",
    tags=["server"],
    dependencies=[Depends(get_current_admin)],
)


class ConnectionInfoUpdateRequest(BaseModel):
    public_address: str = Field(min_length=1, max_length=128)


async def _start_playit_if_required() -> bool:
    """Start the default public connection before Minecraft, unless LAN-only was chosen."""
    if not settings.playit_enabled:
        return False
    if playit_service.needs_setup:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conectá tu cuenta de Playit antes de iniciar, o elegí Solo red local en Preparar servidor.",
        )
    try:
        was_running = playit_service.is_running or playit_service.uses_external_agent
        await playit_service.start()
        return not was_running
    except PlayitServiceError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error


async def _create_first_backup_after_ready() -> None:
    """Create exactly one first-world backup after Minecraft has generated it."""
    try:
        await server_manager.wait_until_ready()
        if not await backup_service.list_backups():
            await backup_service.create_backup()
    except Exception:
        # Startup and backup failures remain visible in their own panel sections.
        return

@router.post("/start", response_model=ServerActionResponse)
async def start_server(dev_mode: bool = False) -> ServerActionResponse:
    if server_manager.is_running:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El servidor ya está en ejecución.")
    started_playit = await _start_playit_if_required()
    try:
        await server_manager.start(dev_mode=dev_mode)
    except ServerProcessError as error:
        if started_playit:
            await playit_service.stop()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    if dev_mode:
        msg = "Servidor NeoForge iniciado en Modo Dev (Silencioso)."
    elif settings.playit_enabled:
        msg = "Servidor iniciado y Playit quedó conectado para compartirlo con amigos."
    else:
        msg = "Servidor iniciado sólo para la red local."
    asyncio.create_task(_create_first_backup_after_ready(), name="first-world-backup")
    return _action_response(f"{msg} A first backup will be created when the world is ready.")
@router.post("/stop", response_model=ServerActionResponse)
async def stop_server() -> ServerActionResponse:
    try:
        stopped = await server_manager.stop()
    except ServerProcessError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if not stopped:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El servidor ya está detenido.")
    return _action_response("Se envió /stop al servidor.")


@router.post("/restart", response_model=ServerActionResponse)
async def restart_server() -> ServerActionResponse:
    if server_manager.is_running:
        await server_manager.stop()
        try:
            await asyncio.wait_for(
                server_manager.wait_until_stopped(), timeout=settings.graceful_stop_timeout_seconds
            )
        except TimeoutError:
            await server_manager.kill()
            await server_manager.wait_until_stopped()

    try:
        await server_manager.start()
    except ServerProcessError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    return _action_response("Servidor NeoForge reiniciado.")


@router.post("/graceful-restart", response_model=ServerActionResponse)
async def graceful_restart_server(countdown: int = 10) -> ServerActionResponse:
    if countdown < 3 or countdown > 60:
        countdown = 10
    asyncio.create_task(server_manager.graceful_restart(countdown_seconds=countdown), name="graceful-restart-task")
    return _action_response(f"Iniciando reinicio suave con aviso de {countdown} segundos en el chat.")


@router.post("/kill", response_model=ServerActionResponse)
async def kill_server() -> ServerActionResponse:
    if not await server_manager.kill():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El servidor ya está detenido.")
    return _action_response("Se solicitó la finalización forzada del servidor.")


@router.get("/metrics", response_model=ServerMetrics)
async def server_metrics() -> ServerMetrics:
    return metrics_service.get_server_metrics()


@router.get("/online-players")
async def get_online_players() -> dict[str, Any]:
    props = server_properties_service.read_properties()
    max_players = int(props.get("max-players", "10"))
    players = server_manager.get_online_players()
    return {
        "count": len(players),
        "max_players": max_players,
        "is_running": server_manager.is_running,
        "players": players,
    }


def _friend_connection_info(
    *,
    port: int,
    custom_address: str | None,
    configured_address: str | None,
    tunnel: TunnelStatus,
) -> FriendConnectionInfo:
    """Describe una dirección existente sin iniciar, detener ni configurar túneles."""
    custom_address = custom_address.strip() if custom_address else None
    configured_address = configured_address.strip() if configured_address else None

    if tunnel.is_running and tunnel.public_address:
        address = tunnel.public_address
        source = "playit_detected"
        message = "Playit está activo y el panel detectó esta dirección para compartir."
        next_step = "Copiala y pedile a un amigo que la pruebe desde otra red."
    elif custom_address:
        address = custom_address
        source = "manual"
        message = "Usando la dirección que configuraste manualmente. El panel no verifica su alcance desde Internet."
        next_step = "Confirmala con un amigo desde otra red antes de compartirla con todos."
    elif configured_address:
        address = configured_address
        source = "configured"
        message = "Usando la dirección guardada en la configuración del servidor. El panel no controla ese acceso."
        next_step = "Probala desde otra red para confirmar que sigue funcionando."
    else:
        address = f"127.0.0.1:{port}"
        source = "local_only"
        message = "Todavía no hay una dirección pública detectada; esta dirección sólo funciona en esta computadora."
        next_step = "Configurá una forma de acceso externo, como Playit, y luego volvé a revisar esta pantalla."

    return FriendConnectionInfo(
        public_address=address,
        server_port=port,
        source=source,
        can_share_with_friends=source != "local_only",
        tunnel_active=tunnel.is_running,
        is_custom=source == "manual",
        message=message,
        next_step=next_step,
    )


@router.get("/connection-info", response_model=FriendConnectionInfo)
async def get_connection_info() -> FriendConnectionInfo:
    props = server_properties_service.read_properties()
    port = int(props.get("server-port", "25565"))

    conn_file = settings.panel_directory / ".server_connection.json" if settings.panel_directory else None
    custom_addr = None
    if conn_file and conn_file.is_file():
        try:
            data = json.loads(conn_file.read_text(encoding="utf-8"))
            custom_addr = data.get("public_address")
        except Exception:
            pass

    tunnel_stat = playit_service.status()
    return _friend_connection_info(
        port=port,
        custom_address=custom_addr,
        configured_address=settings.server_public_address,
        tunnel=tunnel_stat,
    )


@router.post("/connection-info")
async def update_connection_info(req: ConnectionInfoUpdateRequest) -> dict[str, Any]:
    conn_file = settings.panel_directory / ".server_connection.json" if settings.panel_directory else None
    if conn_file:
        try:
            conn_file.write_text(json.dumps({"public_address": req.public_address.strip()}, indent=2), encoding="utf-8")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"No se pudo guardar la dirección: {e}")
    return {"success": True, "public_address": req.public_address.strip(), "message": "Dirección permanente guardada correctamente."}


@router.get("/health-summary")
async def get_health_summary() -> dict[str, Any]:
    metrics = metrics_service.get_server_metrics()
    is_running = server_manager.is_running

    # TPS y MSPT estimados
    tps = 20.0 if is_running else 0.0
    mspt = round(min(50.0, max(15.0, metrics.cpu_percent * 0.4)), 1) if is_running else 0.0
    if not is_running:
        health_status = "DETENIDO"
        health_label = "Servidor detenido"
        health_color = "zinc"
    elif metrics.cpu_percent > 85.0 or metrics.ram_percent > 95.0:
        health_status = "CRITICO"
        health_label = "Carga alta / Riesgo de lag"
        health_color = "rose"
    elif metrics.cpu_percent > 60.0 or metrics.ram_percent > 85.0:
        health_status = "MODERADO"
        health_label = "Carga moderada"
        health_color = "amber"
    else:
        health_status = "EXCELENTE"
        health_label = "Fluido (20.0 TPS)"
        health_color = "emerald"

    # Último backup
    last_backup_info = None
    try:
        backups = await backup_service.list_backups()
        if backups:
            first = backups[0]
            last_backup_info = {
                "filename": first.filename,
                "size_mb": first.size_mb,
                "created_at": first.created_at.isoformat(),
            }
    except Exception:
        pass

    # Último crash / incidente
    last_crash_info = None
    try:
        crash_list = await player_crash_service.list_events(limit=5)
        abnormal = [e for e in crash_list.events if e.category != "NORMAL_DISCONNECT"]
        if abnormal:
            latest = abnormal[0]
            last_crash_info = {
                "id": latest.id,
                "player": latest.player,
                "category": latest.category,
                "category_label": latest.category_label,
                "timestamp": latest.timestamp,
                "severity": latest.severity,
            }
    except Exception:
        pass

    return {
        "is_running": is_running,
        "tps": tps,
        "mspt": mspt,
        "health_status": health_status,
        "health_label": health_label,
        "health_color": health_color,
        "last_backup": last_backup_info,
        "last_crash": last_crash_info,
    }


@router.post("/spark-audit")
async def spark_audit() -> dict[str, Any]:
    if not server_manager.is_running:
        raise HTTPException(status_code=400, detail="El servidor debe estar encendido para ejecutar Spark.")
    return await spark_service.audit()


def _action_response(message: str) -> ServerActionResponse:
    return ServerActionResponse(success=True, message=message, state=str(server_manager.state))
