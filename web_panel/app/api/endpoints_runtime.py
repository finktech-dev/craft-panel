"""Host discovery and editable launch preferences for the first-run assistant."""

from __future__ import annotations

import asyncio
import json
import os

import psutil
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import get_current_admin
from app.schemas.runtime import HostRuntimeDiscovery
from app.services.runtime_discovery import runtime_discovery_service
from app.services.jvm_args import JvmArgsMissingError, apply_ram
from app.services.server_process import server_manager
from app.services.server_settings_file import SettingsFileError, server_settings_file

router = APIRouter(prefix="/runtime", tags=["runtime"], dependencies=[Depends(get_current_admin)])


class LaunchSettings(BaseModel):
    allocated_ram_gb: int
    maximum_recommended_ram_gb: int
    available_ram_gb: int
    total_ram_gb: int
    server_running: bool
    playit_enabled: bool


class LaunchSettingsUpdate(BaseModel):
    allocated_ram_gb: int = Field(ge=1, le=64)
    playit_enabled: bool = True


def _host_memory() -> tuple[int, int, int]:
    memory = psutil.virtual_memory()
    total_gb = max(1, int(memory.total / (1024**3)))
    available_gb = max(1, int(memory.available / (1024**3)))
    recommended_gb = max(1, min(64, total_gb - 2 if total_gb > 3 else total_gb))
    return total_gb, available_gb, recommended_gb


def _apply_ram_to_jvm_args(allocated_ram_gb: int) -> None:
    try:
        apply_ram(settings, allocated_ram_gb)
    except JvmArgsMissingError as error:
        raise HTTPException(status_code=409, detail="No encontramos user_jvm_args.txt para aplicar la RAM al servidor.") from error


def _settings_file():
    assert settings.panel_directory is not None
    return settings.panel_directory / ".launch_settings.json"


@router.get("/discovery", response_model=HostRuntimeDiscovery)
async def discover_host_runtime() -> HostRuntimeDiscovery:
    # Each Java found is run once (java -version), so keep that off the event loop.
    return await asyncio.to_thread(runtime_discovery_service.discover)


@router.get("/launch-settings", response_model=LaunchSettings)
async def get_launch_settings() -> LaunchSettings:
    total_gb, available_gb, recommended_gb = _host_memory()
    return LaunchSettings(
        allocated_ram_gb=settings.effective_ram_gb,
        maximum_recommended_ram_gb=recommended_gb,
        available_ram_gb=available_gb,
        total_ram_gb=total_gb,
        server_running=server_manager.is_running,
        playit_enabled=settings.playit_enabled,
    )


@router.put("/launch-settings", response_model=LaunchSettings)
async def update_launch_settings(payload: LaunchSettingsUpdate) -> LaunchSettings:
    if server_manager.is_running:
        raise HTTPException(status_code=409, detail="Apagá el servidor antes de cambiar la RAM.")
    total_gb, available_gb, maximum = _host_memory()
    if payload.allocated_ram_gb > maximum:
        raise HTTPException(status_code=422, detail=f"Esta computadora recomienda reservar al menos 2 GB para el sistema; elegí hasta {maximum} GB.")
    _apply_ram_to_jvm_args(payload.allocated_ram_gb)
    # When craftpanel.txt exists, its memory value is the source of truth: keep it in step.
    if server_settings_file.load(settings).exists:
        try:
            server_settings_file.save_fields(settings, values={"memory": f"{payload.allocated_ram_gb}G"})
        except SettingsFileError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    settings.allocated_ram_gb = payload.allocated_ram_gb
    settings.playit_enabled = payload.playit_enabled
    try:
        _settings_file().write_text(json.dumps({"allocated_ram_gb": payload.allocated_ram_gb, "playit_enabled": payload.playit_enabled}, indent=2), encoding="utf-8")
    except OSError as error:
        raise HTTPException(status_code=500, detail="No se pudo guardar la preferencia de RAM.") from error
    return LaunchSettings(
        allocated_ram_gb=settings.effective_ram_gb,
        maximum_recommended_ram_gb=maximum,
        available_ram_gb=available_gb,
        total_ram_gb=total_gb,
        server_running=False,
        playit_enabled=settings.playit_enabled,
    )
