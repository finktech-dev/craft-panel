"""Upload, preview or clear the server-list icon (``server-icon.png``)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response

from app.core.security import get_current_admin
from app.services.server_icon_service import ServerIconError, server_icon_service

router = APIRouter(prefix="/server/icon", tags=["server"])


@router.get("/status", dependencies=[Depends(get_current_admin)])
async def icon_status() -> dict[str, bool]:
    return {"has_icon": server_icon_service.has_icon()}


@router.get(".png", include_in_schema=False)
async def icon_image() -> Response:
    data = server_icon_service.read_icon()
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.post("", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(get_current_admin)])
async def set_icon(file: UploadFile = File(...)) -> Response:
    try:
        await server_icon_service.set_icon(file)
    except ServerIconError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(get_current_admin)])
async def clear_icon() -> Response:
    try:
        await server_icon_service.remove_icon()
    except ServerIconError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
