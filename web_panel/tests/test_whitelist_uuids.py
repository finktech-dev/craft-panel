"""Whitelist entries must carry the UUID the server actually checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services import whitelist_service as whitelist_module
from app.services.whitelist_service import WhitelistService, offline_uuid


class StoppedServer:
    is_running = False


class FakeProperties:
    def __init__(self, online_mode: bool) -> None:
        self._online = online_mode

    def read_properties(self) -> dict[str, str]:
        return {"online-mode": "true" if self._online else "false"}


def _service(tmp_path: Path, monkeypatch, online_mode: bool) -> WhitelistService:
    configured = Settings(project_root=tmp_path)
    assert configured.server_directory is not None
    configured.server_directory.mkdir(parents=True)
    monkeypatch.setattr(whitelist_module, "server_properties_service", FakeProperties(online_mode))
    return WhitelistService(configured_settings=configured, manager=StoppedServer())


def test_offline_uuid_matches_minecraft() -> None:
    # Known value from Java's UUID.nameUUIDFromBytes("OfflinePlayer:Notch").
    assert offline_uuid("Notch") == "b50ad385-829d-3141-a216-7e7d7539ba7f"


@pytest.mark.asyncio
async def test_offline_server_stores_offline_uuid(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch, online_mode=False)

    await service.add_player("Alex")

    stored = json.loads(service.file_path.read_text(encoding="utf-8"))
    assert stored == [{"name": "Alex", "uuid": offline_uuid("Alex")}]


@pytest.mark.asyncio
async def test_usercache_uuid_wins(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch, online_mode=True)
    cached = "11111111-2222-3333-4444-555555555555"
    (service.file_path.parent / "usercache.json").write_text(json.dumps([{"name": "alex", "uuid": cached}]), encoding="utf-8")

    async def no_network(self, name):
        pytest.fail("usercache must be used before asking Mojang")

    monkeypatch.setattr(WhitelistService, "_mojang_uuid", no_network)
    await service.add_player("Alex")

    assert json.loads(service.file_path.read_text(encoding="utf-8"))[0]["uuid"] == cached


@pytest.mark.asyncio
async def test_online_server_uses_official_account(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch, online_mode=True)

    async def official(self, name):
        return "069a79f4-44e9-4726-a5be-fca90e38aaf5", "Notch"

    monkeypatch.setattr(WhitelistService, "_mojang_uuid", official)
    await service.add_player("notch")

    assert json.loads(service.file_path.read_text(encoding="utf-8")) == [
        {"name": "Notch", "uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5"}
    ]
