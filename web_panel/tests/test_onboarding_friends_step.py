"""The guided setup must not reach "play" while anyone on the Internet could join."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.core.config import Settings
from app.services.onboarding_service import OnboardingService


class ReadyDiscovery:
    def discover(self):
        return SimpleNamespace(
            operating_system="windows",
            java=SimpleNamespace(state="available", message="Java listo"),
            minecraft=SimpleNamespace(state="detected", start_script="run.bat", loader="vanilla", message="Servidor listo"),
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


def test_public_server_without_friends_list_stops_at_friends_step(tmp_path: Path) -> None:
    status = _service(tmp_path, playit_enabled=True, whitelist=False, players=0).status()
    assert status.first_step == "connection"
    assert status.whitelist_enabled is False


def test_public_server_with_friends_list_is_ready(tmp_path: Path) -> None:
    status = _service(tmp_path, playit_enabled=True, whitelist=True, players=2).status()
    assert status.first_step == "ready"
    assert status.whitelisted_players == 2


def test_local_only_server_is_not_blocked(tmp_path: Path) -> None:
    status = _service(tmp_path, playit_enabled=False, whitelist=False, players=0).status()
    assert status.first_step == "ready"
