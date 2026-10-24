"""Autenticación del administrador para HTTP y WebSockets."""

from __future__ import annotations

import base64
import datetime as _dt
import io
import ipaddress
import json
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

import pyotp
import qrcode
from fastapi import HTTPException, Request, WebSocket, status
from starlette.requests import HTTPConnection

from app.core.config import settings
from app.core.passwords import verify_password
from app.core.path_safety import write_private_text

_SESSION_ADMIN_KEY: Final = "is_admin"
_SESSION_CSRF_KEY: Final = "csrf_token"
_SESSION_ID_KEY: Final = "sid"
_SESSION_ISSUED_KEY: Final = "issued_at"
_MAX_FAILED_ATTEMPTS: Final = 5
_LOCKOUT_SECONDS: Final = 15 * 60
_ATTEMPT_WINDOW_SECONDS: Final = 15 * 60
# Backstop against attackers rotating forwarded IPs: after this many failures
# from anywhere, remote logins pause. The owner at the PC (direct loopback)
# can always sign in.
_GLOBAL_MAX_FAILED_ATTEMPTS: Final = 30
_FORWARDING_HEADERS: Final = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip", "cf-connecting-ip")
_LOOPBACK_NAMES: Final = frozenset({"localhost", "127.0.0.1", "::1"})
_QUICK_TUNNEL_SUFFIX: Final = ".trycloudflare.com"


class TwoFactorError(RuntimeError):
    """Error de configuración o verificación TOTP."""


