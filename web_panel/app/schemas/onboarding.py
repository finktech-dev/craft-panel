"""Contracts for the safe, guided first-run experience."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ServerFlavor = Literal["vanilla", "neoforge", "fabric", "import"]
InstallFlavor = Literal["vanilla", "neoforge", "fabric"]


class InstallServerRequest(BaseModel):
    flavor: InstallFlavor
    minecraft_version: str = Field(pattern=r"^\d+\.\d+(?:\.\d+)?$")
    accept_eula: bool = False


class InstallJavaRequest(BaseModel):
    minecraft_version: str = Field(pattern=r"^\d+\.\d+(?:\.\d+)?$")

class OnboardingStatus(BaseModel):
    operating_system: Literal["windows", "linux", "macos", "other"]
    java_ready: bool
    java_message: str
    server_ready: bool
    server_message: str
    server_flavor: str | None
    minecraft_version: str | None = None
    loader_version: str | None = None
    playit_connected: bool
    playit_enabled: bool = True
    # The official Playit app for Windows: running, installed but stopped, or not installed.
    playit_state: Literal["running", "stopped", "not_installed"] = "not_installed"
    playit_message: str = ""
    playit_autostart: bool | None = None
    playit_download_url: str = "https://playit.gg/download"
    friend_address: str | None = None
    whitelist_enabled: bool = False
    whitelisted_players: int = 0
    public_address: str | None
    first_step: Literal["java", "server", "connection", "ready"]
    recommended_versions: dict[ServerFlavor, list[str]]
    # Running through the panel, or opened outside it: the wizard then only offers to review access.
    server_running: bool = False
    external_server: bool = False
    # new: nothing to start yet; installed: never played; played: a world already exists.
    history_phase: Literal["new", "installed", "played"] = "new"
    world_name: str | None = None
    last_played_at: datetime | None = None
    known_players: int = 0


class AvailableVersion(BaseModel):
    """One installable Minecraft version for a flavor."""

    minecraft_version: str
    stable: bool
    java_major: int | None
    loader_version: str | None = None


class AvailableVersionsResponse(BaseModel):
    flavor: InstallFlavor
    include_snapshots: bool
    latest: str | None
    versions: list[AvailableVersion]
    source: str
    fetched_at: datetime
