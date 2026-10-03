"""Contracts for the safe, guided first-run experience."""

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
    playit_connected: bool
    public_address: str | None
    first_step: Literal["java", "server", "connection", "ready"]
    recommended_versions: dict[ServerFlavor, list[str]]
