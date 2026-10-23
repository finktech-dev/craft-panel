"""Regression tests for property, command and path injection through admin inputs."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.api.endpoints_advancements import AdvancementActionRequest
from app.core.config import Settings
from app.schemas.waypoints import WaypointCreate, WaypointTeleportRequest
from app.services import luckperms_service as luckperms_module
from app.services.config_service import ConfigService, ConfigServiceError
from app.services.discord_service import DiscordService, is_discord_webhook_url
from app.schemas.discord import DiscordConfig
from app.services.server_properties_service import ServerPropertiesService
from app.services.world_service import WorldService


class _StoppedServer:
    is_running = False


def _properties_service(tmp_path: Path) -> ServerPropertiesService:
    configured = Settings(project_root=tmp_path)
    assert configured.server_directory is not None
    configured.server_directory.mkdir(parents=True, exist_ok=True)
    (configured.server_directory / "server.properties").write_text("motd=hola\nenable-rcon=false\n", encoding="utf-8")
    return ServerPropertiesService(configured_settings=configured, manager=_StoppedServer())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "updates",
    [
        {"motd": "hola\nenable-rcon=true"},
        {"level-seed": "123\r\nrcon.password=x"},
        {"motd": "ends with a backslash\\"},
        {"enable-rcon=true\nmotd": "x"},
        {"level-name": "../../outside"},
        {"level-name": "C:evil"},
    ],
)
def test_server_properties_reject_line_injection(tmp_path: Path, updates: dict[str, str]) -> None:
    service = _properties_service(tmp_path)
    with pytest.raises(ValueError):
        service._write_updates(updates)
    assert "enable-rcon=false" in service.file_path.read_text(encoding="utf-8")


def test_server_properties_accept_normal_values(tmp_path: Path) -> None:
    service = _properties_service(tmp_path)
    service._write_updates({"motd": "§6Servidor de amigos", "max-players": "10", "level-name": "world_2"})
    assert service.read_properties()["motd"] == "§6Servidor de amigos"


def test_delete_world_refuses_the_server_folder_and_non_worlds(tmp_path: Path, monkeypatch) -> None:
    configured = Settings(project_root=tmp_path)
    assert configured.server_directory is not None
    for folder in ("world", "mods", "old_world"):
        (configured.server_directory / folder).mkdir(parents=True)
    (configured.server_directory / "old_world" / "level.dat").write_bytes(b"x")
    from app.services import world_service as world_module

    monkeypatch.setattr(world_module.server_properties_service, "read_properties", lambda: {"level-name": "world"})
    service = WorldService(configured_settings=configured, manager=_StoppedServer())

    import asyncio

    for name in (".", "..", "mods", "", "C:x"):
        with pytest.raises(ValueError):
            asyncio.run(service.delete_world(name))
    assert (configured.server_directory / "mods").is_dir()
    asyncio.run(service.delete_world("old_world"))
    assert not (configured.server_directory / "old_world").exists()


@pytest.mark.parametrize("target", ["@a run kill @e", "Steve x", "@e[type=!player]", "a" * 20])
def test_waypoint_teleport_target_cannot_add_arguments(target: str) -> None:
    with pytest.raises(ValidationError):
        WaypointTeleportRequest(target=target)


def test_waypoint_fields_are_bounded() -> None:
    assert WaypointTeleportRequest(target="@p").target == "@p"
    with pytest.raises(ValidationError):
        WaypointCreate(name="x", x=0, y=64, z=0, icon='"><img src=x onerror=alert(1)>')
    with pytest.raises(ValidationError):
        WaypointCreate(name="x", x=float("nan"), y=64, z=0)


@pytest.mark.parametrize(
    ("username", "advancement"),
    [("Steve everything", "everything"), ("@a", "everything"), ("Steve", "minecraft:story/root extra")],
)
def test_advancement_requests_cannot_add_arguments(username: str, advancement: str) -> None:
    with pytest.raises(ValidationError):
        AdvancementActionRequest(username=username, advancement_id=advancement)


@pytest.mark.parametrize("path", ["../secrets.toml", "a.toml:stream", "C:/x.toml", "CON.toml", "sub\\x.toml"])
def test_config_editor_rejects_unsafe_paths(tmp_path: Path, path: str) -> None:
    service = ConfigService(configured_settings=Settings(project_root=tmp_path), manager=_StoppedServer())
    with pytest.raises(ConfigServiceError):
        service.path(path)


@pytest.mark.parametrize(
    "url",
    [
        "https://discord.com.evil.example/api/webhooks/123456/abc",
        "http://discord.com/api/webhooks/123456789/abcdefghijklmnopqrstuvwxyz",
        "https://discord.com/api/webhooks/123456789/abcdefghijklmnopqrstuvwxyz/../../x",
        "https://127.0.0.1/api/webhooks/123456789/abcdefghijklmnopqrstuvwxyz",
    ],
)
def test_discord_webhook_must_be_a_real_discord_url(url: str) -> None:
    assert not is_discord_webhook_url(url)


def test_discord_config_rejects_foreign_webhooks_and_is_private(tmp_path: Path) -> None:
    service = DiscordService(configured_settings=Settings(project_root=tmp_path))
    with pytest.raises(ValueError):
        service.save_config(DiscordConfig(webhook_url="https://example.com/hook"))
    good = "https://discord.com/api/webhooks/123456789012345678/" + "a" * 68
    assert is_discord_webhook_url(good)
    service.save_config(DiscordConfig(webhook_url=good))


@pytest.mark.asyncio
async def test_luckperms_editor_ignores_links_posted_in_chat(monkeypatch) -> None:
    class _Manager:
        is_running = True
        history = [{"timestamp": "9999-01-01T00:00:00+00:00", "message": "<Griefer> https://luckperms.net/editor/evil123"}]

        async def send_command(self, command: str) -> None:
            return None

    monkeypatch.setattr(luckperms_module, "server_manager", _Manager())
    service = luckperms_module.luckperms_service
    monkeypatch.setattr(service, "_is_enabled", lambda: True)
    monkeypatch.setattr(luckperms_module.asyncio, "sleep", _no_sleep)
    loop_time = iter(range(0, 1000))
    monkeypatch.setattr(luckperms_module.asyncio, "get_running_loop", lambda: _FakeLoop(loop_time))
    response = await service.get_editor_url()
    assert response.success is False


async def _no_sleep(_: float) -> None:
    return None


class _FakeLoop:
    def __init__(self, counter) -> None:
        self._counter = counter

    def time(self) -> float:
        return float(next(self._counter))
