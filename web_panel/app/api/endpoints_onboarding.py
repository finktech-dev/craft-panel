"""Small, protected actions for the first-run wizard."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.endpoints_jobs import accepted, start_job
from app.core.security import get_current_admin
from app.schemas.job import JobAccepted
from app.schemas.onboarding import (
    AvailableVersion,
    AvailableVersionsResponse,
    InstallFlavor,
    InstallJavaRequest,
    InstallServerRequest,
    OnboardingStatus,
)
from app.services.installer_service import INSTALL_SERVER_STEPS, InstallerServiceError, installer_service
from app.services.java_runtime_service import INSTALL_JAVA_STEPS, JavaRuntimeServiceError, java_runtime_service
from app.services.job_service import JobReporter
from app.services.onboarding_service import onboarding_service
from app.services.version_catalog_service import VersionCatalogError, version_catalog_service

router = APIRouter(prefix="/onboarding", tags=["onboarding"], dependencies=[Depends(get_current_admin)])


@router.get("/status", response_model=OnboardingStatus)
async def onboarding_status(
    minecraft_version: str | None = Query(default=None, pattern=r"^\d+\.\d+(?:\.\d+)?$"),
) -> OnboardingStatus:
    return await onboarding_service.status(minecraft_version)


@router.get("/versions", response_model=AvailableVersionsResponse)
async def available_versions(
    flavor: InstallFlavor = Query(default="vanilla"),
    include_snapshots: bool = Query(default=False),
) -> AvailableVersionsResponse:
    """Installable Minecraft versions for a flavor, newest first, from the official sources."""
    try:
        catalog = await version_catalog_service.list_versions(flavor, include_snapshots)
    except VersionCatalogError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    return AvailableVersionsResponse(
        flavor=catalog.flavor,
        include_snapshots=catalog.include_snapshots,
        latest=catalog.latest,
        versions=[
            AvailableVersion(
                minecraft_version=entry.minecraft_version,
                stable=entry.stable,
                java_major=entry.java_major,
                loader_version=entry.loader_version,
            )
            for entry in catalog.versions
        ],
        source=catalog.source,
        fetched_at=catalog.fetched_at,
    )


@router.post("/install", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def install_server(payload: InstallServerRequest) -> JobAccepted:
    """Check the request right away, then download and install in a job."""
    try:
        installer_service.preflight(payload.minecraft_version, accept_eula=payload.accept_eula)
    except InstallerServiceError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error

    async def work(reporter: JobReporter) -> dict:
        await installer_service.install_server(
            flavor=payload.flavor,
            minecraft_version=payload.minecraft_version,
            accept_eula=payload.accept_eula,
            progress=reporter,
        )
        return {"flavor": payload.flavor, "minecraft_version": payload.minecraft_version}

    job = start_job(
        "install_server",
        "Instalar el servidor",
        INSTALL_SERVER_STEPS,
        work,
        success_message="Servidor instalado. Ahora podés elegir la memoria y la conexión.",
    )
    return accepted(job, "Empezamos a instalar el servidor.")


@router.post("/java", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def install_java(payload: InstallJavaRequest) -> JobAccepted:
    try:
        java_runtime_service.preflight(payload.minecraft_version)
    except JavaRuntimeServiceError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error

    async def work(reporter: JobReporter) -> dict:
        reporter.done_message = await java_runtime_service.install_for(payload.minecraft_version, progress=reporter)
        return {"minecraft_version": payload.minecraft_version}

    job = start_job("install_java", "Descargar Java", INSTALL_JAVA_STEPS, work)
    return accepted(job, "Empezamos a descargar Java.")