class TOTPManager:
    """Almacena localmente el secreto TOTP fuera del control de versiones.

    A new setup is kept as ``pending_secret`` so starting a re-enrollment never
    disables an active second factor until the new code is verified.
    """

    def __init__(self, secret_path: Path) -> None:
        self._secret_path = secret_path
        self._last_used_counter = -1

    @property
    def is_enabled(self) -> bool:
        state = self._read_state()
        return bool(state and state.get("enabled") is True and isinstance(state.get("secret"), str))

    def begin_setup(self) -> str:
        secret = pyotp.random_base32()
        state = self._read_state() or {}
        if state.get("enabled") is True and isinstance(state.get("secret"), str):
            self._write_state({"secret": state["secret"], "enabled": True, "pending_secret": secret})
        else:
            self._write_state({"pending_secret": secret, "enabled": False})
        return secret

    @staticmethod
    def provisioning_uri(secret: str) -> str:
        return pyotp.TOTP(secret).provisioning_uri(name="Administrador", issuer_name="Craft Panel")

    def provisioning_qr_base64(self, secret: str) -> str:
        uri = self.provisioning_uri(secret)
        image = qrcode.make(uri)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def verify_setup_code(self, code: str) -> bool:
        state = self._read_state()
        pending = state.get("pending_secret") if state else None
        if pending is None and state and state.get("enabled") is not True:
            pending = state.get("secret")  # setup started by an older panel version
        if not isinstance(pending, str):
            raise TwoFactorError("No hay una configuración 2FA pendiente.")
        counter = self._matching_counter(pending, code)
        if counter is None:
            return False
        self._write_state({"secret": pending, "enabled": True})
        # The code that confirmed the setup cannot be replayed to sign in.
        self._last_used_counter = max(self._last_used_counter, counter)
        return True

    def disable(self) -> None:
        """Turn the second factor off and drop any pending setup.

        Callers must have checked a current code first (``verify_login_code``)
        when the factor is active.
        """
        try:
            self._secret_path.unlink(missing_ok=True)
        except OSError as error:
            raise TwoFactorError("No se pudo apagar la verificación en dos pasos.") from error

    def verify_login_code(self, code: str | None) -> bool:
        if not self.is_enabled:
            return True
        state = self._read_state()
        secret = state.get("secret") if state else None
        if not isinstance(secret, str) or not code:
            return False
        counter = self._matching_counter(secret, code)
        # Each code is accepted once: a sniffed or shoulder-surfed code cannot be replayed.
        if counter is None or counter <= self._last_used_counter:
            return False
        self._last_used_counter = counter
        return True

    def _read_state(self) -> dict[str, object] | None:
        if not self._secret_path.is_file():
            return None
        try:
            data = json.loads(self._secret_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise TwoFactorError("No se pudo leer la configuración 2FA local.") from error
        if not isinstance(data, dict) or not (
            isinstance(data.get("secret"), str) or isinstance(data.get("pending_secret"), str)
        ):
            raise TwoFactorError("La configuración 2FA local no es válida.")
        return data

    def _write_state(self, state: dict[str, object]) -> None:
        write_private_text(self._secret_path, json.dumps(state))

    @staticmethod
    def _matching_counter(secret: str, code: str) -> int | None:
        if not code or len(code) != 6 or not code.isdigit():
            return None
        totp = pyotp.TOTP(secret)
        current = totp.timecode(_dt.datetime.now(tz=_dt.UTC))
        for counter in (current - 1, current, current + 1):
            if secrets.compare_digest(totp.generate_otp(counter), code):
                return counter
        return None


@dataclass(slots=True)
class _AttemptState:
    timestamps: deque[float]
    locked_until: float = 0.0


class LoginAttemptTracker:
    """Límite local en memoria por IP para reducir intentos de PIN/TOTP."""

    def __init__(self, max_attempts: int = _MAX_FAILED_ATTEMPTS) -> None:
        self._max_attempts = max_attempts
        self._attempts: defaultdict[str, _AttemptState] = defaultdict(lambda: _AttemptState(deque()))

    def retry_after(self, client_ip: str) -> int:
        state = self._attempts.get(client_ip)
        if state is None:
            return 0
        remaining = state.locked_until - time.monotonic()
        if remaining > 0:
            return max(1, int(remaining))
        if state.locked_until:
            self._attempts.pop(client_ip, None)
        return 0

    def record_failure(self, client_ip: str) -> int:
        now = time.monotonic()
        self._prune(now)
        state = self._attempts[client_ip]
        while state.timestamps and now - state.timestamps[0] > _ATTEMPT_WINDOW_SECONDS:
            state.timestamps.popleft()
        state.timestamps.append(now)
        if len(state.timestamps) >= self._max_attempts:
            state.locked_until = now + _LOCKOUT_SECONDS
            return _LOCKOUT_SECONDS
        return 0

    def reset(self, client_ip: str) -> None:
        self._attempts.pop(client_ip, None)

    def _prune(self, now: float) -> None:
        """Keep memory bounded when many distinct (possibly forged) IPs show up."""
        if len(self._attempts) < 10_000:
            return
        for key in [
            key for key, state in self._attempts.items()
            if state.locked_until < now and (not state.timestamps or now - state.timestamps[-1] > _ATTEMPT_WINDOW_SECONDS)
        ]:
            self._attempts.pop(key, None)


def is_valid_admin_pin(candidate: str) -> bool:
    """Check the administrator password against its scrypt hash.

    The hash is always computed, and the final comparison is constant-time
    (see ``app.core.passwords.verify_password``). This is CPU-bound: call it
    from a worker thread inside async code.
    """
    stored_hash = settings.admin_password_hash
    if stored_hash is None:
        return False
    return verify_password(candidate, stored_hash)


def _is_loopback(host: str | None) -> bool:
    try:
        return host is not None and ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def client_ip(request: HTTPConnection) -> str:
    """Best-effort client address for rate limiting.

    Forwarded headers are only considered when the TCP peer is this machine
    (cloudflared or a local reverse proxy). The right-most X-Forwarded-For
    entry is the one appended by that proxy; left-most entries are client
    controlled.
    """
    remote_host = request.client.host if request.client else "unknown"
    if not _is_loopback(remote_host):
        return remote_host

    cloudflare_ip = request.headers.get("cf-connecting-ip", "").strip()
    if cloudflare_ip:
        try:
            return str(ipaddress.ip_address(cloudflare_ip))
        except ValueError:
            pass
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
    try:
        return str(ipaddress.ip_address(forwarded_for))
    except ValueError:
        return remote_host


def _host_without_port(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):
        return host[1 : host.find("]")] if "]" in host else ""
    if host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host.rstrip(".")


def is_allowed_host(host_header: str | None) -> bool:
    """Reject Host headers that could come from a DNS rebinding attack.

    IP literals and ``localhost`` cannot be rebound by an attacker. Domain
    names must be the Cloudflare Quick Tunnel domain or listed explicitly in
    ``MINECRAFT_ALLOWED_HOSTS`` (e.g. a reverse proxy domain).
    """
    if not host_header:
        return False
    host = _host_without_port(host_header)
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if host in _LOOPBACK_NAMES or host == settings.panel_host.lower():
        return True
    if host.endswith(_QUICK_TUNNEL_SUFFIX):
        return True
    for allowed in settings.allowed_hosts:
        candidate = allowed.strip().lower().rstrip(".")
        if candidate.startswith("*.") and host.endswith(candidate[1:]):
            return True
        if host == candidate:
            return True
    return False


def is_same_origin(connection: HTTPConnection) -> bool:
    """CSRF/CSWSH check: a browser Origin, when present, must match the Host."""
    origin = connection.headers.get("origin")
    if origin is None:
        # Older browsers omit Origin on same-origin requests; Fetch Metadata
        # still tells us when a request was triggered by another site.
        return connection.headers.get("sec-fetch-site", "same-origin") in {"same-origin", "none"}
    if origin == "null":
        return False
    parsed = urlsplit(origin)
    origin_netloc = parsed.netloc.lower()
    if not origin_netloc:
        return False
    if origin_netloc == connection.headers.get("host", "").lower():
        return True
    # A local reverse proxy may rewrite Host to 127.0.0.1 and keep the public
    # name in X-Forwarded-Host; only trust that header from this machine.
    peer = connection.client.host if connection.client else None
    forwarded_host = connection.headers.get("x-forwarded-host", "").split(",")[-1].strip().lower()
    if forwarded_host and _is_loopback(peer) and origin_netloc == forwarded_host:
        return True
    # The Quick Tunnel this panel started itself (in case cloudflared rewrites Host).
    from app.services.cloudflare_service import cloudflare_quick_tunnel_service

    tunnel_url = cloudflare_quick_tunnel_service.status().public_url
    if tunnel_url and _is_loopback(peer) and origin_netloc == urlsplit(tunnel_url).netloc.lower():
        return True
    # Domains the owner listed explicitly (never IP literals or shared tunnel domains).
    origin_host = _host_without_port(origin_netloc)
    return any(
        origin_host == allowed.strip().lower().rstrip(".")
        or (allowed.strip().startswith("*.") and origin_host.endswith(allowed.strip().lower()[1:]))
        for allowed in settings.allowed_hosts
    )


def request_is_direct_loopback(connection: HTTPConnection) -> bool:
    """True only for a browser on this PC talking to the panel without any proxy."""
    peer = connection.client.host if connection.client else None
    if not _is_loopback(peer):
        return False
    if any(header in connection.headers for header in _FORWARDING_HEADERS):
        return False
    return _host_without_port(connection.headers.get("host", "")) in _LOOPBACK_NAMES


def request_is_https(connection: HTTPConnection) -> bool:
    """Whether the browser reached the panel over HTTPS (directly or via a local proxy)."""
    if connection.url.scheme in {"https", "wss"}:
        return True
    peer = connection.client.host if connection.client else None
    if not _is_loopback(peer):
        return False
    forwarded_proto = connection.headers.get("x-forwarded-proto", "").split(",")[-1].strip().lower()
    return forwarded_proto == "https" or '"scheme":"https"' in connection.headers.get("cf-visitor", "").replace(" ", "")


@dataclass(slots=True)
class _RevokedSessions:
    entries: dict[str, float]

    def revoke(self, session_id: str) -> None:
        now = time.time()
        if len(self.entries) > 5_000:
            self.entries = {key: until for key, until in self.entries.items() if until > now}
        self.entries[session_id] = now + settings.session_max_age_seconds

    def is_revoked(self, session_id: str) -> bool:
        return session_id in self.entries


_revoked_sessions = _RevokedSessions({})


def _has_admin_session(session: Mapping[str, object]) -> bool:
    if session.get(_SESSION_ADMIN_KEY) is not True:
        return False
    issued_at = session.get(_SESSION_ISSUED_KEY)
    session_id = session.get(_SESSION_ID_KEY)
    if not isinstance(issued_at, int) or not isinstance(session_id, str):
        return False
    # Absolute lifetime: the signed cookie is re-issued on every response, so
    # without this check an active stolen cookie would never expire.
    age = time.time() - issued_at
    if age < -60 or age > settings.session_max_age_seconds:
        return False
    return not _revoked_sessions.is_revoked(session_id)


def request_has_admin_session(request: Request) -> bool:
    """Indica si una petición HTML tiene una sesión de administrador válida."""
    return _has_admin_session(request.session)


def get_csrf_token(request: Request) -> str | None:
    token = request.session.get(_SESSION_CSRF_KEY)
    return token if isinstance(token, str) else None


def has_valid_csrf_token(request: Request) -> bool:
    expected_token = get_csrf_token(request)
    supplied_token = request.headers.get("x-csrf-token", "")
    return bool(
        expected_token
        and supplied_token
        and secrets.compare_digest(expected_token.encode("utf-8"), supplied_token.encode("utf-8"))
    )


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
    if not is_same_origin(websocket):
        return False
    session = websocket.scope.get("session", {})
    if not isinstance(session, Mapping) or not _has_admin_session(session):
        return False
    expected_token = session.get(_SESSION_CSRF_KEY)
    supplied_token = websocket.query_params.get("csrf", "")
    return (
        isinstance(expected_token, str)
        and bool(supplied_token)
        and secrets.compare_digest(expected_token.encode("utf-8"), supplied_token.encode("utf-8"))
    )


def mark_session_as_admin(request: Request) -> None:
    """Marca la sesión actual; SessionMiddleware firma la cookie resultante.

    The session is rebuilt from scratch with a new id and CSRF token so no
    value set before login survives (session fixation).
    """
    request.session.clear()
    request.session[_SESSION_ADMIN_KEY] = True
    request.session[_SESSION_ID_KEY] = secrets.token_urlsafe(16)
    request.session[_SESSION_ISSUED_KEY] = int(time.time())
    request.session[_SESSION_CSRF_KEY] = secrets.token_urlsafe(32)


def clear_admin_session(request: Request) -> None:
    """Invalida la sesión del navegador actual, también si alguien copió la cookie."""
    session_id = request.session.get(_SESSION_ID_KEY)
    if isinstance(session_id, str):
        _revoked_sessions.revoke(session_id)
    request.session.clear()


assert settings.totp_secret_path is not None
totp_manager = TOTPManager(settings.totp_secret_path)
login_attempt_tracker = LoginAttemptTracker()
global_login_failures = LoginAttemptTracker(max_attempts=_GLOBAL_MAX_FAILED_ATTEMPTS)
GLOBAL_LOGIN_KEY: Final = "*"
