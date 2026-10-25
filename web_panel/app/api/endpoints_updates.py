"""Whether a newer Craft Panel release is out (check_updates in craftpanel.txt)."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.security import get_current_admin
from app.services.server_settings_file import read_server_settings
from app.services.update_service import update_service

router = APIRouter(prefix="/updates", tags=["updates"], dependencies=[Depends(get_current_admin)])


@router.get("")
async def get_update_status() -> dict[str, Any]:
    file_settings = await asyncio.to_thread(read_server_settings, settings)
    status = await update_service.status(enabled=bool(file_settings.effective("check_updates")))
    return asdict(status)
