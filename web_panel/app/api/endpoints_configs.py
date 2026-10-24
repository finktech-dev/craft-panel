"""Routes for the offline mod configuration editor."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.security import get_current_admin, request_is_direct_loopback
from app.schemas.universal import ConfigDocument, ConfigEditorInfo, ConfigFile, ConfigSaveRequest
from app.services.config_service import ConfigServiceError, config_service

router = APIRouter(tags=["configs"], dependencies=[Depends(get_current_admin)])


@router.get("/configs", response_model=list[ConfigFile])
async def configs() -> list[ConfigFile]:
    return await config_service.list_files()


@router.get("/config-editor", response_model=ConfigEditorInfo)
async def config_editor(request: Request) -> ConfigEditorInfo:
    """Whether "Abrir" can use this computer's text editor: only for a browser on the same PC."""
    editor = config_service.system_editor()
    return ConfigEditorInfo(can_open_locally=bool(editor) and request_is_direct_loopback(request), editor_name=editor)


@router.post("/config-editor/open/{filepath:path}")
async def config_open_locally(filepath: str, request: Request) -> dict[str, str]:
    # Opening a window on the host only makes sense for someone sitting at it;
    # through a tunnel or another device it would pop up where nobody is looking.
    if not request_is_direct_loopback(request):
        raise HTTPException(409, "Esto solo funciona desde la computadora donde corre el panel. Editalo acá en el panel.")
    try:
        editor = await config_service.open_in_system_editor(filepath)
    except ConfigServiceError as error:
        raise HTTPException(error.status_code, str(error)) from error
    return {"message": f"Se abrió en {editor}. Guardá ahí y reiniciá el servidor para que se note el cambio.", "editor": editor}


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
