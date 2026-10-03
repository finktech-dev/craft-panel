"""Entrypoint ASGI del panel de administración."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.router import router as api_router
from app.core.config import settings
from app.core.security import TwoFactorError, get_csrf_token, request_has_admin_session, totp_manager
from app.core.security_middleware import SecurityHeadersAndCsrfMiddleware
from app.services.server_process import server_manager
from app.services.cloudflare_service import cloudflare_quick_tunnel_service
from app.services.playit_service import playit_service
from app.services.scheduler_service import scheduler_service
from app.websocket.terminal import router as terminal_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Conserva el proceso de Minecraft consistente al apagar el panel."""
    scheduler_service.start()
    try:
        yield
    except asyncio.CancelledError:
        # Uvicorn cancela el lifespan al recibir Ctrl+C en Windows. Consumir
        # esta cancelación evita una traza falsa tras un apagado correcto.
        logging.getLogger("panel").info("Se recibió una interrupción; apagando el panel ordenadamente.")
    finally:
        scheduler_service.shutdown()
        try:
            await server_manager.shutdown()
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await playit_service.shutdown()
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await cloudflare_quick_tunnel_service.shutdown()
        except (asyncio.CancelledError, Exception):
            pass



app = FastAPI(
    title="Panel del servidor Minecraft",
    version="0.1.0",
    lifespan=lifespan,
)
# SessionMiddleware queda por fuera del control CSRF para que este último pueda
# leer la sesión firmada antes de procesar una acción administrativa.
app.add_middleware(SecurityHeadersAndCsrfMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret.get_secret_value(),
    session_cookie="minecraft_panel_session",
    max_age=settings.session_max_age_seconds,
    same_site="strict",
    https_only=settings.effective_cookie_secure,
)

assert settings.static_directory is not None
assert settings.panel_directory is not None
app.mount("/static", StaticFiles(directory=str(settings.static_directory)), name="static")
templates = Jinja2Templates(directory=str(settings.panel_directory / "templates"))
app.include_router(api_router)
app.include_router(terminal_router)


@app.get("/health", tags=["system"])
async def healthcheck() -> dict[str, str]:
    """Sonda mínima que no intenta iniciar ni inspeccionar el servidor."""
    return {"status": "ok", "server_state": server_manager.state}


def _template_context(request: Request, current_page: str) -> dict[str, object]:
    try:
        two_factor_enabled = totp_manager.is_enabled
    except TwoFactorError:
        two_factor_enabled = False
    return {
        "request": request,
        "current_page": current_page,
        "is_admin": request_has_admin_session(request),
        "public_address": settings.server_public_address or "IP no configurada",
        "minecraft_version": settings.minecraft_version,
        "two_factor_enabled": two_factor_enabled,
        "csrf_token": get_csrf_token(request) if request_has_admin_session(request) else None,
        "initial_admin_pin": settings.admin_pin.get_secret_value() if settings.admin_pin_generated_this_start else None,
    }


def _require_html_session(request: Request) -> RedirectResponse | None:
    if not request_has_admin_session(request):
        return RedirectResponse(url="/", status_code=303)
    return None


@app.get("/", include_in_schema=False)
async def dashboard(request: Request):
    context = _template_context(request, "dashboard")
    template_name = "dashboard.html" if context["is_admin"] else "login.html"
    return templates.TemplateResponse(request=request, name=template_name, context=context)


@app.get("/onboarding", include_in_schema=False)
async def onboarding_page(request: Request):
    if redirect := _require_html_session(request):
        return redirect
    return templates.TemplateResponse(
        request=request, name="onboarding.html", context=_template_context(request, "onboarding")
    )

@app.get("/console", include_in_schema=False)
async def console_page(request: Request):
    if redirect := _require_html_session(request):
        return redirect
    return templates.TemplateResponse(
        request=request, name="console.html", context=_template_context(request, "console")
    )


@app.get("/mods", include_in_schema=False)
async def mods_page(request: Request):
    if redirect := _require_html_session(request):
        return redirect
    return templates.TemplateResponse(
        request=request, name="mods.html", context=_template_context(request, "mods")
    )


@app.get("/backups", include_in_schema=False)
async def backups_page(request: Request):
    if redirect := _require_html_session(request):
        return redirect
    return templates.TemplateResponse(
        request=request, name="backups.html", context=_template_context(request, "backups")
    )


@app.get("/schematics", include_in_schema=False)
async def schematics_page(request: Request):
    if redirect := _require_html_session(request):
        return redirect
    return templates.TemplateResponse(
        request=request, name="schematics.html", context=_template_context(request, "schematics")
    )

@app.get("/administration", include_in_schema=False)
async def administration_page(request: Request):
    if redirect := _require_html_session(request):
        return redirect
    return templates.TemplateResponse(request=request, name="administration.html", context=_template_context(request, "administration"))


@app.get("/worlds", include_in_schema=False)
async def worlds_page(request: Request):
    if redirect := _require_html_session(request):
        return redirect
    return templates.TemplateResponse(request=request, name="worlds.html", context=_template_context(request, "worlds"))


@app.get("/crashes", include_in_schema=False)
async def crashes_page(request: Request):
    if redirect := _require_html_session(request):
        return redirect
    return templates.TemplateResponse(request=request, name="crashes.html", context=_template_context(request, "crashes"))


@app.get("/setup", include_in_schema=False)
async def setup_page(request: Request):
    """Keep old bookmarks working while using the focused first-run wizard."""
    if redirect := _require_html_session(request):
        return redirect
    return RedirectResponse(url="/onboarding", status_code=303)