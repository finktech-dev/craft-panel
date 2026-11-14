"""Switching premium/no-premium moves each known player's progress to their new UUID."""

import json

import pytest

from app.core.config import Settings
from app.services.account_mode_service import AccountModeService
from app.services.whitelist_service import offline_uuid


class StoppedServer:
    is_running = False


def _service(tmp_path):
    configured = Settings(project_root=tmp_path)
    assert configured.server_directory is not None
    return AccountModeService(configured_settings=configured, manager=StoppedServer()), configured.server_directory


def _player_files(world, player_uuid):
    for folder, suffix in (("playerdata", ".dat"), ("playerdata", ".dat_old"), ("advancements", ".json"), ("stats", ".json")):
        (world / folder).mkdir(parents=True, exist_ok=True)
        (world / folder / f"{player_uuid}{suffix}").write_bytes(b"data")


def test_move_player_moves_every_file(tmp_path):
    service, _root = _service(tmp_path)
    world = tmp_path / "w"
    _player_files(world, "OLD")

    outcome, moved = service._move_player("OLD", "NEW", [world])

    assert outcome == "migrated" and moved == 4
    for folder, suffix in (("playerdata", ".dat"), ("playerdata", ".dat_old"), ("advancements", ".json"), ("stats", ".json")):
        assert (world / folder / f"NEW{suffix}").is_file()
        assert not (world / folder / f"OLD{suffix}").exists()


def test_move_player_never_overwrites_an_existing_save(tmp_path):
    service, _root = _service(tmp_path)
    world = tmp_path / "w"
    _player_files(world, "OLD")
    (world / "playerdata" / "NEW.dat").write_bytes(b"already-here")

    outcome, moved = service._move_player("OLD", "NEW", [world])

    assert outcome == "collision" and moved == 0
    assert (world / "playerdata" / "OLD.dat").read_bytes() == b"data"      # left untouched
    assert (world / "playerdata" / "NEW.dat").read_bytes() == b"already-here"  # not overwritten


@pytest.mark.asyncio
async def test_premium_to_offline_keeps_progress(tmp_path, monkeypatch):
    service, root = _service(tmp_path)
    root.mkdir(parents=True)
    (root / "server.properties").write_text("online-mode=true\nlevel-name=world\n", encoding="utf-8")
    online = "11111111-1111-1111-1111-111111111111"
    name = "Steve"
    world = root / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"x")
    (world / "playerdata").mkdir()
    (world / "playerdata" / f"{online}.dat").write_bytes(b"inventory")
    (root / "whitelist.json").write_text(json.dumps([{"name": name, "uuid": online}]), encoding="utf-8")

    async def fake_online(player_name, current_online):
        return online

    monkeypatch.setattr(service, "_online_uuid", fake_online)

    result = await service.change(online_mode=False, migrate=True)

    offline = offline_uuid(name)
    assert (world / "playerdata" / f"{offline}.dat").read_bytes() == b"inventory"
    assert not (world / "playerdata" / f"{online}.dat").exists()
    assert result["online_mode"] is False
    assert name in result["migration"]["migrated"]
    assert "online-mode=false" in (root / "server.properties").read_text(encoding="utf-8")
    # The whitelist entry was resynced to the offline UUID for the new mode.
    whitelist = json.loads((root / "whitelist.json").read_text(encoding="utf-8"))
    assert whitelist[0]["uuid"] == offline


@pytest.mark.asyncio
async def test_offline_to_premium_keeps_progress(tmp_path, monkeypatch):
    service, root = _service(tmp_path)
    root.mkdir(parents=True)
    (root / "server.properties").write_text("online-mode=false\nlevel-name=world\n", encoding="utf-8")
    name = "Alex"
    offline = offline_uuid(name)
    online = "22222222-2222-2222-2222-222222222222"
    world = root / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"x")
    (world / "playerdata").mkdir()
    (world / "playerdata" / f"{offline}.dat").write_bytes(b"inventory")
    (root / "usercache.json").write_text(json.dumps([{"name": name, "uuid": offline}]), encoding="utf-8")

    async def fake_online(player_name, current_online):
        return online

    monkeypatch.setattr(service, "_online_uuid", fake_online)

    result = await service.change(online_mode=True, migrate=True)

    assert (world / "playerdata" / f"{online}.dat").read_bytes() == b"inventory"
    assert not (world / "playerdata" / f"{offline}.dat").exists()
    assert result["online_mode"] is True
    assert name in result["migration"]["migrated"]
    assert "online-mode=true" in (root / "server.properties").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_no_migration_when_asked_to_skip(tmp_path):
    service, root = _service(tmp_path)
    root.mkdir(parents=True)
    (root / "server.properties").write_text("online-mode=true\n", encoding="utf-8")

    result = await service.change(online_mode=False, migrate=False)

    assert result["online_mode"] is False
    assert result["migration"]["migrated"] == []
    assert "online-mode=false" in (root / "server.properties").read_text(encoding="utf-8")
