"""Routes for the offline mod configuration editor."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_admin
from app.schemas.universal import ConfigDocument, ConfigFile, ConfigSaveRequest
from app.services.config_service import ConfigServiceError, config_service

router = APIRouter(tags=["configs"], dependencies=[Depends(get_current_admin)])


@router.get("/configs", response_model=list[ConfigFile])
async def configs() -> list[ConfigFile]:
    return await config_service.list_files()


@router.get("/configs/{filepath:path}", response_model=ConfigDocument)
async def config_read(filepath: str) -> ConfigDocument:
    try:
        return await config_service.read(filepath)
    except ConfigServiceError as error:
        raise HTTPException(error.status_code, str(error)) from error


@router.post("/configs/{filepath:path}", response_model=ConfigDocument)
async def config_save(filepath: str, payload: ConfigSaveRequest) -> ConfigDocument:
    try:
        return await config_service.save(filepath, payload.content, payload.changes)
    except ConfigServiceError as error:
        raise HTTPException(error.status_code, str(error)) from error
