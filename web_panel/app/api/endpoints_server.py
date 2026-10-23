"""Controles REST protegidos para el proceso del servidor y métricas de operación."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
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
from app.services.external_server_service import external_server_detector
from app.services.safety_service import SafetySummary, safety_service
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
    _raise_if_busy()
    started_playit = await _start_playit_if_required()
    try:
        started = await server_manager.start(dev_mode=dev_mode)
    except ServerProcessError as error:
        if started_playit:
            await playit_service.stop()
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    if not started:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El servidor ya está iniciándose o en ejecución.")
    if dev_mode:
        msg = "Servidor iniciado en Modo Dev (Silencioso)."
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


def _raise_if_busy() -> None:
    """Fail fast before side effects such as starting Playit."""
    if operation := server_manager.lifecycle_operation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya hay una operación en curso ({operation}). Esperá a que termine.",
        )


async def _run_restart(restart: Callable[[], Awaitable[bool]], success_message: str) -> ServerActionResponse:
    started_playit = await _start_playit_if_required()
    try:
        restarted = await restart()
    except ServerProcessError as error:
        if started_playit:
            await playit_service.stop()
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    if not restarted:
        if started_playit:
            await playit_service.stop()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El reinicio se canceló porque se forzó la detención del servidor.",
        )
    return _action_response(success_message)


@router.post("/restart", response_model=ServerActionResponse)
async def restart_server() -> ServerActionResponse:
    _raise_if_busy()
    return await _run_restart(server_manager.restart, "Servidor reiniciado.")


@router.post("/graceful-restart", response_model=ServerActionResponse)
async def graceful_restart_server(countdown: int = 10) -> ServerActionResponse:
    if countdown < 3 or countdown > 60:
        countdown = 10
    _raise_if_busy()
    return await _run_restart(
        lambda: server_manager.graceful_restart(countdown_seconds=countdown),
        f"Reinicio suave completado después del aviso de {countdown} segundos.",
    )


@router.post("/kill", response_model=ServerActionResponse)
async def kill_server() -> ServerActionResponse:
    if not await server_manager.kill():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El servidor ya está detenido.")
    return _action_response("Se solicitó la finalización forzada del servidor.")


class ExternalServerInfo(BaseModel):
    detected: bool
    pid: int | None = None
    process_name: str | None = None
    reason: str | None = None
    port: int | None = None
    message: str | None = None


class ExternalServerTerminateRequest(BaseModel):
    pid: int = Field(gt=0)
    confirm: bool = False


@router.get("/safety-summary", response_model=SafetySummary)
async def safety_summary() -> SafetySummary:
    """Access, disk, backups and diagnostics in one read-only call for the dashboard."""
    properties = server_properties_service.read_properties()
    return await asyncio.to_thread(
        safety_service.summary, properties, settings.playit_enabled, server_manager.process_pid
    )


@router.get("/external", response_model=ExternalServerInfo)
async def external_server() -> ExternalServerInfo:
    """Report a server running outside the panel (run.bat, previous panel session, port clash)."""
    found = await asyncio.to_thread(external_server_detector.detect, server_manager.process_pid)
    if found is None:
        return ExternalServerInfo(detected=False)
    return ExternalServerInfo(
        detected=True,
        pid=found.pid,
        process_name=found.name,
        reason=found.reason,
        port=found.port,
        message=found.message,
    )


@router.post("/external/terminate", response_model=ServerActionResponse)
async def terminate_external_server(request: ExternalServerTerminateRequest) -> ServerActionResponse:
    if not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmá explícitamente el cierre: se perderá lo que no se haya guardado.",
        )
    if not await asyncio.to_thread(
        external_server_detector.terminate, request.pid, server_manager.process_pid
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese proceso ya no se detecta como servidor externo o no se pudo cerrar.",
        )
    return _action_response("Se cerró el servidor que estaba corriendo fuera del panel.")


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
        message = "Pasales esta dirección. En Minecraft van a Multijugador → Agregar servidor y la pegan."
        next_step = ""
    elif custom_address:
        address = custom_address
        source = "manual"
        message = "Esta es la dirección que escribiste en Ajustes. No podemos comprobar si funciona desde otras casas."
        next_step = "Probala primero con un amigo antes de pasársela a todos."
    elif configured_address:
        address = configured_address
        source = "configured"
        message = "Esta es la dirección guardada para tu servidor. Pasásela a tus amigos."
        next_step = "Si alguno no puede entrar, revisá que la dirección siga siendo la correcta."
    else:
        address = f"127.0.0.1:{port}"
        source = "local_only"
        message = "Por ahora solo se puede jugar desde esta computadora."
        next_step = "Para que entren amigos desde sus casas, activá el acceso por Internet en Ajustes."

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
