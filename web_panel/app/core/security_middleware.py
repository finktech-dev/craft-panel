"""Controles HTTP transversales para la sesión administrativa."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.security import has_valid_csrf_token, request_has_admin_session

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_CSRF_EXEMPT_PATHS = {"/api/auth/login"}


class SecurityHeadersAndCsrfMiddleware(BaseHTTPMiddleware):
    """Bloquea CSRF para sesiones y añade cabeceras defensivas al panel."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        if (
            request.method in _UNSAFE_METHODS
            and request.url.path.startswith("/api/")
            and request.url.path not in _CSRF_EXEMPT_PATHS
            and request_has_admin_session(request)
            and not has_valid_csrf_token(request)
        ):
            return JSONResponse({"detail": "Solicitud administrativa inválida."}, status_code=403)

        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), microphone=()")
        if settings.effective_cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
            "connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        if request.url.path.startswith("/api/") or request.url.path in {"/", "/console", "/mods", "/backups", "/schematics", "/administration"}:
            response.headers.setdefault("Cache-Control", "no-store")
        return response
