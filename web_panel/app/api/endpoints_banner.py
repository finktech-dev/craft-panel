"""Public status banner image (shown in Ajustes and embeddable in Discord or forums)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from app.services.banner_service import banner_service

banner_router = APIRouter(prefix="/server", tags=["server"])


@banner_router.get("/banner.png", include_in_schema=True)
async def server_banner() -> Response:
    return Response(
        content=banner_service.generate_status_banner(),
        media_type="image/png",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
