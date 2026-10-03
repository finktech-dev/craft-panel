"""Host discovery and editable launch preferences for the first-run assistant."""

from __future__ import annotations

import json
import os

import psutil
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import get_current_admin
from app.schemas.runtime import HostRuntimeDiscovery
from app.services.runtime_discovery import runtime_discovery_service
from app.services.server_process import server_manager

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
    recommended_gb = max(1, min(64, min(total_gb - 2, available_gb - 1)))
    return total_gb, available_gb, recommended_gb


def _apply_ram_to_jvm_args(allocated_ram_gb: int) -> None:
    assert settings.server_directory is not None
    target = settings.server_directory / "user_jvm_args.txt"
    if not target.is_file():
        raise HTTPException(status_code=409, detail="No encontramos user_jvm_args.txt para aplicar la RAM al servidor.")
    lines = target.read_text(encoding="utf-8").splitlines()
    maximum_line = f"-Xmx{allocated_ram_gb}G"
    initial_line = f"-Xms{min(2, allocated_ram_gb)}G"
    found_maximum = found_initial = False
    updated: list[str] = []
    for line in lines:
        if line.strip().lower().startswith("-xmx"):
            updated.append(maximum_line)
            found_maximum = True
        elif line.strip().lower().startswith("-xms"):
            updated.append(initial_line)
            found_initial = True
        else:
            updated.append(line)
    if not found_initial:
        updated.append(initial_line)
    if not found_maximum:
        updated.append(maximum_line)
    temporary = target.with_suffix(".tmp")
    temporary.write_text("\n".join(updated) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def _settings_file():
    assert settings.panel_directory is not None
    return settings.panel_directory / ".launch_settings.json"


@router.get("/discovery", response_model=HostRuntimeDiscovery)
async def discover_host_runtime() -> HostRuntimeDiscovery:
    return runtime_discovery_service.discover()


@router.get("/launch-settings", response_model=LaunchSettings)
async def get_launch_settings() -> LaunchSettings:
    total_gb, available_gb, recommended_gb = _host_memory()
    return LaunchSettings(
        allocated_ram_gb=settings.allocated_ram_gb,
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
        raise HTTPException(status_code=422, detail=f"Esta computadora recomienda reservar recursos; elegí hasta {maximum} GB.")
    _apply_ram_to_jvm_args(payload.allocated_ram_gb)
    settings.allocated_ram_gb = payload.allocated_ram_gb
    settings.playit_enabled = payload.playit_enabled
    try:
        _settings_file().write_text(json.dumps({"allocated_ram_gb": payload.allocated_ram_gb, "playit_enabled": payload.playit_enabled}, indent=2), encoding="utf-8")
    except OSError as error:
        raise HTTPException(status_code=500, detail="No se pudo guardar la preferencia de RAM.") from error
    return LaunchSettings(
        allocated_ram_gb=settings.allocated_ram_gb,
        maximum_recommended_ram_gb=maximum,
        available_ram_gb=available_gb,
        total_ram_gb=total_gb,
        server_running=False,
        playit_enabled=settings.playit_enabled,
    )
