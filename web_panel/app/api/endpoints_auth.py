"""Administrator login, 2FA and attempt rate limiting."""

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.rate_limit import rate_limit
from app.core.security import (
    GLOBAL_LOGIN_KEY,
    TwoFactorError,
    client_ip,
    clear_admin_session,
    get_current_admin,
    global_login_failures,
    is_valid_admin_pin,
    login_attempt_tracker,
    mark_session_as_admin,
    request_is_direct_loopback,
    totp_manager,
)
from app.schemas.auth import TOTPCurrentCodeRequest, TOTPSetupResponse, TOTPVerifyRequest, TwoFactorStatus
from app.schemas.server import LoginRequest, LoginResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _too_many_attempts(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Demasiados intentos. Probá de nuevo en {retry_after} segundos.",
        headers={"Retry-After": str(retry_after)},
    )


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request) -> LoginResponse:
    """Validate the PIN and set a signed, HttpOnly session cookie."""
    remote_ip = client_ip(request)
    # The owner sitting at the PC is never locked out by remote brute force.
    count_globally = not request_is_direct_loopback(request)
    retry_after = login_attempt_tracker.retry_after(remote_ip)
    if not retry_after and count_globally:
        retry_after = global_login_failures.retry_after(GLOBAL_LOGIN_KEY)
    if retry_after:
        raise _too_many_attempts(retry_after)
    try:
        # scrypt is CPU-bound; a worker thread keeps the console and WebSockets responsive.
        password_ok = await run_in_threadpool(is_valid_admin_pin, payload.pin)
        # The TOTP code is only checked (and consumed) once the PIN is right.
        valid = password_ok and totp_manager.verify_login_code(payload.totp_code)
    except TwoFactorError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    if not valid:
        lockout = login_attempt_tracker.record_failure(remote_ip)
        if count_globally:
            lockout = max(lockout, global_login_failures.record_failure(GLOBAL_LOGIN_KEY))
        detail = "PIN o código 2FA inválido."
        headers = {"Retry-After": str(lockout)} if lockout else None
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS if lockout else status.HTTP_401_UNAUTHORIZED,
            detail=detail if not lockout else "Demasiados intentos. La IP fue bloqueada durante 15 minutos.",
            headers=headers,
        )
    login_attempt_tracker.reset(remote_ip)
    try:
        # The first-run password stops being shown once someone signed in with it.
        settings.mark_admin_password_claimed()
    except OSError:
        pass  # only the "unclaimed" marker could not be cleared; the hash is unchanged
    mark_session_as_admin(request)
    return LoginResponse(success=True, message="Sesión de administrador iniciada.")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> None:
    """Log out this browser's session only."""
    clear_admin_session(request)


@router.get("/2fa/status", response_model=TwoFactorStatus)
async def two_factor_status() -> TwoFactorStatus:
    """Expose only whether the second factor is on, never the secret."""
    try:
        return TwoFactorStatus(enabled=totp_manager.is_enabled)
    except TwoFactorError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error


def _two_factor_attempt_key(request: Request) -> str:
    return f"2fa:{client_ip(request)}"


def _require_current_code(request: Request, payload: TOTPCurrentCodeRequest | None) -> None:
    """When 2FA is on, changing it needs a fresh code from the current app.

    A stolen session cookie alone must not be enough to replace or remove the
    second factor. Wrong codes count toward the same lockout as setup codes,
    and a code accepted here is consumed (it cannot be replayed to sign in).
    """
    attempt_key = _two_factor_attempt_key(request)
    if retry_after := login_attempt_tracker.retry_after(attempt_key):
        raise _too_many_attempts(retry_after)
    code = payload.code if payload else None
    try:
        if not totp_manager.is_enabled:
            return
        if not code or not totp_manager.verify_login_code(code):
            if lockout := login_attempt_tracker.record_failure(attempt_key):
                raise _too_many_attempts(lockout)
            # 400, not 401: the session is valid; the UI would treat 401 as "signed out".
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El código no es correcto. Escribí el que te muestra ahora la app.",
            )
    except TwoFactorError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    login_attempt_tracker.reset(attempt_key)


@router.post(
    "/2fa/setup",
    response_model=TOTPSetupResponse,
    dependencies=[Depends(get_current_admin), Depends(rate_limit("2fa-setup", 10, 600))],
)
async def setup_two_factor(
    request: Request, payload: TOTPCurrentCodeRequest | None = Body(default=None)
) -> TOTPSetupResponse:
    """Create a pending setup; it becomes active once a code is verified.

    Re-enrolling while 2FA is on requires a current code; the active factor
    keeps working until the new one is verified.
    """
    _require_current_code(request, payload)
    try:
        secret = totp_manager.begin_setup()
        return TOTPSetupResponse(
            qr_code_base64=totp_manager.provisioning_qr_base64(secret),
            manual_entry_key=secret,
            message="Escaneá el código QR y escribí los 6 números que te muestra la app.",
        )
    except (OSError, TwoFactorError) as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error


@router.post("/2fa/verify", response_model=TwoFactorStatus, dependencies=[Depends(get_current_admin)])
async def verify_two_factor(payload: TOTPVerifyRequest, request: Request) -> TwoFactorStatus:
    attempt_key = _two_factor_attempt_key(request)
    if retry_after := login_attempt_tracker.retry_after(attempt_key):
        raise _too_many_attempts(retry_after)
    try:
        if not totp_manager.verify_setup_code(payload.code):
            login_attempt_tracker.record_failure(attempt_key)
            # 400, not 401: the session is fine and the page must not bounce to the login screen.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El código no es correcto. Revisá la hora del celular y probá con el que se ve ahora.",
            )
    except TwoFactorError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    login_attempt_tracker.reset(attempt_key)
    return TwoFactorStatus(enabled=True)


@router.post(
    "/2fa/disable",
    response_model=TwoFactorStatus,
    dependencies=[Depends(get_current_admin), Depends(rate_limit("2fa-disable", 10, 600))],
)
async def disable_two_factor(
    request: Request, payload: TOTPCurrentCodeRequest | None = Body(default=None)
) -> TwoFactorStatus:
    """Turn off the second factor (or discard a half-finished setup).

    When 2FA is on, a current code is required.
    """
    _require_current_code(request, payload)
    try:
        totp_manager.disable()
    except TwoFactorError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    return TwoFactorStatus(enabled=False)
