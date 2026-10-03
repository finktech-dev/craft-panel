"""API protegida para administrar mods locales y el catálogo Modrinth."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.core.security import get_current_admin
from app.schemas.mod import (
    ClientPackExportResponse,
    ModInstallRequest,
    ModItem,
    ModrinthSearchHit,
    ModToggleResponse,
)
from app.services.mod_service import ModServiceError, mod_service

router = APIRouter(prefix="/mods", tags=["mods"], dependencies=[Depends(get_current_admin)])


@router.get("", response_model=list[ModItem])
async def list_mods() -> list[ModItem]:
    return await mod_service.list_mods()


@router.post("/{filename}/toggle", response_model=ModToggleResponse)
async def toggle_mod(filename: str) -> ModToggleResponse:
    try:
        return await mod_service.toggle_mod(filename)
    except ModServiceError as error:
        _raise_mod_error(error)


@router.post("/upload", response_model=ModItem, status_code=status.HTTP_201_CREATED)
async def upload_mod(file: UploadFile = File(...)) -> ModItem:
    try:
        return await mod_service.upload_mod(file)
    except ModServiceError as error:
        _raise_mod_error(error)


@router.delete("/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mod(filename: str) -> None:
    try:
        await mod_service.delete_mod(filename)
    except ModServiceError as error:
        _raise_mod_error(error)


@router.get("/search", response_model=list[ModrinthSearchHit])
async def search_modrinth(query: str) -> list[ModrinthSearchHit]:
    try:
        return await mod_service.search_modrinth(query)
    except ModServiceError as error:
        _raise_mod_error(error)


@router.post("/install", response_model=ModItem, status_code=status.HTTP_201_CREATED)
async def install_modrinth_mod(payload: ModInstallRequest) -> ModItem:
    try:
        return await mod_service.install_modrinth_mod(payload.project_id, payload.version_id)
    except ModServiceError as error:
        _raise_mod_error(error)


@router.post("/export-client-pack", response_model=ClientPackExportResponse)
async def export_client_pack() -> ClientPackExportResponse:
    try:
        export_path = await mod_service.export_client_pack()
    except ModServiceError as error:
        _raise_mod_error(error)
    return ClientPackExportResponse(
        filename=export_path.name,
        size_mb=round(export_path.stat().st_size / (1024 * 1024), 2),
        message="Modpack generado correctamente.",
    )


@router.get("/download-client-pack", response_class=FileResponse)
async def download_client_pack() -> FileResponse:
    export_path = mod_service.client_pack_path
    if not export_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El modpack todavía no fue generado.")
    return FileResponse(
        path=export_path,
        media_type="application/zip",
        filename=export_path.name,
    )


def _raise_mod_error(error: ModServiceError) -> None:
    raise HTTPException(status_code=error.status_code, detail=str(error)) from error
