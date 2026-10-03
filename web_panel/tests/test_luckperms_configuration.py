"""LuckPerms stays opt-in and loads ranks from local files, not JavaScript."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import Settings
from app.services.luckperms_service import LuckPermsService


def test_luckperms_is_disabled_without_a_local_configuration(tmp_path: Path, monkeypatch) -> None:
    configured = Settings(project_root=tmp_path)
    service = LuckPermsService()
    monkeypatch.setattr("app.core.config.settings", configured)
    assert service.get_configuration().enabled is False


def test_enabled_configuration_loads_a_local_preset(tmp_path: Path, monkeypatch) -> None:
    configured = Settings(project_root=tmp_path)
    assert configured.panel_directory is not None
    preset_dir = configured.panel_directory / "config" / "presets" / "luckperms"
    preset_dir.mkdir(parents=True)
    (preset_dir / "friends.json").write_text(json.dumps({"primary_ranks": [{"id": "owner"}], "secondary_roles": []}), encoding="utf-8")
    (configured.panel_directory / ".luckperms_config.json").write_text(json.dumps({"enabled": True, "preset": "friends"}), encoding="utf-8")
    service = LuckPermsService()
    monkeypatch.setattr("app.core.config.settings", configured)
    availability = service.get_configuration()
    assert availability.enabled is True
    assert availability.primary_ranks == [{"id": "owner"}]

def test_worldedit_is_optional_and_detected_from_the_mods_folder(tmp_path: Path, monkeypatch) -> None:
    configured = Settings(project_root=tmp_path)
    assert configured.mods_directory is not None
    configured.mods_directory.mkdir(parents=True)
    service = LuckPermsService()
    monkeypatch.setattr("app.core.config.settings", configured)

    assert service.get_worldedit_status()["available"] is False

    (configured.mods_directory / "worldedit-neoforge-7.3.0.jar").write_bytes(b"placeholder")
    assert service.get_worldedit_status()["available"] is True
