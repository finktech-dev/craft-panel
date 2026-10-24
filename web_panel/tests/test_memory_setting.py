"""memory in craftpanel.txt is the source of truth for the server's RAM when written."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import server_settings_file as module
from app.services.server_settings_file import KEYS, ValidationContext, parse_text
from tests.test_server_settings_file import settings_for, write_file


@pytest.fixture(autouse=True)
def eight_gigabyte_pc(monkeypatch) -> None:
    monkeypatch.setattr(module, "host_memory_limits", lambda: (8, 6))


def test_memory_accepts_gigabytes_within_what_the_pc_can_spare() -> None:
    parse = KEYS["memory"].parser
    assert parse("6G", ValidationContext()) == 6
    assert parse("4GB", ValidationContext()) == 4
    assert parse("2048MB", ValidationContext()) == 2
    assert parse("3", ValidationContext()) == 3
    for bad in ["7G", "0G", "1500MB", "lots"]:
        with pytest.raises(ValueError):
            parse(bad, ValidationContext())


def test_effective_ram_prefers_the_file(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    configured.allocated_ram_gb = 3
    assert configured.effective_ram_gb == 3
    write_file(configured, "memory = 5G\n")
    assert configured.effective_ram_gb == 5
    assert parse_text("memory = 5G\n").value("memory") == 5


@pytest.mark.asyncio
async def test_start_writes_the_memory_into_user_jvm_args(tmp_path: Path) -> None:
    from app.services.server_process import MinecraftServerManager

    configured = settings_for(tmp_path)
    server = configured.server_directory
    (server / "user_jvm_args.txt").write_text("# keep\n-Xms1G\n-Xmx2G\n", encoding="utf-8")
    write_file(configured, "memory = 5G\n")
    manager = object.__new__(MinecraftServerManager)
    manager.__init__(configured_settings=configured)

    manager._apply_memory(5)

    assert (server / "user_jvm_args.txt").read_text(encoding="utf-8") == "# keep\n-Xms2G\n-Xmx5G\n"


def test_protected_jvm_args_are_left_alone(tmp_path: Path) -> None:
    from app.services.server_process import MinecraftServerManager

    configured = settings_for(tmp_path)
    args = configured.server_directory / "user_jvm_args.txt"
    args.write_text("-Xmx2G\n", encoding="utf-8")
    write_file(configured, "memory = 5G\n[protected]\nuser_jvm_args.txt\n")
    manager = object.__new__(MinecraftServerManager)
    manager.__init__(configured_settings=configured)

    manager._apply_memory(5)

    assert args.read_text(encoding="utf-8") == "-Xmx2G\n"


@pytest.mark.asyncio
async def test_ram_selector_writes_memory_into_an_existing_file(tmp_path: Path, monkeypatch) -> None:
    from app.api import endpoints_runtime
    from app.services.server_settings_file import ServerSettingsFile

    configured = settings_for(tmp_path)
    (configured.server_directory / "user_jvm_args.txt").write_text("-Xmx2G\n", encoding="utf-8")
    monkeypatch.setattr(endpoints_runtime, "settings", configured)
    monkeypatch.setattr(endpoints_runtime, "server_settings_file", ServerSettingsFile())
    monkeypatch.setattr(endpoints_runtime, "_host_memory", lambda: (8, 6, 6))
    monkeypatch.setattr(endpoints_runtime, "_settings_file", lambda: tmp_path / "launch.json")

    class Stopped:
        is_running = False

    monkeypatch.setattr(endpoints_runtime, "server_manager", Stopped())

    # Without craftpanel.txt nothing is created in the server folder.
    await endpoints_runtime.update_launch_settings(endpoints_runtime.LaunchSettingsUpdate(allocated_ram_gb=3))
    assert not (configured.server_directory / "craftpanel.txt").exists()

    path = write_file(configured, "# mine\nmemory = 3G\n")
    result = await endpoints_runtime.update_launch_settings(endpoints_runtime.LaunchSettingsUpdate(allocated_ram_gb=4))

    assert path.read_text(encoding="utf-8") == "# mine\nmemory = 4G\n"
    assert result.allocated_ram_gb == 4
    assert (await endpoints_runtime.get_launch_settings()).allocated_ram_gb == 4


def test_cache_sees_same_size_saves_from_another_instance(tmp_path: Path) -> None:
    """Two saves in one Windows clock tick keep mtime and size; the cache must still notice."""
    import os

    from app.services.server_settings_file import ServerSettingsFile

    configured = settings_for(tmp_path)
    path = write_file(configured, "memory = 3G\n")
    reader, writer = ServerSettingsFile(), ServerSettingsFile()
    assert reader.load(configured).values["memory"] == 3
    before = path.stat()

    writer.save_fields(configured, values={"memory": "4G"})
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))  # same tick, same size
    assert path.stat().st_size == before.st_size

    assert reader.load(configured).values["memory"] == 4
