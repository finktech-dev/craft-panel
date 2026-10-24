"""Automations driven by craftpanel.txt: start with the panel, restart after a crash, daily restart.

They live next to the endpoints because they reuse the same jobs and checks
as the buttons (external server, Playit, a broken settings file), so an
automation can never do something the person could not do by hand.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException

from app.core.config import settings
from app.services.crash_guard import crash_guard
from app.services.external_server_service import external_server_detector
from app.services.scheduler_service import scheduler_service
from app.services.server_process import server_manager
from app.services.server_settings_file import read_server_settings

logger = logging.getLogger(__name__)

# Give Windows a moment to release the world and the port before starting again.
CRASH_RESTART_DELAY_SECONDS = 10.0


def _endpoints():
    from app.api import endpoints_server

    return endpoints_server


async def _blocked_reason() -> str | None:
    """Why an automation must not start or restart the server right now."""
    if server_manager.lifecycle_operation:
        return f"hay otra operación en curso ({server_manager.lifecycle_operation})"
    external = await asyncio.to_thread(external_server_detector.detect, server_manager.process_pid)
    if external is not None:
        return "hay un servidor abierto fuera del panel"
    return None


async def start_with_panel() -> None:
    """``start_with_panel = true``: start the server as a job when the panel opens."""
    if not read_server_settings(settings).effective("start_with_panel"):
        return
    if server_manager.is_running:
        return
    tunnel = _endpoints().playit_service
    # A stopped official Playit app is fine: the start job turns it on.
    if settings.playit_enabled and tunnel.needs_setup and not tunnel.can_start_external_agent:
        logger.info("Not starting with the panel: Playit still needs to be connected.")
        return
    if reason := await _blocked_reason():
        logger.info("Not starting with the panel: %s.", reason)
        return
    try:
        await _endpoints().launch_start_job(title="Encender el servidor al abrir el panel")
    except HTTPException as error:
        logger.info("Not starting with the panel: %s", error.detail)


async def restart_after_crash() -> None:
    """``restart_on_crash = true``: start again after the server ended on its own."""
    file_settings = read_server_settings(settings)
    if not file_settings.effective("restart_on_crash"):
        return
    if not crash_guard.allow_restart(int(file_settings.effective("max_crash_restarts"))):
        message = crash_guard.paused_message or "Dejamos de volver a encenderlo solo."
        await server_manager.log_system(message)
        return
    await server_manager.log_system(
        f"El servidor se cerró solo. Lo volvemos a encender en {int(CRASH_RESTART_DELAY_SECONDS)} segundos."
    )
    await asyncio.sleep(CRASH_RESTART_DELAY_SECONDS)
    if server_manager.is_running:
        return
    if reason := await _blocked_reason():
        await server_manager.log_system(f"No lo volvimos a encender porque {reason}.")
        return
    try:
        await _endpoints().launch_start_job(title="Volver a encender después de un cierre")
    except HTTPException as error:
        await server_manager.log_system(f"No se pudo volver a encender: {error.detail}")


async def daily_restart() -> None:
    """``daily_restart = HH:MM``: graceful restart with a chat warning; skipped when the server is off."""
    if not server_manager.is_running:
        logger.info("Daily restart skipped: the server is off.")
        return
    if reason := await _blocked_reason():
        logger.info("Daily restart skipped: %s.", reason)
        return
    warning = int(read_server_settings(settings).effective("restart_warning"))
    try:
        await _endpoints().launch_graceful_restart_job(warning, title="Reinicio diario")
    except HTTPException as error:
        await server_manager.log_system(f"No se pudo hacer el reinicio diario: {error.detail}")


def install() -> None:
    """Connect the automations; called once when the panel starts."""
    server_manager.add_crash_listener(restart_after_crash)
    scheduler_service.set_daily_restart_action(daily_restart)
