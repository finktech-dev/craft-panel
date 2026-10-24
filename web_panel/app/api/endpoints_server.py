"""Controles REST protegidos para el proceso del servidor y métricas de operación."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.endpoints_jobs import accepted, start_job
from app.core.config import settings
from app.core.security import get_current_admin
from app.core.rate_limit import rate_limit
from app.schemas.job import JobAccepted
from app.schemas.server import ServerActionResponse, ServerMetrics
from app.schemas.runtime import FriendConnectionInfo, TunnelStatus
from app.services import job_service as job_service_module
from app.services.backup_service import BACKUP_STEPS, backup_service
from app.services.job_service import JobReporter
from app.services.metrics_service import metrics_service
from app.services.player_crash_service import player_crash_service
from app.services.playit_service import PlayitServiceError, playit_service
from app.services.external_server_service import external_server_detector
from app.services.safety_service import SafetySummary, safety_service
from app.services.server_process import (
    GRACEFUL_RESTART_STEPS,
    RESTART_STEPS,
    START_STEPS,
    ServerBusyError,
    ServerProcessError,
    ServerStartTimeoutError,
    server_manager,
)
from app.services.server_properties_service import server_properties_service
from app.services.spark_service import spark_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/server",
    tags=["server"],
    dependencies=[Depends(get_current_admin)],
)


class ConnectionInfoUpdateRequest(BaseModel):
    public_address: str = Field(min_length=1, max_length=128)


# Big modpacks can take minutes to load; after this the job ends with a clear note.
READY_TIMEOUT_SECONDS = 300.0


def _require_playit_ready() -> None:
    """Fail fast (before any job starts) when Playit is chosen but not connected yet."""
    if settings.playit_enabled and playit_service.needs_setup:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conectá tu cuenta de Playit antes de iniciar, o elegí Solo red local en Preparar servidor.",
        )


async def _connect_playit() -> bool:
    """Start the default public connection; returns whether this call started it."""
    if not settings.playit_enabled:
        return False
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
    except Exception as error:  # noqa: BLE001 - startup and backup failures surface in their own sections
        logger.warning("The first automatic backup was not created: %s", error)


async def _wait_until_ready(reporter: JobReporter) -> bool:
    """Final ``ready`` step shared by start and restart jobs."""
    reporter("ready", "Esperando a que el servidor termine de cargar el mundo.")
    try:
        await server_manager.wait_until_ready(timeout_seconds=READY_TIMEOUT_SECONDS)
    except ServerStartTimeoutError:
        reporter.done_message = (
            "El servidor sigue cargando. Con muchos mods puede tardar más; "
            "mirá la consola si querés ver en qué va."
        )
        return False
    return True


async def _launch_first_backup_if_missing() -> None:
    """After the first start, make one copy of the brand-new world as its own job."""
    if backup_service.is_busy or await backup_service.list_backups():
        return
    from app.api.endpoints_backups import backup_job_work

    try:
        start_job("backup", "Primera copia del mundo", BACKUP_STEPS, backup_job_work, success_message="Primera copia lista.")
    except HTTPException as error:
        logger.info("Skipping the first automatic backup: %s", error.detail)


@router.post("/start", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def start_server(dev_mode: bool = False) -> JobAccepted:
    if server_manager.is_running:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El servidor ya está en ejecución.")
    _raise_if_busy()
    await _raise_if_external_server()
    _require_playit_ready()

    async def work(reporter: JobReporter) -> dict:
        if settings.playit_enabled:
            reporter("connect", "Conectando Playit para que tus amigos puedan entrar.")
        started_playit = await _connect_playit()
        try:
            started = await server_manager.start(dev_mode=dev_mode, progress=reporter)
        except ServerProcessError:
            if started_playit:
                await playit_service.stop()
            raise
        if not started:
            raise ServerBusyError("El servidor ya está iniciándose o en ejecución.")
        if await _wait_until_ready(reporter):
            if dev_mode:
                reporter.done_message = "Listo, el servidor está encendido en modo de prueba."
            elif settings.playit_enabled:
                reporter.done_message = "Listo, el servidor está encendido y tus amigos ya pueden entrar."
            else:
                reporter.done_message = "Listo, el servidor está encendido para jugar en esta casa."
            await _launch_first_backup_if_missing()
        else:
            job_service_module.job_service.spawn(_create_first_backup_after_ready(), "first-world-backup")
        return {"state": str(server_manager.state)}

    job = start_job("start", "Encender el servidor", START_STEPS, work)
    return accepted(job, "Encendiendo el servidor.")


@router.post("/stop", response_model=ServerActionResponse)
async def stop_server() -> ServerActionResponse:
    try:
        stopped = await server_manager.stop()
    except ServerProcessError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if not stopped:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El servidor ya está detenido.")
    return _action_response("Se envió /stop al servidor.")


async def _raise_if_external_server() -> None:
    """Refuse right away, before any job starts, when another server already holds the world."""
    own_pid = getattr(server_manager, "process_pid", None)
    found = await asyncio.to_thread(external_server_detector.detect, own_pid)
    if found is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=found.message)


def _raise_if_busy() -> None:
    """Fail fast before side effects such as starting Playit."""
    if operation := server_manager.lifecycle_operation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya hay una operación en curso ({operation}). Esperá a que termine.",
        )


def _restart_work(restart: Callable[[JobReporter], Awaitable[bool]]) -> Callable[[JobReporter], Awaitable[dict]]:
    async def work(reporter: JobReporter) -> dict:
        started_playit = await _connect_playit()
        try:
            restarted = await restart(reporter)
        except ServerProcessError:
            if started_playit:
                await playit_service.stop()
            raise
        if not restarted:
            if started_playit:
                await playit_service.stop()
            raise ServerBusyError("El reinicio se canceló porque se forzó el cierre del servidor.")
        if await _wait_until_ready(reporter):
            reporter.done_message = "Listo, el servidor se reinició y ya se puede entrar."
        return {"state": str(server_manager.state)}

    return work


@router.post("/restart", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def restart_server() -> JobAccepted:
    _raise_if_busy()
    await _raise_if_external_server()
    _require_playit_ready()
    job = start_job(
        "restart",
        "Reiniciar el servidor",
        RESTART_STEPS,
        _restart_work(lambda reporter: server_manager.restart(progress=reporter)),
    )
    return accepted(job, "Reiniciando el servidor.")


@router.post("/graceful-restart", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def graceful_restart_server(countdown: int = 10) -> JobAccepted:
    if countdown < 3 or countdown > 60:
        countdown = 10
    _raise_if_busy()
    await _raise_if_external_server()
    _require_playit_ready()
    job = start_job(
        "graceful_restart",
        "Reiniciar avisando a los jugadores",
        GRACEFUL_RESTART_STEPS,
        _restart_work(
            lambda reporter: server_manager.graceful_restart(countdown_seconds=countdown, progress=reporter)
        ),
    )
    return accepted(job, f"Avisamos a los jugadores y reiniciamos en {countdown} segundos.")


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
    can_terminate: bool = False


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
        can_terminate=found.can_terminate,
    )


@router.post("/external/terminate", response_model=ServerActionResponse)
async def terminate_external_server(request: ExternalServerTerminateRequest) -> ServerActionResponse:
    if not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmá explícitamente el cierre: se perderá lo que no se haya guardado.",
        )
    found = await asyncio.to_thread(external_server_detector.detect, server_manager.process_pid)
    if found is None or found.pid != request.pid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese programa ya se cerró o ya no está ocupando el servidor. Actualizá la página.",
        )
    if not found.can_terminate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Lo que ocupa el puerto {found.port} no es un servidor de Minecraft ({found.name}), "
                "así que el panel no lo cierra. Cerralo desde su propia ventana."
            ),
        )
    if not await asyncio.to_thread(
        external_server_detector.terminate, request.pid, server_manager.process_pid
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se pudo cerrar ese servidor. Cerralo desde su propia ventana.",
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


@router.post("/spark-audit", dependencies=[Depends(rate_limit("spark-audit", 4, 300))])
async def spark_audit() -> dict[str, Any]:
    if not server_manager.is_running:
        raise HTTPException(status_code=400, detail="El servidor debe estar encendido para ejecutar Spark.")
    return await spark_service.audit()


def _action_response(message: str) -> ServerActionResponse:
    return ServerActionResponse(success=True, message=message, state=str(server_manager.state))
