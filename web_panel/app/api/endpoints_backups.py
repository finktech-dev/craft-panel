"""Endpoints protegidos de backups y consulta del Crash Doctor."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.core.security import get_current_admin
from app.core.rate_limit import rate_limit
from app.schemas.backup import BackupAuditResponse, BackupCreateResponse, BackupItem, BackupSafetyOverview
from app.schemas.crash import CrashReportSummary
from app.services.backup_service import BackupServiceError, backup_service
from app.services.crash_analyzer import crash_analyzer

router = APIRouter(prefix="/backups", tags=["backups"], dependencies=[Depends(get_current_admin)])
crash_router = APIRouter(prefix="/server", tags=["crash"], dependencies=[Depends(get_current_admin)])


@router.get("", response_model=list[BackupItem])
async def list_backups() -> list[BackupItem]:
    return await backup_service.list_backups()


@router.get("/overview", response_model=BackupSafetyOverview)
async def backup_safety_overview() -> BackupSafetyOverview:
    """Devuelve integridad, procedencia y preparación; no modifica copias ni mundos."""
    return await backup_service.safety_overview()


@router.post(
    "",
    response_model=BackupCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("backups-create", 6, 600))],
)
async def create_backup() -> BackupCreateResponse:
    _raise_if_busy()
    try:
        backup = await backup_service.create_backup()
    except BackupServiceError as error:
        _raise_backup_error(error)
    return BackupCreateResponse(success=True, backup=backup, message="Backup creado correctamente.")


@router.post("/audit", response_model=BackupAuditResponse, dependencies=[Depends(rate_limit("backups-audit", 4, 300))])
async def audit_backups() -> BackupAuditResponse:
    _raise_if_busy()
    try:
        return await backup_service.audit_and_purge_backups()
    except (BackupServiceError, OSError) as error:
        _raise_backup_error(error if isinstance(error, BackupServiceError) else BackupServiceError(str(error)))


@router.post("/{filename}/restore", response_model=BackupCreateResponse)
async def restore_backup(filename: str) -> BackupCreateResponse:
    try:
        backup = await backup_service.restore_backup(filename)
    except BackupServiceError as error:
        _raise_backup_error(error)
    return BackupCreateResponse(
        success=True,
        backup=backup,
        message="Mundo restaurado. El servidor quedó detenido y listo para iniciar.",
    )


@router.delete("/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backup(filename: str) -> None:
    try:
        await backup_service.delete_backup(filename)
    except BackupServiceError as error:
        _raise_backup_error(error)


@router.get("/{filename}/download", response_class=FileResponse)
async def download_backup(filename: str) -> FileResponse:
    try:
        backup_path = backup_service.get_backup_path(filename)
    except BackupServiceError as error:
        _raise_backup_error(error)
    if not backup_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe el backup indicado.")
    return FileResponse(path=backup_path, media_type="application/zip", filename=backup_path.name)


@crash_router.get("/crash-report", response_model=CrashReportSummary)
async def get_crash_report() -> CrashReportSummary:
    report = await crash_analyzer.get_latest_crash_report()
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay crash-reports disponibles.")
    return report


def _raise_if_busy() -> None:
    """Queueing more copies behind a running one only wastes disk and CPU."""
    if backup_service.is_busy:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay una operación de backups en curso. Esperá a que termine.",
        )


def _raise_backup_error(error: BackupServiceError) -> None:
    raise HTTPException(status_code=error.status_code, detail=str(error)) from error
