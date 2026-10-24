"""[protected] in craftpanel.txt: the panel never changes or deletes those paths."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.services.protected_paths import (
    ProtectedPathError,
    is_protected,
    require_not_protected,
    require_tree_not_protected,
)
from app.services.server_settings_file import SECTIONS, ValidationContext
from tests.test_server_settings_file import settings_for, write_file


class StoppedServer:
    is_running = False
    lifecycle_operation = None
    process_pid = None


@pytest.mark.parametrize("pattern", ["*", "**", "/", "*/", "**/*", "**/", "*.*"])
def test_patterns_that_block_everything_are_rejected(pattern: str) -> None:
    with pytest.raises(ValueError):
        SECTIONS["protected"].parser(pattern, ValidationContext())


@pytest.mark.parametrize("pattern", ["server.properties", "config/mymod.toml", "mods/important.jar", "world/", "*.json", "!mods/x.jar"])
def test_specific_patterns_are_accepted(pattern: str) -> None:
    assert SECTIONS["protected"].parser(pattern, ValidationContext()) == pattern


def test_helper_matches_relative_to_the_server_folder(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    server = configured.server_directory
    write_file(configured, "[protected]\nconfig/keep/\nserver.properties\n")

    assert is_protected(server / "server.properties", configured, is_directory=False)
    assert is_protected(server / "config" / "keep" / "a.toml", configured, is_directory=False)
    assert not is_protected(server / "config" / "other.toml", configured, is_directory=False)
    assert not is_protected(tmp_path / "server.properties", configured, is_directory=False)
    with pytest.raises(ProtectedPathError) as error:
        require_not_protected(server / "server.properties", configured=configured)
    assert "protegido en craftpanel.txt" in str(error.value)


def test_tree_check_finds_protected_files_inside_a_folder(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    world = configured.server_directory / "old_world"
    (world / "data").mkdir(parents=True)
    (world / "data" / "important.dat").write_bytes(b"x")
    write_file(configured, "[protected]\nimportant.dat\n")

    with pytest.raises(ProtectedPathError):
        require_tree_not_protected(world, configured)


def test_without_rules_nothing_is_protected(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    require_not_protected(configured.server_directory / "server.properties", configured=configured)


def _mod_service(configured):
    from app.services.mod_service import ModService

    configured.mods_directory.mkdir(parents=True, exist_ok=True)
    return ModService(configured, StoppedServer())


def test_mod_delete_toggle_and_bulk_respect_protection(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    service = _mod_service(configured)
    jar = configured.mods_directory / "important.jar"
    jar.write_bytes(b"PK\x03\x04")
    write_file(configured, "[protected]\nmods/important.jar\n")

    with pytest.raises(ProtectedPathError):
        asyncio.run(service.delete_mod("important.jar"))
    with pytest.raises(ProtectedPathError):
        asyncio.run(service.toggle_mod("important.jar"))
    result = asyncio.run(service.bulk_action("delete", ["important.jar"]))
    assert result.affected_count == 0 and "protegido" in result.errors[0]
    assert jar.is_file()


def test_mod_history_rollback_refuses_protected_mods(tmp_path: Path) -> None:
    from app.services.mod_history_service import ModFileRecord

    configured = settings_for(tmp_path)
    service = _mod_service(configured)
    jar = configured.mods_directory / "important.jar"
    jar.write_bytes(b"PK\x03\x04")
    write_file(configured, "[protected]\nmods/important.jar\n")
    current = [ModFileRecord(filename="important.jar", sha256="0" * 64, size=4, enabled=True, mtime_ns=0)]

    with pytest.raises(ProtectedPathError):
        service.history._apply_state([], current)
    assert jar.is_file()


def test_config_editor_refuses_protected_files(tmp_path: Path) -> None:
    from app.services.config_service import ConfigConflictError, ConfigService

    configured = settings_for(tmp_path)
    configured.config_directory.mkdir(parents=True)
    target = configured.config_directory / "mymod.toml"
    target.write_text("a = 1\n", encoding="utf-8")
    write_file(configured, "[protected]\nconfig/mymod.toml\n")

    with pytest.raises(ConfigConflictError) as error:
        asyncio.run(ConfigService(configured, StoppedServer()).save("mymod.toml", "a = 2\n"))
    assert "protegido" in str(error.value)
    assert target.read_text(encoding="utf-8") == "a = 1\n"


def test_server_properties_edits_are_refused_when_protected(tmp_path: Path) -> None:
    from app.services.server_properties_service import ServerPropertiesService

    configured = settings_for(tmp_path)
    properties = configured.server_directory / "server.properties"
    properties.write_text("motd=old\n", encoding="utf-8")
    write_file(configured, "[protected]\nserver.properties\n")

    with pytest.raises(ProtectedPathError):
        ServerPropertiesService(configured, StoppedServer())._write_updates({"motd": "new"})
    assert properties.read_text(encoding="utf-8") == "motd=old\n"


def test_world_delete_is_refused_when_something_inside_is_protected(tmp_path: Path, monkeypatch) -> None:
    from app.services import world_service as world_module

    configured = settings_for(tmp_path)
    old = configured.server_directory / "old_world"
    old.mkdir()
    (old / "level.dat").write_bytes(b"x")
    write_file(configured, "[protected]\nold_world/\n")
    monkeypatch.setattr(world_module.server_properties_service, "read_properties", lambda: {"level-name": "world"})

    with pytest.raises(ProtectedPathError):
        asyncio.run(world_module.WorldService(configured, StoppedServer()).delete_world("old_world"))
    assert (old / "level.dat").is_file()


def test_installer_refuses_when_its_files_are_protected(tmp_path: Path) -> None:
    from app.services.installer_service import InstallerConflictError, InstallerService

    configured = settings_for(tmp_path)
    write_file(configured, "[protected]\neula.txt\n")
    service = InstallerService(configured, server=StoppedServer())

    with pytest.raises(InstallerConflictError) as error:
        service.preflight("1.21.1", accept_eula=True)
    assert "protegido" in str(error.value)


@pytest.mark.asyncio
async def test_protected_errors_become_a_plain_409() -> None:
    from main import protected_path_handler

    response = await protected_path_handler(None, ProtectedPathError("server.properties"))

    assert response.status_code == 409
    assert "protegido en craftpanel.txt" in json.loads(response.body)["detail"]
