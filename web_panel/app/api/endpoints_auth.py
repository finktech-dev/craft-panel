"""Inicio de sesión, 2FA y limitación de intentos del administrador."""

from fastapi import APIRouter, HTTPException, Request, status

from app.core.security import (
    TwoFactorError,
    client_ip,
    clear_admin_session,
    is_valid_admin_pin,
    login_attempt_tracker,
    mark_session_as_admin,
    totp_manager,
)
from app.core.security import get_current_admin
from fastapi import Depends
from app.schemas.auth import TOTPSetupResponse, TOTPVerifyRequest, TwoFactorStatus
from app.schemas.server import LoginRequest, LoginResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request) -> LoginResponse:
    """Valida el PIN y deja una cookie de sesión firmada y HttpOnly."""
    remote_ip = client_ip(request)
    retry_after = login_attempt_tracker.retry_after(remote_ip)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Demasiados intentos. Probá de nuevo en {retry_after} segundos.",
            headers={"Retry-After": str(retry_after)},
        )
    try:
        valid_totp = totp_manager.verify_login_code(payload.totp_code)
    except TwoFactorError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    if not is_valid_admin_pin(payload.pin) or not valid_totp:
        lockout = login_attempt_tracker.record_failure(remote_ip)
        detail = "PIN o código 2FA inválido."
        headers = {"Retry-After": str(lockout)} if lockout else None
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS if lockout else status.HTTP_401_UNAUTHORIZED,
            detail=detail if not lockout else "Demasiados intentos. La IP fue bloqueada durante 15 minutos.",
            headers=headers,
        )
    login_attempt_tracker.reset(remote_ip)
    mark_session_as_admin(request)
    return LoginResponse(success=True, message="Sesión de administrador iniciada.")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> None:
    """Cierra sólo la sesión de este navegador."""
    clear_admin_session(request)


@router.get("/2fa/status", response_model=TwoFactorStatus)
async def two_factor_status() -> TwoFactorStatus:
    """Expone sólo si el segundo factor está activo, nunca el secreto."""
    try:
        return TwoFactorStatus(enabled=totp_manager.is_enabled)
    except TwoFactorError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error


@router.post("/2fa/setup", response_model=TOTPSetupResponse, dependencies=[Depends(get_current_admin)])
async def setup_two_factor() -> TOTPSetupResponse:
    """Crea una configuración pendiente; se activa al verificar un código."""
    try:
        secret = totp_manager.begin_setup()
        return TOTPSetupResponse(
            qr_code_base64=totp_manager.provisioning_qr_base64(secret),
            message="Escaneá el QR y verificá el código de seis dígitos para activar 2FA.",
        )
    except (OSError, TwoFactorError) as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error


@router.post("/2fa/verify", response_model=TwoFactorStatus, dependencies=[Depends(get_current_admin)])
async def verify_two_factor(payload: TOTPVerifyRequest) -> TwoFactorStatus:
    try:
        if not totp_manager.verify_setup_code(payload.code):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Código 2FA inválido.")
    except TwoFactorError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return TwoFactorStatus(enabled=True)
