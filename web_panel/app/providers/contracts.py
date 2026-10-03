"""Interfaces mínimas para desacoplar la UI de un host concreto."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.schemas.providers import ProviderDescriptor, ProviderStatus


@runtime_checkable
class PanelProvider(Protocol):
    """Adapter observable registrado explícitamente por una futura composición.

    El contrato no autoriza procesos, archivos o red por sí mismo. Cada
    provider concreto debe declarar sus capacidades antes de recibir una acción
    desde UI/API.
    """

    @property
    def descriptor(self) -> ProviderDescriptor: ...

    def status(self) -> ProviderStatus:
        """Lee disponibilidad sin iniciar servicios ni mutar el host."""


@runtime_checkable
class ProviderCatalog(Protocol):
    """Catálogo de adapters disponibles, independiente del sistema operativo."""

    def list_providers(self) -> tuple[PanelProvider, ...]: ...
