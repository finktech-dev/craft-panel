"""Cross-cutting HTTP controls for the admin session."""

from __future__ import annotations

import json

from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import HTTPConnection, Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.core.security import (
    has_valid_csrf_token,
    is_allowed_host,
    is_same_origin,
    request_has_admin_session,
    request_is_https,
)

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_CSRF_EXEMPT_PATHS = {"/api/auth/login"}
_MEBIBYTE = 1024 * 1024
_DEFAULT_BODY_LIMIT = 1 * _MEBIBYTE
# Path prefix -> maximum request body. Mods are streamed to disk and capped
# again by the service; config files may be large TOML/JSON documents.
_BODY_LIMITS = (
    ("/api/mods/upload", 1024 * _MEBIBYTE + _MEBIBYTE),
    ("/api/configs/", 8 * _MEBIBYTE),
)


class _BodyTooLarge(Exception):
    pass


def _body_limit_for(path: str) -> int:
    for prefix, limit in _BODY_LIMITS:
        if path.startswith(prefix):
            return limit
    return _DEFAULT_BODY_LIMIT


async def _send_json(send: Send, status_code: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status_code,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})


class RequestGuardMiddleware:
    """Outermost guard: Host allow-list (DNS rebinding) and request body limits.

    Implemented as plain ASGI so it also covers WebSockets and can stop an
    oversized upload while it streams, before the multipart parser spools it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if not is_allowed_host(headers.get("host")):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await _send_json(send, 400, "Dirección del panel no permitida.")
            return
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return

        limit = _body_limit_for(scope.get("path", ""))
        declared = headers.get("content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > limit):
            await _send_json(send, 413, "El archivo o la solicitud es demasiado grande.")
            return

        received = 0
        response_started = False
        # SessionMiddleware sets its cookie inside this layer, so the Secure
        # flag for HTTPS-through-a-tunnel is added here, on the way out.
        upgrade_cookies = not settings.effective_cookie_secure and request_is_https(HTTPConnection(scope))

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                if upgrade_cookies:
                    message["headers"] = _secure_cookie_headers(message.get("headers", []))
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not response_started:
                await _send_json(send, 413, "El archivo o la solicitud es demasiado grande.")


class SecurityHeadersAndCsrfMiddleware(BaseHTTPMiddleware):
    """Block CSRF for sessions and add defensive headers to the panel."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        if request.method in _UNSAFE_METHODS and request.url.path.startswith("/api/"):
            # Cross-site requests are refused even before login (login CSRF).
            if not is_same_origin(request):
                return JSONResponse({"detail": "Solicitud administrativa inválida."}, status_code=403)
            if (
                request.url.path not in _CSRF_EXEMPT_PATHS
                and request_has_admin_session(request)
                and not has_valid_csrf_token(request)
            ):
                return JSONResponse({"detail": "Solicitud administrativa inválida."}, status_code=403)

        response = await call_next(request)
        is_https = settings.effective_cookie_secure or request_is_https(request)

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), microphone=(), usb=(), payment=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        if is_https:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        host = request.headers.get("host", "")
        websocket_sources = f"ws://{host} wss://{host}" if host else ""
        response.headers.setdefault(
            "Content-Security-Policy",
            # No inline scripts or on* handlers anywhere: page code lives in /static/js.
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            # Player heads and Modrinth icons are the only remote images.
            "img-src 'self' data: https://mc-heads.net https://cdn.modrinth.com; "
            f"connect-src 'self' {websocket_sources}; object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        if not request.url.path.startswith("/static/"):
            # Every page and API answer may carry private data (players, IPs, tokens).
            response.headers.setdefault("Cache-Control", "no-store")
        return response


def _secure_cookie_headers(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    """Add ``Secure`` to cookies when the browser came in over HTTPS (tunnel/proxy)."""
    updated: list[tuple[bytes, bytes]] = []
    for name, value in headers:
        if name.lower() == b"set-cookie" and b"secure" not in {part.strip().lower() for part in value.split(b";")}:
            value = value + b"; secure"
        updated.append((name, value))
    return updated
