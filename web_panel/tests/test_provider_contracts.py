"""Contract coverage for providers that must stay host-agnostic."""

from app.providers.contracts import PanelProvider
from app.providers.demo import DemoProvider


def test_demo_provider_is_read_only_and_uses_no_host_specific_paths() -> None:
    provider = DemoProvider()
    descriptor = provider.descriptor

    assert isinstance(provider, PanelProvider)
    assert descriptor.kind == "demo"
    assert descriptor.capabilities == ("runtime.discover", "server.observe", "backups.observe")
    assert "\\" not in descriptor.id
    assert "/" not in descriptor.id
    assert provider.status().state == "not_configured"
