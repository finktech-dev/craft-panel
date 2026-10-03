"""API para generar, listar y descargar esquemas de Create."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, Response

from app.core.security import get_current_admin
from app.schemas.schematic import SchematicGenerationResponse, SchematicItem, ViaductGenerationRequest
from app.services.banner_service import banner_service
from app.services.schematic_service import SchematicServiceError, schematic_service

router = APIRouter(prefix="/schematics", tags=["schematics"], dependencies=[Depends(get_current_admin)])
banner_router = APIRouter(prefix="/server", tags=["server"])


@router.get("", response_model=list[SchematicItem])
async def list_schematics() -> list[SchematicItem]:
    return await schematic_service.list_schematics()


@router.post("/generate-viaduct", response_model=SchematicGenerationResponse, status_code=status.HTTP_201_CREATED)
async def generate_viaduct(payload: ViaductGenerationRequest | None = None) -> SchematicGenerationResponse:
    try:
        schematic = await schematic_service.generate_railway_viaduct(
            (payload or ViaductGenerationRequest()).length_blocks
        )
    except SchematicServiceError as error:
        _raise_schematic_error(error)
    return SchematicGenerationResponse(success=True, schematic=schematic, message="Viaducto medieval generado.")


@router.post("/generate-station", response_model=SchematicGenerationResponse, status_code=status.HTTP_201_CREATED)
async def generate_station() -> SchematicGenerationResponse:
    try:
        schematic = await schematic_service.generate_train_station()
    except SchematicServiceError as error:
        _raise_schematic_error(error)
    return SchematicGenerationResponse(success=True, schematic=schematic, message="Estación medieval generada.")


@router.get("/{filename}/download", response_class=FileResponse)
async def download_schematic(filename: str) -> FileResponse:
    try:
        path = schematic_service.get_schematic_path(filename)
    except SchematicServiceError as error:
        _raise_schematic_error(error)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe el esquema indicado.")
    return FileResponse(path=path, media_type="application/x-nbt", filename=path.name)


@router.get("/{filename}/preview")
async def preview_schematic(filename: str) -> dict[str, object]:
    try:
        return await asyncio.to_thread(schematic_service.get_schematic_voxels, filename)
    except SchematicServiceError as error:
        _raise_schematic_error(error)


@banner_router.get("/banner.png", include_in_schema=True)
async def server_banner() -> Response:
    return Response(
        content=banner_service.generate_status_banner(),
        media_type="image/png",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def _raise_schematic_error(error: SchematicServiceError) -> None:
    raise HTTPException(status_code=error.status_code, detail=str(error)) from error
