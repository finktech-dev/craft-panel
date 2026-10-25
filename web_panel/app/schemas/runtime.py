"""Installer and Playit tunnel responses."""

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
    # The official Playit app for Windows, which runs on its own as the "playitd" service.
    external_agent: Literal["running", "stopped", "not_installed"] = "not_installed"
    external_autostart: bool | None = None


class FriendAddressRequest(BaseModel):
    """An address the host copied from Playit (or another service) to share with friends."""

    public_address: str = Field(min_length=1, max_length=260)


class FriendAddressResponse(BaseModel):
    public_address: str
    saved_to: Literal["craftpanel.txt", "panel"]
    message: str


class VpnAddress(BaseModel):
    """The server's address through one VPN, e.g. Tailscale 100.101.2.3:25565."""

    name: str
    address: str


class FriendConnectionInfo(BaseModel):
    """Information for sharing the server, without controlling any tunnel.

    The address may come from Playit, a manual setting or the local fallback.
    The panel never promises that a manual address is reachable from the
    Internet: it only reports where it got it from.
    """

    public_address: str
    server_port: int
    source: Literal["playit_detected", "manual", "configured", "vpn", "local_only"]
    can_share_with_friends: bool
    tunnel_active: bool
    is_custom: bool
    message: str
    next_step: str
    # Addresses through each VPN on this PC; friends on the same VPN can use them too.
    vpn_addresses: list[VpnAddress] = Field(default_factory=list)


class TunnelSetupRequest(BaseModel):
    """Private agent key, accepted only from an admin session."""

    agent_secret: str = Field(min_length=16, max_length=4_096)


class TunnelLogLine(BaseModel):
    """One observable Playit agent line, safe for the web console."""

    timestamp: datetime
    level: str
    message: str


class CloudflareQuickTunnelStatus(BaseModel):
    """Status of the panel's temporary HTTPS link."""

    is_running: bool
    public_url: str | None
    message: str
    started_at: datetime | None = None
    last_error: str | None = None


class JavaRuntimeStatus(BaseModel):
    """A Java found on the host, without modifying its installation."""

    state: Literal["available", "missing", "unusable"]
    # Absolute path, used by the panel to run Java; never sent to the browser.
    executable: str | None = Field(default=None, exclude=True)
    # Where it was found and who built it, to describe it without showing paths.
    source: Literal["craftpanel.txt", "tools/java", "system", "minecraft_launcher"] | None = None
    vendor: str | None = None
    version: str | None = None
    major_version: int | None = None
    message: str


class MinecraftInstallationStatus(BaseModel):
    """Fingerprint of a local Minecraft server; does not list worlds or mods."""

    state: Literal["detected", "not_detected"]
    # Absolute paths stay inside the panel; the browser only gets the script's file name.
    root: str = Field(exclude=True)
    loader: Literal["neoforge", "forge", "fabric", "quilt", "paper", "vanilla", "custom", "unknown"] | None = None
    loader_version: str | None = None
    minecraft_version: str | None = None
    start_script: str | None = Field(default=None, exclude=True)
    start_script_name: str | None = None
    message: str


class AccountProtectionStatus(BaseModel):
    """Server access settings, without reading local accounts or credentials."""

    state: Literal["online_accounts", "whitelist", "unrestricted", "unknown"]
    online_mode: bool | None = None
    whitelist_enabled: bool | None = None
    message: str


class HostRuntimeDiscovery(BaseModel):
    """Portable, strictly read-only discovery contract."""

    operating_system: Literal["windows", "linux", "macos", "other"]
    java: JavaRuntimeStatus
    minecraft: MinecraftInstallationStatus
    accounts: AccountProtectionStatus
    safe_to_inspect: bool = True
