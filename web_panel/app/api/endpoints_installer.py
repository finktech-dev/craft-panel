"""Retired legacy installer endpoint.

First-run installation must happen in the onboarding wizard so accepting the
Minecraft EULA is always an explicit user action.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_admin

router = APIRouter(prefix="/server", tags=["installer"], dependencies=[Depends(get_current_admin)])


@router.post("/install-runtime", status_code=status.HTTP_410_GONE)
async def install_runtime() -> None:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Use the guided setup page to install a server and explicitly accept the Minecraft EULA.",
    )
