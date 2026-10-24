"""Capability profile of the admin session.

This endpoint is deliberately read-only. Authorization is still the existing
signed session until a future migration explicitly introduces persistent
accounts and roles.
"""

from fastapi import APIRouter, Depends

from app.core.security import get_current_admin
from app.schemas.access import PanelAccessProfile
from app.services.access_service import access_service

router = APIRouter(prefix="/access", tags=["access"], dependencies=[Depends(get_current_admin)])


@router.get("/me", response_model=PanelAccessProfile)
async def current_access_profile() -> PanelAccessProfile:
    """Expose the authenticated owner's capabilities, with no side effects."""
    return access_service.owner_profile()
