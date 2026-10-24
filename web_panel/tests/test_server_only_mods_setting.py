"""[server_only_mods] keeps mods out of the friends' pack and marks them in the Mods list."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from app.services.mod_service import ModService, matches_server_only_rule
from app.services.server_settings_file import SECTIONS, ValidationContext
from tests.test_protected_paths import StoppedServer
from tests.test_server_settings_file import settings_for, write_file


def _jar(path: Path, mod_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("fabric.mod.json", json.dumps({"id": mod_id, "name": mod_id, "version": "1.0", "description": "x" * 200}))


def test_rules_match_file_patterns_ids_and_prefixes() -> None:
    rules = ("*-server.jar", "dashboardmod", "statsbridge")
    assert matches_server_only_rule("maps-server.jar", None, rules)
    assert matches_server_only_rule("Maps-Server.jar.disabled", None, rules)
    assert matches_server_only_rule("anything.jar", "dashboardmod", rules)
    assert matches_server_only_rule("statsbridge-1.2.jar", None, rules)
    assert not matches_server_only_rule("statsbridgeextra.jar", None, rules)
    assert not matches_server_only_rule("sodium.jar", "sodium", rules)


@pytest.mark.parametrize("bad", ["*", "*.jar", "**", "a b", "mods/x.jar", "x"])
def test_rules_that_would_empty_the_pack_or_look_like_paths_are_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        SECTIONS["server_only_mods"].parser(bad, ValidationContext())


def test_server_only_mods_are_left_out_of_the_pack_and_marked(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    mods = configured.mods_directory
    _jar(mods / "maps-server.jar", "maps")
    _jar(mods / "dashboard.jar", "dashboardmod")
    _jar(mods / "sodium.jar", "sodium")
    write_file(configured, "[server_only_mods]\n*-server.jar\ndashboardmod\n")
    service = ModService(configured, StoppedServer())
    pack = tmp_path / "pack.zip"

    service._build_client_pack_sync(pack)

    with zipfile.ZipFile(pack) as archive:
        assert {name for name in archive.namelist() if name.startswith("mods/")} == {"mods/sodium.jar"}
    marked = {item.filename: item.is_server_only for item in service._list_mods_sync()}
    assert marked == {"dashboard.jar": True, "maps-server.jar": True, "sodium.jar": False}
