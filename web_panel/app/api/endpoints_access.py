"""Perfil de capacidades de la sesión administrativa.

Este endpoint es deliberadamente de sólo lectura. La autorización sigue siendo
la sesión firmada existente hasta que una futura migración introduzca cuentas y
roles persistentes de forma explícita.
"""

from fastapi import APIRouter, Depends

from app.core.security import get_current_admin
from app.schemas.access import PanelAccessProfile
from app.services.access_service import access_service

router = APIRouter(prefix="/access", tags=["access"], dependencies=[Depends(get_current_admin)])


@router.get("/me", response_model=PanelAccessProfile)
async def current_access_profile() -> PanelAccessProfile:
    """Expone las capacidades del dueño autenticado, sin efecto lateral."""
    return access_service.owner_profile()
