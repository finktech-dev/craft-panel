"""Declarative contracts for the panel's capabilities.

They do not represent stored users and do not change the current session. They
are a stable base so the UI and future adapters can talk about permissions per
capability instead of assuming paths, operating systems or a single server.
"""

from typing import Literal

from pydantic import BaseModel, Field


class PanelCapability(BaseModel):
    """An action or area that an interface can show to the host."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$")
    label: str
    description: str
    risk: Literal["read", "operate", "destructive"]


class PanelAccessProfile(BaseModel):
    """Effective profile of the current admin session.

    For now the panel keeps exactly its single-admin-session model. ``role`` is
    neither stored nor used to authorize actions: the response lets new
    clients prepare a capability-based UI without introducing accounts,
    secrets or migrations.
    """

    role: Literal["owner"] = "owner"
    capabilities: tuple[PanelCapability, ...]
    authorization_model: Literal["single_admin_session"] = "single_admin_session"

