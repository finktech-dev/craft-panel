"""Small, protected actions for the first-run wizard."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_admin
from app.schemas.onboarding import InstallJavaRequest, InstallServerRequest, OnboardingStatus
from app.services.installer_service import InstallerServiceError, installer_service
from app.services.java_runtime_service import JavaRuntimeServiceError, java_runtime_service
from app.services.onboarding_service import onboarding_service

router = APIRouter(prefix="/onboarding", tags=["onboarding"], dependencies=[Depends(get_current_admin)])


@router.get("/status", response_model=OnboardingStatus)
async def onboarding_status() -> OnboardingStatus:
    return onboarding_service.status()


@router.post("/install", status_code=status.HTTP_201_CREATED)
async def install_server(payload: InstallServerRequest) -> dict[str, str]:
    try:
        await installer_service.install_server(
            flavor=payload.flavor,
            minecraft_version=payload.minecraft_version,
            accept_eula=payload.accept_eula,
        )
    except InstallerServiceError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    return {"message": "Servidor instalado. Ahora podés elegir la memoria y la conexión."}

@router.post("/java", status_code=status.HTTP_201_CREATED)
async def install_java(payload: InstallJavaRequest) -> dict[str, str]:
    try:
        message = await java_runtime_service.install_for(payload.minecraft_version)
    except JavaRuntimeServiceError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    return {"message": message}
