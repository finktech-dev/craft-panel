"""server_name and public_address from craftpanel.txt."""

from __future__ import annotations

from pathlib import Path

from app.schemas.runtime import TunnelStatus
from tests.test_server_settings_file import settings_for, write_file


def _tunnel(running: bool, address: str | None) -> TunnelStatus:
    return TunnelStatus(is_running=running, public_address=address, message="")


def test_public_address_fills_in_when_playit_reports_none_of_its_own() -> None:
    from app.api.endpoints_server import _friend_connection_info

    # Playit as a Windows service: running, but only echoing the configured address.
    info = _friend_connection_info(
        port=25565, custom_address="manual.example.com", configured_address="old.example.com",
        tunnel=_tunnel(True, "old.example.com"), file_address="play.example.com:25570",
    )
    assert info.public_address == "play.example.com:25570"
    assert "craftpanel.txt" in info.message

    # Nothing detected at all.
    info = _friend_connection_info(
        port=25565, custom_address=None, configured_address=None, tunnel=_tunnel(False, None),
        file_address="play.example.com",
    )
    assert info.public_address == "play.example.com" and info.can_share_with_friends


def test_a_real_playit_address_still_wins() -> None:
    from app.api.endpoints_server import _friend_connection_info

    info = _friend_connection_info(
        port=25565, custom_address=None, configured_address=None,
        tunnel=_tunnel(True, "abc.joinmc.link"), file_address="play.example.com",
    )
    assert info.public_address == "abc.joinmc.link" and info.source == "playit_detected"


def test_effective_values_follow_the_file(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    assert configured.effective_server_name is None
    assert configured.effective_public_address == configured.server_public_address

    write_file(configured, "server_name = Friends server\npublic_address = play.example.com\n")
    assert configured.effective_server_name == "Friends server"
    assert configured.effective_public_address == "play.example.com"


def test_discord_uses_the_server_name_from_the_file(tmp_path: Path) -> None:
    from app.services.discord_service import DiscordConfig, DiscordService

    configured = settings_for(tmp_path)
    service = DiscordService(configured)
    assert service._server_name(DiscordConfig(server_name="From the form")) == "From the form"

    write_file(configured, "server_name = Friends server\n")
    assert service._server_name(DiscordConfig(server_name="From the form")) == "Friends server"


def test_header_and_title_show_the_server_name() -> None:
    from main import templates

    html = templates.env.get_template("dashboard.html").render(
        request=None, current_page="dashboard", is_admin=True, brand_name="Friends server", csrf_token="x",
        two_factor_enabled=False, public_address=None, minecraft_version="",
    )
    assert "<title>Inicio · Friends server</title>" in html
    assert "Friends server</span></a>" in html  # truncated with an ellipsis when long
    assert 'title="Friends server"' in html
