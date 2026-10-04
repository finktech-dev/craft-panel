from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services.playit_service import PlayitService


def test_playit_is_enabled_by_default_and_can_be_disabled_locally(tmp_path):
    configured = Settings(project_root=tmp_path)
    assert configured.playit_enabled is True

    assert configured.panel_directory is not None
    preference = configured.panel_directory / ".launch_settings.json"
    preference.write_text('{"allocated_ram_gb": 4, "playit_enabled": false}', encoding="utf-8")

    restored = Settings(project_root=tmp_path)
    assert restored.allocated_ram_gb == 4
    assert restored.playit_enabled is False


def test_playit_asset_selection_uses_the_platform_specific_portable_binary(monkeypatch):
    release = {
        "assets": [
            {"name": "playit-windows-amd64.exe", "browser_download_url": "https://github.com/playit-cloud/playit-agent/windows"},
            {"name": "playit-linux-amd64", "browser_download_url": "https://github.com/playit-cloud/playit-agent/linux"},
        ]
    }
    monkeypatch.setattr("app.services.playit_service.platform.system", lambda: "Linux")
    monkeypatch.setattr("app.services.playit_service.platform.machine", lambda: "x86_64")

    assert PlayitService._select_asset(release).endswith("/linux")

def test_playit_asset_selection_accepts_current_cli_release_names(monkeypatch):
    release = {
        "assets": [
            {"name": "playit-cli-linux-amd64", "browser_download_url": "https://github.com/playit-cloud/playit-agent/cli-linux"},
            {"name": "playit-1.0.10-apple-m1", "browser_download_url": "https://github.com/playit-cloud/playit-agent/apple"},
        ]
    }
    monkeypatch.setattr("app.services.playit_service.platform.system", lambda: "Darwin")
    monkeypatch.setattr("app.services.playit_service.platform.machine", lambda: "arm64")

    assert PlayitService._select_asset(release).endswith("/apple")

@pytest.mark.asyncio
async def test_playit_output_exposes_a_shareable_address(tmp_path):
    service = PlayitService(Settings(project_root=tmp_path))
    stream = asyncio.StreamReader()
    stream.feed_data(b"Tunnel address: friends-room.joinmc.link:25565\n")
    stream.feed_eof()

    await service._read_output(stream)

    assert service.status().public_address == "friends-room.joinmc.link:25565"


def test_running_windows_playit_service_is_reused_without_copying_its_secret(tmp_path, monkeypatch):
    service = PlayitService(Settings(project_root=tmp_path))
    monkeypatch.setattr("app.services.playit_service.platform.system", lambda: "Windows")
    monkeypatch.setattr(
        "app.services.playit_service.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="STATE              : 4  RUNNING"),
    )

    assert service.uses_external_agent is True
    assert service.needs_setup is False
    assert service.status().is_running is True