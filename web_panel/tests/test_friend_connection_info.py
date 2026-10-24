"""Regression tests for the read-only friend connection summary."""

from app.api.endpoints_server import _friend_connection_info
from app.schemas.runtime import TunnelStatus


def _tunnel(*, active: bool = False, address: str | None = None) -> TunnelStatus:
    return TunnelStatus(is_running=active, public_address=address, message="test")


def test_local_fallback_is_never_presented_as_shareable() -> None:
    result = _friend_connection_info(
        port=25565, custom_address=None, configured_address=None, tunnel=_tunnel()
    )

    assert result.public_address == "127.0.0.1:25565"
    assert result.source == "local_only"
    assert result.can_share_with_friends is False
    assert "esta computadora" in result.message


def test_detected_active_playit_address_is_preferred() -> None:
    result = _friend_connection_info(
        port=25565,
        custom_address="manual.example:25565",
        configured_address="configured.example:25565",
        tunnel=_tunnel(active=True, address="friends.joinmc.link:25565"),
    )

    assert result.public_address == "friends.joinmc.link:25565"
    assert result.source == "playit_detected"
    assert result.can_share_with_friends is True
    assert result.tunnel_active is True


def test_manual_address_is_explicitly_unverified() -> None:
    result = _friend_connection_info(
        port=25565,
        custom_address="my-server.example:25565",
        configured_address=None,
        tunnel=_tunnel(),
    )

    assert result.source == "manual"
    assert result.is_custom is True
    assert "No podemos comprobar" in result.message


import pytest  # noqa: E402


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("stopped", "Al tocar Encender lo prendemos solo"),
        ("running", "Usar la dirección de mi Playit"),
        ("not_installed", "playit.gg/download"),
        (None, "activá el acceso por Internet en Ajustes"),
    ],
)
def test_local_fallback_tells_the_next_step_for_each_playit_state(state, expected) -> None:
    result = _friend_connection_info(
        port=25565, custom_address=None, configured_address=None, tunnel=_tunnel(), playit_host_state=state
    )

    assert result.source == "local_only"
    assert expected in result.next_step