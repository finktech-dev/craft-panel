"""Discord alert presentation is host-configurable and never needs a real webhook."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.config import Settings
from app.schemas.discord import DiscordConfig
from app.services.discord_service import DiscordService


class RecordingDiscordService(DiscordService):
    def __init__(self, configured_settings: Settings) -> None:
        super().__init__(configured_settings)
        self.messages: list[dict[str, object]] = []

    async def _send_embed(self, **kwargs):  # type: ignore[override]
        self.messages.append(kwargs)
        return True, "recorded"


def test_alert_presentation_is_loaded_from_local_config_without_network(tmp_path: Path) -> None:
    configured = Settings(
        project_root=tmp_path,
        discord_server_name="Variable de entorno",
        discord_world_name="world-env",
    )
    assert configured.panel_directory is not None
    service = RecordingDiscordService(configured)
    service.save_config(
        DiscordConfig(
            server_name="Servidor de Ana",
            server_software_label="Fabric 1.21.4",
            world_name="aventura",
            test_player_name="Invitado de prueba",
            player_avatar_url_template="https://avatar.example/{player_name}.png",
        )
    )

    reloaded = RecordingDiscordService(configured)
    assert reloaded.get_config().server_name == "Servidor de Ana"
    assert reloaded.get_config().world_name == "aventura"

    asyncio.run(service.send_server_started(public_address="friends.example:25565"))
    asyncio.run(service.send_test(test_type="events"))

    started, event = service.messages
    assert ("Servidor", "Fabric 1.21.4") in started["fields"]
    assert ("Mundo Activo", "aventura") in started["fields"]
    assert event["title"] == "💀 [Prueba de Feed] Invitado de prueba fue volado en pedazos por un Creeper"
    assert event["thumbnail_url"] == "https://avatar.example/Invitado%20de%20prueba.png"


def test_environment_presentation_is_used_when_local_values_are_empty(tmp_path: Path) -> None:
    configured = Settings(
        project_root=tmp_path,
        discord_server_name="Servidor portable",
        discord_server_software_label="Paper 1.21",
        discord_world_name="mundo-principal",
        discord_player_avatar_url_template="",
    )
    assert configured.panel_directory is not None
    service = RecordingDiscordService(configured)
    service.save_config(DiscordConfig())

    asyncio.run(service.send_server_starting())
    asyncio.run(service.send_player_join("Una Persona"))

    starting, player = service.messages
    assert ("Servidor", "Paper 1.21") in starting["fields"]
    assert ("Mundo Activo", "mundo-principal") in starting["fields"]
    assert player["thumbnail_url"] is None


def test_discord_service_does_not_embed_previous_host_specific_values() -> None:
    source = Path(__file__).parents[1] / "app" / "services" / "discord_service.py"
    content = source.read_text(encoding="utf-8")
    for value in ("ExampleWorld", "ExamplePlayer", "ExampleOperator"):
        assert value not in content
