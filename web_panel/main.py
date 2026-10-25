"""ASGI entry point of the admin panel."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import server_automation
from app.api.router import router as api_router
from app.core.config import settings
from app.core.navigation import NAV_COOKIE, nav_layout, parse_nav_cookie
from app.core.security import (
    TwoFactorError,
    get_csrf_token,
    request_has_admin_session,
    request_is_direct_loopback,
    totp_manager,
)
from app.core.security_middleware import RequestGuardMiddleware, SecurityHeadersAndCsrfMiddleware
from app.services.job_service import job_service
from app.services.server_process import server_manager
from app.services.cloudflare_service import cloudflare_quick_tunnel_service
from app.services.playit_service import playit_service
from app.services.protected_paths import ProtectedPathError
from app.services.scheduler_service import scheduler_service
from app.services.server_version_service import server_version_service
from app.websocket.terminal import router as terminal_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Keep the Minecraft process consistent when the panel shuts down."""
    server_automation.install()
    scheduler_service.start()
    # A server left running by the previous panel session is taken back before anything else.
    try:
        await server_manager.adopt_running_server()
    except Exception:  # noqa: BLE001 - the panel must open even if this fails
        logging.getLogger("panel").exception("Could not take back the running server")
    asyncio.create_task(server_automation.start_with_panel(), name="start-with-panel")
    try:
        yield
    except asyncio.CancelledError:
        # Uvicorn cancels the lifespan on Ctrl+C on Windows. Swallowing the
        # cancellation avoids a bogus traceback after a clean shutdown.
        logging.getLogger("panel").info("Se recibió una interrupción; apagando el panel ordenadamente.")
    finally:
        # Record jobs that this shutdown interrupts before anything else stops.
        job_service.shutdown()
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
    # The interactive API docs are not needed by the UI and only widen what an
    # Internet visitor can probe.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
# SessionMiddleware wraps the CSRF check so the latter can read the signed
# session before handling an admin action.
app.add_middleware(SecurityHeadersAndCsrfMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret.get_secret_value(),
    session_cookie="minecraft_panel_session",
    max_age=settings.session_max_age_seconds,
    same_site="strict",
    https_only=settings.effective_cookie_secure,
)
# Outermost: reject forged Host headers (DNS rebinding) and oversized bodies
# before sessions, routing or multipart parsing do any work.
app.add_middleware(RequestGuardMiddleware)

assert settings.static_directory is not None
assert settings.panel_directory is not None
app.mount("/static", StaticFiles(directory=str(settings.static_directory)), name="static")
templates = Jinja2Templates(directory=str(settings.panel_directory / "templates"))
templates.env.globals["nav_layout"] = nav_layout
app.include_router(api_router)
app.include_router(terminal_router)


@app.exception_handler(ProtectedPathError)
async def protected_path_handler(_: Request, error: ProtectedPathError) -> JSONResponse:
    """Any write the user protected in craftpanel.txt ends as a plain 409, wherever it was attempted."""
    return JSONResponse(status_code=409, content={"detail": str(error)})


@app.get("/health", tags=["system"])
async def healthcheck() -> dict[str, str]:
    """Minimal probe that never starts or inspects the server."""
    return {"status": "ok", "server_state": server_manager.state}


def _template_context(request: Request, current_page: str) -> dict[str, object]:
    try:
        two_factor_enabled = totp_manager.is_enabled
    except TwoFactorError:
        two_factor_enabled = False
    return {
        "request": request,
        "current_page": current_page,
        "nav_bar": parse_nav_cookie(request.cookies.get(NAV_COOKIE)),
        "is_admin": request_has_admin_session(request),
        "public_address": settings.effective_public_address,
        "brand_name": settings.effective_server_name or "Craft Panel",
        "minecraft_version": server_version_service.detect().minecraft_version or "",
        "two_factor_enabled": two_factor_enabled,
        "csrf_token": get_csrf_token(request) if request_has_admin_session(request) else None,
        # The first-run password is only ever shown to a browser on this PC,
        # never through a tunnel, reverse proxy or LAN address. It lives only
        # in memory (the file keeps a hash) and is dropped after the first login.
        "initial_admin_pin": (
            settings.initial_admin_password if request_is_direct_loopback(request) else None
        ),
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
async def schematics_page() -> RedirectResponse:
    # The schematics page was removed; old bookmarks land on the home page instead of a 404.
    return RedirectResponse(url="/", status_code=307)

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