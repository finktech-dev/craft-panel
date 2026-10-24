"""Neutral contracts for panel hosts and adapters.

These models describe an integration; they hold no paths, commands,
credentials or connection to the current server.
"""

from typing import Literal

from pydantic import BaseModel, Field

ProviderKind = Literal["local_process", "docker", "remote_agent", "demo"]
ProviderCapability = Literal[
    "runtime.discover", "server.observe", "server.control", "backups.observe",
    "backups.manage", "players.manage", "tunnel.manage",
]


class ProviderDescriptor(BaseModel):
    """Identity and declared scope of an installable adapter."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=80)
    kind: ProviderKind
    capabilities: tuple[ProviderCapability, ...]
    documentation_url: str | None = None


class ProviderStatus(BaseModel):
    """Observable status; reveals no host settings or secrets."""

    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    state: Literal["ready", "unavailable", "not_configured"]
    message: str
