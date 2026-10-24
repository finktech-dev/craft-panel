"""Minimal interfaces that decouple the UI from a specific host."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.schemas.providers import ProviderDescriptor, ProviderStatus


@runtime_checkable
class PanelProvider(Protocol):
    """Observable adapter, explicitly registered by a future composition root.

    The contract does not grant process, file or network access on its own.
    Each concrete provider must declare its capabilities before it receives an
    action from the UI/API.
    """

    @property
    def descriptor(self) -> ProviderDescriptor: ...

    def status(self) -> ProviderStatus:
        """Read availability without starting services or changing the host."""


@runtime_checkable
class ProviderCatalog(Protocol):
    """Catalog of available adapters, independent of the operating system."""

    def list_providers(self) -> tuple[PanelProvider, ...]: ...
