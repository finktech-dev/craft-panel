"""Protected endpoints for backups and Crash Doctor queries."""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.api.endpoints_jobs import accepted, start_job
from app.core.security import get_current_admin
from app.core.rate_limit import rate_limit
from app.schemas.backup import BackupAuditResponse, BackupItem, BackupSafetyOverview
from app.schemas.crash import CrashReportSummary
from app.schemas.job import JobAccepted
from app.services.backup_service import (
    BACKUP_STEPS,
    RESTORE_STEPS,
    BackupConflictError,
    BackupServiceError,
    backup_service,
)
from app.services.crash_analyzer import crash_analyzer
from app.services.job_service import JobReporter
from app.services.runtime_guard import ServerActiveError, require_server_stopped
from app.services.server_process import server_manager

_BUSY_MESSAGE = "Ya hay una operación de backups en curso. Esperá a que termine."

router = APIRouter(prefix="/backups", tags=["backups"], dependencies=[Depends(get_current_admin)])
crash_router = APIRouter(prefix="/server", tags=["crash"], dependencies=[Depends(get_current_admin)])


@router.get("", response_model=list[BackupItem])
async def list_backups() -> list[BackupItem]:
    return await backup_service.list_backups()


@router.get("/overview", response_model=BackupSafetyOverview)
async def backup_safety_overview() -> BackupSafetyOverview:
    """Return integrity, origin and readiness; never modifies backups or worlds."""
    return await backup_service.safety_overview()


@router.post(
    "",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("backups-create", 6, 600))],
)
async def create_backup() -> JobAccepted:
    """Start a backup job; follow it with ``GET /api/jobs/{job_id}`` or the WebSocket."""
    _raise_if_busy()
    if not backup_service.world_directory.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe el mundo para respaldar.")
    job = start_job("backup", "Copia del mundo", BACKUP_STEPS, backup_job_work, success_message="Copia lista.")
    return accepted(job, "Empezamos la copia. Se puede seguir jugando mientras tanto.")


async def backup_job_work(reporter: JobReporter) -> dict:
    # The request checked this already; a scheduled copy may have started since.
    if backup_service.is_busy:
        raise BackupConflictError(_BUSY_MESSAGE)
    backup = await backup_service.create_backup(progress=reporter)
    reporter.done_message = f"Copia lista: {backup.size_mb:.1f} MB.".replace(".", ",", 1)
    return {"backup": backup.model_dump(mode="json")}


@router.post("/audit", response_model=BackupAuditResponse, dependencies=[Depends(rate_limit("backups-audit", 4, 300))])
async def audit_backups() -> BackupAuditResponse:
    _raise_if_busy()
    try:
        return await backup_service.audit_and_purge_backups()
    except (BackupServiceError, OSError) as error:
        _raise_backup_error(error if isinstance(error, BackupServiceError) else BackupServiceError(str(error)))


class RestoreRequest(BaseModel):
    # Put back the [backup_include] files saved in the copy too (never [protected] ones).
    restore_server_files: bool = False


@router.post("/{filename}/restore", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def restore_backup(filename: str, request: RestoreRequest | None = None) -> JobAccepted:
    """Validate the request right away, then replace the world in a job."""
    restore_server_files = bool(request and request.restore_server_files)
    try:
        require_server_stopped(server_manager, "volver a una copia")
    except ServerActiveError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    try:
        backup_path = backup_service.get_backup_path(filename)
    except BackupServiceError as error:
        _raise_backup_error(error)
    if not backup_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe el backup indicado.")
    _raise_if_busy()

    async def work(reporter: JobReporter) -> dict:
        if backup_service.is_busy:
            raise BackupConflictError(_BUSY_MESSAGE)
        backup = await backup_service.restore_backup(
            filename, progress=reporter, restore_server_files=restore_server_files
        )
        return {"backup": backup.model_dump(mode="json")}

    job = start_job(
        "restore",
        "Volver a una copia",
        RESTORE_STEPS,
        work,
        success_message="Listo, el mundo volvió a esa copia. El servidor quedó apagado; encendelo cuando quieras.",
    )
    return accepted(job, "Empezamos a volver a esa copia.")


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
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_BUSY_MESSAGE)


def _raise_backup_error(error: BackupServiceError) -> None:
    raise HTTPException(status_code=error.status_code, detail=str(error)) from error
