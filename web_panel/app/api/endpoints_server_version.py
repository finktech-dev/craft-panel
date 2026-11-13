"""Change the version of a server that already exists."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.endpoints_jobs import accepted, start_job
from app.core.security import get_current_admin
from app.schemas.job import JobAccepted
from app.schemas.onboarding import ChangeVersionRequest
from app.services.backup_service import BACKUP_STEPS, BackupNotFoundError, backup_service
from app.services.installer_service import CHANGE_VERSION_STEPS, InstallerServiceError, installer_service
from app.services.job_service import JobReporter
from app.services.progress import StepPlan

router = APIRouter(prefix="/server", tags=["server-version"], dependencies=[Depends(get_current_admin)])

# Folders kept in the copy taken before changing version, on top of the world.
_BACKUP_INCLUDES = ("mods", "config")


@router.post("/change-version", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def change_version(payload: ChangeVersionRequest) -> JobAccepted:
    """Replace the server's runtime with another Minecraft version, keeping its loader.

    When ``make_backup`` is set, a verified copy of the world (plus mods and config) is
    made first; if that copy fails, the version is not changed.
    """
    try:
        installer_service.change_version_preflight()
    except InstallerServiceError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    if payload.make_backup and backup_service.is_busy:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Hay una copia de seguridad en curso. Esperá a que termine y probá de nuevo.",
        )

    steps: StepPlan = (*BACKUP_STEPS, *CHANGE_VERSION_STEPS) if payload.make_backup else CHANGE_VERSION_STEPS

    async def work(reporter: JobReporter) -> dict:
        if payload.make_backup:
            try:
                await backup_service.create_backup(progress=reporter, extra_includes=_BACKUP_INCLUDES)
            except BackupNotFoundError:
                # Nothing to copy yet (the server has no world); go on with the change.
                reporter.say("Todavía no hay un mundo que copiar; seguimos con el cambio.")
        label = await installer_service.change_version(
            payload.minecraft_version,
            delete_world=payload.delete_world,
            progress=reporter,
        )
        reporter.done_message = f"Listo. Tu servidor ahora es {label}." + (
            " Empezás con un mundo nuevo." if payload.delete_world else " El mundo quedó igual."
        )
        return {"minecraft_version": payload.minecraft_version, "label": label}

    job = start_job("change_version", "Cambiar la versión del servidor", steps, work)
    return accepted(job, "Empezamos a cambiar la versión del servidor.")
