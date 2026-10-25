"""The wizard knows whether the server is new, installed but never played, already played, or on."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services.onboarding_service import OnboardingService
from app.services.server_history import needs_setup, read_server_history
from tests.test_onboarding_friends_step import LinkedTunnel, ReadyDiscovery


def _settings(tmp_path: Path) -> Settings:
    configured = Settings(project_root=tmp_path, playit_enabled=False)
    assert configured.server_directory is not None
    configured.server_directory.mkdir(parents=True, exist_ok=True)
    return configured


def _installed(configured: Settings) -> Path:
    root = configured.server_directory
    configured.server_start_script.write_text("@echo off\n", encoding="utf-8")
    return root


def _played(configured: Settings, *, world: str = "Oficial2", players: int = 3) -> Path:
    root = _installed(configured)
    (root / "server.properties").write_text(f"level-name={world}\n", encoding="utf-8")
    (root / world).mkdir()
    (root / world / "level.dat").write_bytes(b"\x0a")
    (root / "usercache.json").write_text(json.dumps([{"name": f"P{index}"} for index in range(players)]), encoding="utf-8")
    return root


def test_phases_follow_the_server_folder(tmp_path: Path) -> None:
    configured = _settings(tmp_path)
    assert read_server_history(configured).phase == "new"

    _installed(configured)
    assert read_server_history(configured).phase == "installed"

    _played(configured)
    history = read_server_history(configured)
    assert history.phase == "played"
    assert history.world_name == "Oficial2" and history.known_players == 3
    assert history.last_played_at is not None


def test_a_level_name_with_a_path_is_never_followed(tmp_path: Path) -> None:
    configured = _settings(tmp_path)
    root = _installed(configured)
    (root / "server.properties").write_text("level-name=../afuera\n", encoding="utf-8")
    (tmp_path / "afuera").mkdir()
    (tmp_path / "afuera" / "level.dat").write_bytes(b"\x0a")
    assert read_server_history(configured).phase == "installed"


def test_login_opens_the_wizard_only_until_the_server_was_played(tmp_path: Path) -> None:
    configured = _settings(tmp_path)
    assert needs_setup(configured, server_running=False)
    assert not needs_setup(configured, server_running=True)
    _played(configured)
    assert not needs_setup(configured, server_running=False)


class FakeServer:
    def __init__(self, running: bool) -> None:
        self.is_running = running
        self.process_pid = None


class FakeDetector:
    def __init__(self, found: bool) -> None:
        self.found = found

    def detect(self, own_pid=None):
        return SimpleNamespace() if self.found else None


@pytest.mark.asyncio
@pytest.mark.parametrize(("running", "external"), [(True, False), (False, True), (False, False)])
async def test_status_reports_a_running_server_and_its_history(tmp_path: Path, running: bool, external: bool) -> None:
    configured = _settings(tmp_path)
    _played(configured, players=1)
    service = OnboardingService(
        configured_settings=configured,
        discovery=ReadyDiscovery(),
        tunnel=LinkedTunnel(),
        server=FakeServer(running),
        external=FakeDetector(external),
    )
    status = await service.status()
    assert status.server_running is running
    assert status.external_server is external
    assert status.history_phase == "played" and status.world_name == "Oficial2" and status.known_players == 1


@pytest.mark.asyncio
async def test_login_answers_where_to_go(tmp_path: Path, monkeypatch) -> None:
    from starlette.requests import Request

    from app.api import endpoints_auth
    from app.schemas.server import LoginRequest

    configured = _settings(tmp_path)
    monkeypatch.setattr(endpoints_auth, "settings", SimpleNamespace(
        server_directory=configured.server_directory,
        server_start_script=configured.server_start_script,
        mark_admin_password_claimed=lambda: None,
    ))
    monkeypatch.setattr(endpoints_auth, "is_valid_admin_pin", lambda pin: True)
    monkeypatch.setattr(endpoints_auth, "totp_manager", SimpleNamespace(verify_login_code=lambda code: True))
    monkeypatch.setattr(endpoints_auth, "mark_session_as_admin", lambda request: None)
    monkeypatch.setattr(endpoints_auth, "server_manager", FakeServer(False))
    request = Request({"type": "http", "headers": [(b"host", b"127.0.0.1:8080")], "client": ("127.0.0.1", 5000)})

    first = await endpoints_auth.login(LoginRequest(pin="whatever-pin-1234"), request)
    assert first.next_url == "/onboarding"

    _played(configured)
    again = await endpoints_auth.login(LoginRequest(pin="whatever-pin-1234"), request)
    assert again.next_url == "/"
