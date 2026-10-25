"""Read-only status used to keep first-run choices small and ordered."""

from __future__ import annotations

import asyncio
import json

from app.core.config import Settings, settings
from app.schemas.onboarding import InstallFlavor, OnboardingStatus
from app.services.external_server_service import external_server_detector
from app.services.friend_address import panel_address
from app.services.playit_service import PlayitService, playit_service
from app.services.runtime_discovery import RuntimeDiscoveryService, runtime_discovery_service
from app.services.server_history import read_server_history
from app.services.server_process import server_manager
from app.services.version_catalog_service import VersionCatalogError, VersionCatalogService, version_catalog_service

_RECOMMENDED_COUNT = 10
_PLAYIT_MESSAGES = {
    "running": "Playit ya está instalado y funcionando.",
    "stopped": "Playit está instalado, pero apagado.",
    "broken": "Playit está instalado, pero le falta una parte. Volvé a instalarlo desde la página de Playit.",
    "not_installed": "Playit no está instalado en esta computadora.",
}
_INSTALL_FLAVORS: tuple[InstallFlavor, ...] = ("vanilla", "neoforge", "fabric")


class OnboardingService:
    def __init__(
        self,
        configured_settings: Settings = settings,
        discovery: RuntimeDiscoveryService = runtime_discovery_service,
        tunnel: PlayitService = playit_service,
        catalog: VersionCatalogService = version_catalog_service,
        server=None,  # noqa: ANN001 - MinecraftServerManager or a test double
        external=None,  # noqa: ANN001 - ExternalServerDetector or a test double
    ) -> None:
        self._settings = configured_settings
        self._discovery = discovery
        self._tunnel = tunnel
        self._catalog = catalog
        self._server = server if server is not None else server_manager
        self._external = external if external is not None else external_server_detector

    async def status(self, minecraft_version: str | None = None) -> OnboardingStatus:
        """``minecraft_version`` is the user's pick, used for the Java check before a server exists."""
        runtime = await asyncio.to_thread(self._discovery.discover, minecraft_version)
        tunnel = self._tunnel.status()
        server_ready = runtime.minecraft.state == "detected" and bool(runtime.minecraft.start_script)
        whitelist_enabled, whitelisted_players = self._whitelist_state()
        playit_state = getattr(tunnel, "external_agent", "not_installed")
        can_start_playit = bool(getattr(self._tunnel, "can_start_external_agent", False))
        # A stopped official Playit app counts as ready: "Encender" turns it on.
        playit_ready = not tunnel.needs_setup or can_start_playit
        if runtime.java.state != "available":
            first_step = "java"
        elif not server_ready:
            first_step = "server"
        elif self._settings.playit_enabled and (not playit_ready or not whitelist_enabled):
            # Sharing over the Internet without a friends list lets anyone join.
            first_step = "connection"
        else:
            first_step = "ready"
        recommended = await self._recommended_versions() if not server_ready else {}
        history = await asyncio.to_thread(read_server_history, self._settings)
        running = self._server.is_running
        external = False if running else await asyncio.to_thread(self._external_server_open)
        return OnboardingStatus(
            server_running=running,
            external_server=external,
            history_phase=history.phase,
            world_name=history.world_name,
            last_played_at=history.last_played_at,
            known_players=history.known_players,
            operating_system=runtime.operating_system,
            java_ready=runtime.java.state == "available",
            java_message=runtime.java.message,
            server_ready=server_ready,
            server_message=runtime.minecraft.message,
            server_flavor=runtime.minecraft.loader,
            minecraft_version=runtime.minecraft.minecraft_version,
            loader_version=runtime.minecraft.loader_version,
            playit_connected=playit_ready,
            playit_enabled=self._settings.playit_enabled,
            playit_state=playit_state,
            playit_message=_PLAYIT_MESSAGES[playit_state if playit_state != "stopped" or can_start_playit else "broken"],
            playit_autostart=getattr(tunnel, "external_autostart", None),
            friend_address=self._friend_address(tunnel),
            whitelist_enabled=whitelist_enabled,
            whitelisted_players=whitelisted_players,
            public_address=tunnel.public_address,
            first_step=first_step,
            recommended_versions={
                "vanilla": recommended.get("vanilla", []),
                "neoforge": recommended.get("neoforge", []),
                "fabric": recommended.get("fabric", []),
                "import": [],
            },
        )

    async def _recommended_versions(self) -> dict[str, list[str]]:
        """Newest stable releases per flavor; an empty list when the source is offline."""

        async def newest(flavor: InstallFlavor) -> list[str]:
            try:
                catalog = await self._catalog.list_versions(flavor)
            except VersionCatalogError:
                return []
            return [entry.minecraft_version for entry in catalog.versions[:_RECOMMENDED_COUNT]]

        results = await asyncio.gather(*(newest(flavor) for flavor in _INSTALL_FLAVORS))
        return dict(zip(_INSTALL_FLAVORS, results, strict=True))

    def _external_server_open(self) -> bool:
        try:
            return self._external.detect(self._server.process_pid) is not None
        except Exception:  # noqa: BLE001 - a failed process scan must not break the wizard
            return False

    def _friend_address(self, tunnel) -> str | None:  # noqa: ANN001 - TunnelStatus or a test double
        """The address friends use, from Playit, craftpanel.txt or the panel, if there is one."""
        return tunnel.public_address or panel_address(self._settings)

    def _whitelist_state(self) -> tuple[bool, int]:
        server = self._settings.server_directory
        if server is None:
            return False, 0
        enabled = False
        try:
            for line in (server / "server.properties").read_text(encoding="utf-8", errors="replace").splitlines():
                key, _, value = line.partition("=")
                if key.strip() == "white-list":
                    enabled = value.strip().lower() == "true"
        except OSError:
            pass
        try:
            entries = json.loads((server / "whitelist.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            entries = []
        return enabled, len(entries) if isinstance(entries, list) else 0


onboarding_service = OnboardingService()
