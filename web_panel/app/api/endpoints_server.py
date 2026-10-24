"""Protected REST controls for the server process and runtime metrics."""

from __future__ import annotations

import asyncio
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
from app.services.crash_guard import crash_guard
from app.services.job_service import Job, JobReporter
from app.services.metrics_service import metrics_service
from app.services.player_crash_service import player_crash_service
from app.services.playit_service import PlayitServiceError, playit_service
from app.services.external_server_service import external_server_detector
from app.services.friend_address import FriendAddressError, normalize_address, panel_address, save_address
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
from app.services.server_settings_file import read_server_settings
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
    """Fail fast (before any job starts) when Playit is chosen but not connected yet.

    An installed but stopped official Playit app is fine: the start job turns it on.
    """
    if settings.playit_enabled and playit_service.needs_setup and not playit_service.can_start_external_agent:
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


def _ready_timeout_seconds() -> float:
    """``startup_timeout`` from craftpanel.txt (5 minutes when not set)."""
    return float(read_server_settings(settings).value("startup_timeout") or READY_TIMEOUT_SECONDS)


async def _wait_until_ready(reporter: JobReporter) -> bool:
    """Final ``ready`` step shared by start and restart jobs."""
    reporter("ready", "Esperando a que el servidor termine de cargar el mundo.")
    try:
        await server_manager.wait_until_ready(timeout_seconds=_ready_timeout_seconds())
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
    job = await launch_start_job(dev_mode=dev_mode)
    # Starting by hand means someone is looking: automatic crash restarts may run again.
    crash_guard.reset()
    return accepted(job, "Encendiendo el servidor.")


async def launch_start_job(*, dev_mode: bool = False, title: str = "Encender el servidor") -> Job:
    """Run every check, then start the server as a job; shared by the button and the automations."""
    if server_manager.is_running:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El servidor ya está en ejecución.")
    _raise_if_busy()
    await _raise_if_settings_file_blocks_start()
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

    return start_job("start", title, START_STEPS, work)


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
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=found.explanation)


async def _raise_if_settings_file_blocks_start() -> None:
    """A wrong ``inicio`` or ``java`` in craftpanel.txt fails right away, before any job starts."""
    file_settings = await asyncio.to_thread(read_server_settings, settings)
    if problem := file_settings.launch_problem:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=problem)


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
    await _raise_if_settings_file_blocks_start()
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
    job = await launch_graceful_restart_job(countdown)
    return accepted(job, f"Avisamos a los jugadores y reiniciamos en {countdown} segundos.")


async def launch_graceful_restart_job(countdown: int, *, title: str = "Reiniciar avisando a los jugadores") -> Job:
    """Warn in the chat, save and restart as a job; also used by the daily restart."""
    _raise_if_busy()
    await _raise_if_settings_file_blocks_start()
    await _raise_if_external_server()
    _require_playit_ready()
    return start_job(
        "graceful_restart",
        title,
        GRACEFUL_RESTART_STEPS,
        _restart_work(
            lambda reporter: server_manager.graceful_restart(countdown_seconds=countdown, progress=reporter)
        ),
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
    kind: str | None = None
    reasons: list[str] = Field(default_factory=list)
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
        kind=found.kind,
        reasons=list(found.reasons),
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
    outcome = await asyncio.to_thread(external_server_detector.close, request.pid, server_manager.process_pid)
    if outcome is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se pudo cerrar ese servidor. Cerralo desde su propia ventana.",
        )
    if outcome == "saved":
        return _action_response("Listo: el servidor que estaba abierto aparte guardó el mundo y se cerró.")
    return _action_response(
        "Se cerró el servidor que estaba abierto aparte. No respondió al pedido de guardar, "
        "así que pudo perderse lo de los últimos minutos."
    )


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
    file_address: str | None = None,
    playit_host_state: str | None = None,
) -> FriendConnectionInfo:
    """Describe an existing address without starting, stopping or configuring tunnels."""
    custom_address = custom_address.strip() if custom_address else None
    configured_address = configured_address.strip() if configured_address else None
    file_address = file_address.strip() if file_address else None
    # Playit running as a Windows service may report no address of its own (it then echoes the
    # configured one); public_address from craftpanel.txt fills that gap.
    detected = tunnel.public_address
    if file_address and detected in {file_address, configured_address}:
        detected = None

    if tunnel.is_running and detected:
        address = tunnel.public_address
        source = "playit_detected"
        message = "Pasales esta dirección. En Minecraft van a Multijugador → Agregar servidor y la pegan."
        next_step = ""
    elif file_address:
        address = file_address
        source = "configured"
        message = "Esta es la dirección escrita en craftpanel.txt. Pasásela a tus amigos."
        next_step = "Si alguno no puede entrar, revisá que la dirección siga siendo la correcta."
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
        # The next step depends on the official Playit app (None when Internet access is off).
        if playit_host_state == "stopped":
            message = "Tu Playit está instalado pero apagado."
            next_step = "Al tocar Encender lo prendemos solo, y después aparece acá la dirección para tus amigos."
        elif playit_host_state == "running":
            message = "Playit está funcionando, pero todavía no sabemos tu dirección."
            next_step = "Tocá «Usar la dirección de mi Playit» o pegá abajo la que te muestra Playit."
        elif playit_host_state == "not_installed":
            message = "Por ahora solo se puede jugar desde esta computadora."
            next_step = "Para que entren amigos desde sus casas, instalá Playit desde playit.gg/download y volvé acá."
        else:
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

    custom_addr = panel_address(settings)

    tunnel_stat = playit_service.status()
    host_state = (await asyncio.to_thread(playit_service.host_status)).state if settings.playit_enabled else None
    return _friend_connection_info(
        port=port,
        custom_address=custom_addr,
        configured_address=settings.server_public_address,
        file_address=read_server_settings(settings).value("public_address"),
        tunnel=tunnel_stat,
        playit_host_state=host_state,
    )


@router.post("/connection-info")
async def update_connection_info(req: ConnectionInfoUpdateRequest) -> dict[str, Any]:
    """Save the address for friends (craftpanel.txt when it exists, else the panel)."""
    try:
        address = normalize_address(req.public_address)
        await asyncio.to_thread(save_address, settings, address)
    except FriendAddressError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    return {"success": True, "public_address": address, "message": "Dirección guardada."}


@router.get("/health-summary")
async def get_health_summary() -> dict[str, Any]:
    metrics = metrics_service.get_server_metrics()
    is_running = server_manager.is_running

    # Estimated TPS and MSPT
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

    # Latest backup
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

    # Latest crash / incident
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
