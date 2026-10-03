"""Read-only status used to keep first-run choices small and ordered."""

from __future__ import annotations

from app.core.config import Settings, settings
from app.schemas.onboarding import OnboardingStatus
from app.services.playit_service import PlayitService, playit_service
from app.services.runtime_discovery import RuntimeDiscoveryService, runtime_discovery_service


class OnboardingService:
    def __init__(
        self,
        configured_settings: Settings = settings,
        discovery: RuntimeDiscoveryService = runtime_discovery_service,
        tunnel: PlayitService = playit_service,
    ) -> None:
        self._settings = configured_settings
        self._discovery = discovery
        self._tunnel = tunnel

    def status(self) -> OnboardingStatus:
        runtime = self._discovery.discover()
        tunnel = self._tunnel.status()
        server_ready = runtime.minecraft.state == "detected" and bool(runtime.minecraft.start_script)
        if runtime.java.state != "available":
            first_step = "java"
        elif not server_ready:
            first_step = "server"
        elif self._settings.playit_enabled and tunnel.needs_setup:
            first_step = "connection"
        else:
            first_step = "ready"
        default_version = self._settings.minecraft_version
        return OnboardingStatus(
            operating_system=runtime.operating_system,
            java_ready=runtime.java.state == "available",
            java_message=runtime.java.message,
            server_ready=server_ready,
            server_message=runtime.minecraft.message,
            server_flavor=runtime.minecraft.loader,
            playit_connected=not tunnel.needs_setup,
            public_address=tunnel.public_address,
            first_step=first_step,
            recommended_versions={
                "vanilla": [default_version],
                "neoforge": [default_version],
                "fabric": [default_version],
                "import": [],
            },
        )


onboarding_service = OnboardingService()
