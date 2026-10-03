"""Contratos neutrales para hosts y adaptadores del panel.

Estos modelos describen una integración; no contienen rutas, comandos,
credenciales ni una conexión al servidor actual.
"""

from typing import Literal

from pydantic import BaseModel, Field

ProviderKind = Literal["local_process", "docker", "remote_agent", "demo"]
ProviderCapability = Literal[
    "runtime.discover", "server.observe", "server.control", "backups.observe",
    "backups.manage", "players.manage", "tunnel.manage",
]


class ProviderDescriptor(BaseModel):
    """Identidad y alcance declarativo de un adapter instalable."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=80)
    kind: ProviderKind
    capabilities: tuple[ProviderCapability, ...]
    documentation_url: str | None = None


class ProviderStatus(BaseModel):
    """Estado observable; no revela configuraciones ni secretos del host."""

    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    state: Literal["ready", "unavailable", "not_configured"]
    message: str
