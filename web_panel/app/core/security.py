"""Autenticación del administrador para HTTP y WebSockets."""

from __future__ import annotations

import secrets
import base64
import contextlib
import io
import ipaddress
import json
import os
import time
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pyotp
import qrcode
from fastapi import Depends, HTTPException, Request, WebSocket, status

from app.core.config import settings

_SESSION_ADMIN_KEY: Final = "is_admin"
_SESSION_CSRF_KEY: Final = "csrf_token"
_MAX_FAILED_ATTEMPTS: Final = 5
_LOCKOUT_SECONDS: Final = 15 * 60
_ATTEMPT_WINDOW_SECONDS: Final = 15 * 60


class TwoFactorError(RuntimeError):
    """Error de configuración o verificación TOTP."""


class TOTPManager:
    """Almacena localmente el secreto TOTP fuera del control de versiones."""

    def __init__(self, secret_path: Path) -> None:
        self._secret_path = secret_path

    @property
    def is_enabled(self) -> bool:
        state = self._read_state()
        return bool(state and state.get("enabled") is True)

    def begin_setup(self) -> str:
        secret = pyotp.random_base32()
        self._write_state({"secret": secret, "enabled": False})
        return secret

    def provisioning_qr_base64(self, secret: str) -> str:
        uri = pyotp.TOTP(secret).provisioning_uri(name="Administrador", issuer_name="Panel Minecraft")
        image = qrcode.make(uri)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def verify_setup_code(self, code: str) -> bool:
        state = self._read_state()
        if not state or state.get("enabled") is True:
            raise TwoFactorError("No hay una configuración 2FA pendiente.")
        if not self._verify_code(state, code):
            return False
        self._write_state({"secret": state["secret"], "enabled": True})
        return True

    def verify_login_code(self, code: str | None) -> bool:
        if not self.is_enabled:
            return True
        state = self._read_state()
        return bool(state and code and self._verify_code(state, code))

    def _read_state(self) -> dict[str, object] | None:
        if not self._secret_path.is_file():
            return None
        try:
            data = json.loads(self._secret_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise TwoFactorError("No se pudo leer la configuración 2FA local.") from error
        if not isinstance(data, dict) or not isinstance(data.get("secret"), str):
            raise TwoFactorError("La configuración 2FA local no es válida.")
        return data

    def _write_state(self, state: dict[str, object]) -> None:
        self._secret_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._secret_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(state), encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, self._secret_path)

    @staticmethod
    def _verify_code(state: Mapping[str, object], code: str) -> bool:
        secret = state.get("secret")
        return isinstance(secret, str) and bool(pyotp.TOTP(secret).verify(code, valid_window=1))


@dataclass(slots=True)
class _AttemptState:
    timestamps: deque[float]
    locked_until: float = 0.0


class LoginAttemptTracker:
    """Límite local en memoria por IP para reducir intentos de PIN/TOTP."""

    def __init__(self) -> None:
        self._attempts: defaultdict[str, _AttemptState] = defaultdict(lambda: _AttemptState(deque()))

    def retry_after(self, client_ip: str) -> int:
        state = self._attempts[client_ip]
        remaining = state.locked_until - time.monotonic()
        if remaining > 0:
            return max(1, int(remaining))
        if state.locked_until:
            state.locked_until = 0.0
            state.timestamps.clear()
        return 0

    def record_failure(self, client_ip: str) -> int:
        now = time.monotonic()
        state = self._attempts[client_ip]
        while state.timestamps and now - state.timestamps[0] > _ATTEMPT_WINDOW_SECONDS:
            state.timestamps.popleft()
        state.timestamps.append(now)
        if len(state.timestamps) >= _MAX_FAILED_ATTEMPTS:
            state.locked_until = now + _LOCKOUT_SECONDS
            return _LOCKOUT_SECONDS
        return 0

    def reset(self, client_ip: str) -> None:
        self._attempts.pop(client_ip, None)


def is_valid_admin_pin(candidate: str) -> bool:
    """Compara secretos sin revelar diferencias de tiempo observables."""
    assert settings.admin_pin is not None
    return secrets.compare_digest(candidate, settings.admin_pin.get_secret_value())


def client_ip(request: Request) -> str:
    remote_host = request.client.host if request.client else "unknown"
    try:
        is_loopback_proxy = ipaddress.ip_address(remote_host).is_loopback
    except ValueError:
        is_loopback_proxy = False
    if not is_loopback_proxy:
        return remote_host

    cloudflare_ip = request.headers.get("cf-connecting-ip", "").strip()
    if cloudflare_ip:
        try:
            return str(ipaddress.ip_address(cloudflare_ip))
        except ValueError:
            pass
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    try:
        return str(ipaddress.ip_address(forwarded_for))
    except ValueError:
        return remote_host


def _has_admin_session(session: Mapping[str, object]) -> bool:
    return session.get(_SESSION_ADMIN_KEY) is True


def request_has_admin_session(request: Request) -> bool:
    """Indica si una petición HTML tiene una sesión de administrador válida."""
    return _has_admin_session(request.session)


def get_csrf_token(request: Request) -> str | None:
    token = request.session.get(_SESSION_CSRF_KEY)
    return token if isinstance(token, str) else None


def has_valid_csrf_token(request: Request) -> bool:
    expected_token = get_csrf_token(request)
    supplied_token = request.headers.get("x-csrf-token", "")
    return bool(expected_token and supplied_token and secrets.compare_digest(expected_token, supplied_token))


async def get_current_admin(
    request: Request,
) -> str:
    """Dependencia para rutas REST administrativas.

    Sólo acepta la sesión firmada del navegador. El PIN nunca funciona como
    token reutilizable en rutas administrativas.
    """
    if _has_admin_session(request.session):
        return "session"
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Autenticación de administrador requerida.",
    )


async def websocket_is_admin(websocket: WebSocket) -> bool:
    """Equivalente WebSocket de la dependencia REST para proteger la consola."""
    session = websocket.scope.get("session", {})
    if not isinstance(session, Mapping) or not _has_admin_session(session):
        return False
    expected_token = session.get(_SESSION_CSRF_KEY)
    supplied_token = websocket.query_params.get("csrf", "")
    return isinstance(expected_token, str) and bool(supplied_token) and secrets.compare_digest(expected_token, supplied_token)


def mark_session_as_admin(request: Request) -> None:
    """Marca la sesión actual; SessionMiddleware firma la cookie resultante."""
    request.session.clear()
    request.session[_SESSION_ADMIN_KEY] = True
    request.session[_SESSION_CSRF_KEY] = secrets.token_urlsafe(32)


def clear_admin_session(request: Request) -> None:
    """Invalida la sesión del navegador actual."""
    request.session.clear()


assert settings.totp_secret_path is not None
totp_manager = TOTPManager(settings.totp_secret_path)
login_attempt_tracker = LoginAttemptTracker()
