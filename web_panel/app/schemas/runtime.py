"""Respuestas del instalador y del túnel Playit."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RuntimeInstallResponse(BaseModel):
    success: bool
    message: str


class TunnelStatus(BaseModel):
    is_running: bool
    public_address: str | None
    message: str
    started_at: datetime | None = None
    last_exit_code: int | None = None
    last_error: str | None = None
    needs_setup: bool = False
    claim_url: str | None = None


class FriendConnectionInfo(BaseModel):
    """Información para compartir el servidor, sin controlar ningún túnel.

    La dirección puede provenir de Playit, una configuración manual o el
    fallback local. El panel nunca promete que una dirección manual sea
    alcanzable desde Internet: sólo comunica de dónde la obtuvo.
    """

    public_address: str
    server_port: int
    source: Literal["playit_detected", "manual", "configured", "local_only"]
    can_share_with_friends: bool
    tunnel_active: bool
    is_custom: bool
    message: str
    next_step: str


class TunnelSetupRequest(BaseModel):
    """Clave privada del agente, recibida solamente por una sesión de administrador."""

    agent_secret: str = Field(min_length=16, max_length=4_096)


class TunnelLogLine(BaseModel):
    """Una línea observable del agente Playit, apta para la consola web."""

    timestamp: datetime
    level: str
    message: str


class CloudflareQuickTunnelStatus(BaseModel):
    """Estado del enlace temporal HTTPS del panel."""

    is_running: bool
    public_url: str | None
    message: str
    started_at: datetime | None = None
    last_error: str | None = None


class JavaRuntimeStatus(BaseModel):
    """Un Java encontrado en el host, sin modificar su instalación."""

    state: Literal["available", "missing", "unusable"]
    executable: str | None = None
    version: str | None = None
    major_version: int | None = None
    message: str


class MinecraftInstallationStatus(BaseModel):
    """Huella de un servidor Minecraft local; no enumera mundos ni mods."""

    state: Literal["detected", "not_detected"]
    root: str
    loader: Literal["neoforge", "forge", "fabric", "paper", "vanilla", "unknown"] | None = None
    start_script: str | None = None
    message: str


class AccountProtectionStatus(BaseModel):
    """Configuración de acceso del servidor, sin leer cuentas ni credenciales locales."""

    state: Literal["online_accounts", "whitelist", "unrestricted", "unknown"]
    online_mode: bool | None = None
    whitelist_enabled: bool | None = None
    message: str


class HostRuntimeDiscovery(BaseModel):
    """Contrato de descubrimiento portable y estrictamente de sólo lectura."""

    operating_system: Literal["windows", "linux", "macos", "other"]
    java: JavaRuntimeStatus
    minecraft: MinecraftInstallationStatus
    accounts: AccountProtectionStatus
    safe_to_inspect: bool = True
