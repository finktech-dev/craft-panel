"""``server/craftpanel.txt`` from Ajustes: read it as fields or text, and save either way."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import get_current_admin
from app.services.server_process import server_manager
from app.services.server_settings_file import (
    FILENAME,
    KEYS,
    MAX_FILE_BYTES,
    SECTIONS,
    ServerFileSettings,
    SettingsFileError,
    normalize_path_text,
    server_settings_file,
)

router = APIRouter(prefix="/server", tags=["server"], dependencies=[Depends(get_current_admin)])


class SettingsFileUpdate(BaseModel):
    """Only the keys and lists present are changed; everything else in the file stays as it is."""

    values: dict[str, str] = Field(default_factory=dict, max_length=64)
    lists: dict[str, list[str]] = Field(default_factory=dict, max_length=16)


class SettingsFileRaw(BaseModel):
    raw: str = Field(max_length=MAX_FILE_BYTES)


class SettingsFileProblemInfo(BaseModel):
    line: int | None = None
    field: str | None = None
    message: str


class SettingsFileInfo(BaseModel):
    exists: bool
    filename: str = FILENAME
    raw: str
    values: dict[str, str]
    defaults: dict[str, str]
    lists: dict[str, list[str]]
    problems: list[SettingsFileProblemInfo] = Field(default_factory=list)
    server_running: bool = False
    stopped_only: list[str] = Field(default_factory=list)


def _server_busy() -> bool:
    return bool(server_manager.is_running or server_manager.lifecycle_operation)


def _info(file_settings: ServerFileSettings) -> SettingsFileInfo:
    return SettingsFileInfo(
        exists=file_settings.exists,
        raw=file_settings.raw,
        values={
            key: file_settings.texts.get(key, "" if file_settings.exists else spec.template_value)
            for key, spec in KEYS.items()
        },
        defaults={key: spec.default for key, spec in KEYS.items()},
        lists={name: list(file_settings.list_texts.get(name, ())) for name in SECTIONS},
        problems=[SettingsFileProblemInfo(**problem.as_dict()) for problem in file_settings.problems],
        server_running=_server_busy(),
        stopped_only=[key for key, spec in KEYS.items() if spec.needs_stopped_server],
    )


def _problem(error: SettingsFileError) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"message": str(error), "errors": [problem.as_dict() for problem in error.errors]},
    )


def _comparable(key: str, value: str | None) -> str:
    value = value or ""
    return normalize_path_text(value) if key == "java" else value.strip()


def _raise_if_stopped_only_values_change(current: ServerFileSettings, proposed: dict[str, str]) -> None:
    """``start_script`` and ``java`` are used when the server starts, so they only change with it off."""
    if not _server_busy():
        return
    for key, spec in KEYS.items():
        if spec.needs_stopped_server and key in proposed:
            if _comparable(key, proposed[key]) != _comparable(key, current.texts.get(key)):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Apagá el servidor para cambiar esto: el archivo para encender y Java se usan al encenderlo.",
                )


async def _after_save() -> None:
    """Apply what changes right away (schedules); the rest is read when it is used."""
    from app.services.scheduler_service import scheduler_service

    await asyncio.to_thread(scheduler_service.sync_with_settings_file)


@router.get("/settings-file", response_model=SettingsFileInfo)
async def get_settings_file() -> SettingsFileInfo:
    """craftpanel.txt as fields and as text; defaults when it does not exist yet (nothing is created)."""
    return _info(await asyncio.to_thread(server_settings_file.load, settings))


@router.put("/settings-file", response_model=SettingsFileInfo)
async def update_settings_file(payload: SettingsFileUpdate) -> SettingsFileInfo:
    current = await asyncio.to_thread(server_settings_file.load, settings)
    _raise_if_stopped_only_values_change(current, payload.values)
    try:
        saved = await asyncio.to_thread(server_settings_file.save_fields, settings, payload.values, payload.lists)
    except SettingsFileError as error:
        raise _problem(error) from error
    await _after_save()
    return _info(saved)


@router.put("/settings-file/raw", response_model=SettingsFileInfo)
async def update_settings_file_raw(payload: SettingsFileRaw) -> SettingsFileInfo:
    current = await asyncio.to_thread(server_settings_file.load, settings)
    try:
        proposed = await asyncio.to_thread(server_settings_file.check_raw, settings, payload.raw)
    except SettingsFileError as error:
        raise _problem(error) from error
    _raise_if_stopped_only_values_change(
        current, {key: proposed.texts.get(key, "") for key, spec in KEYS.items() if spec.needs_stopped_server}
    )
    try:
        saved = await asyncio.to_thread(server_settings_file.save_raw, settings, payload.raw)
    except SettingsFileError as error:
        raise _problem(error) from error
    await _after_save()
    return _info(saved)
