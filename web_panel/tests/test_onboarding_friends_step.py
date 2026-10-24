"""The guided setup must not reach "play" while anyone on the Internet could join."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services.onboarding_service import OnboardingService


class ReadyDiscovery:
    def discover(self, minecraft_version=None):
        return SimpleNamespace(
            operating_system="windows",
            java=SimpleNamespace(state="available", message="Java listo"),
            minecraft=SimpleNamespace(state="detected", start_script="run.bat", loader="vanilla", message="Servidor listo",
                                       minecraft_version="1.21.1", loader_version=None),
        )


class LinkedTunnel:
    def status(self):
        return SimpleNamespace(needs_setup=False, public_address="friends.example:25565")


def _service(tmp_path: Path, *, playit_enabled: bool, whitelist: bool, players: int) -> OnboardingService:
    configured = Settings(project_root=tmp_path, playit_enabled=playit_enabled)
    assert configured.server_directory is not None
    configured.server_directory.mkdir(parents=True)
    (configured.server_directory / "server.properties").write_text(f"white-list={'true' if whitelist else 'false'}\n", encoding="utf-8")
    (configured.server_directory / "whitelist.json").write_text(
        json.dumps([{"name": f"Friend{index}", "uuid": "x"} for index in range(players)]), encoding="utf-8"
    )
    return OnboardingService(configured_settings=configured, discovery=ReadyDiscovery(), tunnel=LinkedTunnel())


@pytest.mark.asyncio
async def test_public_server_without_friends_list_stops_at_friends_step(tmp_path: Path) -> None:
    status = await (_service(tmp_path, playit_enabled=True, whitelist=False, players=0).status())
    assert status.first_step == "connection"
    assert status.whitelist_enabled is False


@pytest.mark.asyncio
async def test_public_server_with_friends_list_is_ready(tmp_path: Path) -> None:
    status = await (_service(tmp_path, playit_enabled=True, whitelist=True, players=2).status())
    assert status.first_step == "ready"
    assert status.whitelisted_players == 2


@pytest.mark.asyncio
async def test_local_only_server_is_not_blocked(tmp_path: Path) -> None:
    status = await (_service(tmp_path, playit_enabled=False, whitelist=False, players=0).status())
    assert status.first_step == "ready"


class OfficialPlayit:
    """The official Playit app in one of its states, as PlayitService reports it."""

    def __init__(self, state: str, *, can_start: bool = False, address: str | None = None, autostart: bool | None = False) -> None:
        self.can_start_external_agent = can_start
        self._status = SimpleNamespace(
            needs_setup=state != "running",
            public_address=address,
            external_agent=state,
            external_autostart=autostart,
        )

    def status(self):
        return self._status


def _with_tunnel(tmp_path: Path, tunnel) -> OnboardingService:
    service = _service(tmp_path, playit_enabled=True, whitelist=True, players=1)
    service._tunnel = tunnel
    return service


@pytest.mark.asyncio
async def test_running_official_playit_is_ready_and_never_asks_to_link(tmp_path: Path) -> None:
    status = await _with_tunnel(tmp_path, OfficialPlayit("running", address="example-words.gl.joinmc.link")).status()

    assert status.first_step == "ready" and status.playit_connected is True
    assert status.playit_state == "running"
    assert status.playit_message == "Playit ya está instalado y funcionando."
    assert status.friend_address == "example-words.gl.joinmc.link"


@pytest.mark.asyncio
async def test_stopped_official_playit_does_not_block_because_start_turns_it_on(tmp_path: Path) -> None:
    status = await _with_tunnel(tmp_path, OfficialPlayit("stopped", can_start=True)).status()

    assert status.first_step == "ready" and status.playit_connected is True
    assert status.playit_state == "stopped" and status.playit_autostart is False
    assert status.playit_message == "Playit está instalado, pero apagado."


@pytest.mark.asyncio
async def test_official_playit_without_its_service_asks_to_reinstall(tmp_path: Path) -> None:
    status = await _with_tunnel(tmp_path, OfficialPlayit("stopped", can_start=False, autostart=None)).status()

    assert status.first_step == "connection" and status.playit_connected is False
    assert "Volvé a instalarlo" in status.playit_message


@pytest.mark.asyncio
async def test_without_playit_the_friends_step_offers_the_download(tmp_path: Path) -> None:
    status = await _with_tunnel(tmp_path, OfficialPlayit("not_installed", autostart=None)).status()

    assert status.first_step == "connection" and status.playit_state == "not_installed"
    assert status.playit_download_url == "https://playit.gg/download"


@pytest.mark.asyncio
async def test_pasted_address_counts_as_the_friends_address(tmp_path: Path) -> None:
    service = _with_tunnel(tmp_path, OfficialPlayit("running"))
    assert service._settings.panel_directory is not None
    (service._settings.panel_directory / ".server_connection.json").write_text('{"public_address": "pasted.ply.gg:4000"}', encoding="utf-8")

    assert (await service.status()).friend_address == "pasted.ply.gg:4000"
