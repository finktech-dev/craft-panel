"""Guardrails shared by file operations that require the Minecraft process stopped."""

from __future__ import annotations

from typing import Protocol


class ServerState(Protocol):
    @property
    def is_running(self) -> bool: ...


class ServerActiveError(RuntimeError):
    """Raised before changing files that Minecraft may have open or cached."""

    status_code = 409


def require_server_stopped(manager: ServerState, operation: str) -> None:
    """Refuse unsafe offline-only operations without stopping Java implicitly."""
    if manager.is_running:
        raise ServerActiveError(
            f"No se puede {operation} mientras el servidor está encendido. "
            "Detenelo de forma normal y esperá a que figure apagado antes de reintentar."
        )
