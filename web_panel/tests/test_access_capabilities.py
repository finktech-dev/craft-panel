"""Regression coverage for the non-mutating access/capability foundation."""

import pytest

from app.api.endpoints_access import current_access_profile
from app.schemas.access import PanelCapability
from app.services.access_service import AccessService


def test_owner_capabilities_have_unique_stable_ids_and_document_risk() -> None:
    profile = AccessService().owner_profile()
    capability_ids = [capability.id for capability in profile.capabilities]

    assert profile.role == "owner"
    assert profile.authorization_model == "single_admin_session"
    assert len(capability_ids) == len(set(capability_ids))
    assert {capability.risk for capability in profile.capabilities} == {"read", "operate", "destructive"}
    assert "runtime:discover" in capability_ids
    assert "connections:manage" in capability_ids


@pytest.mark.asyncio
async def test_access_endpoint_returns_the_declared_owner_profile() -> None:
    profile = await current_access_profile()

    assert profile.capabilities
    assert all(isinstance(capability, PanelCapability) for capability in profile.capabilities)
