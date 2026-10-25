"""VPNs on this PC: recognising them, the address for friends and opening the panel to them only."""

from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.endpoints_server import _friend_connection_info
from app.core.security_middleware import RequestGuardMiddleware
from app.schemas.runtime import TunnelStatus
from app.services import vpn_service
from app.services.vpn_service import PanelVpnAccess, VpnNetwork


def _address(ip: str, netmask: str = "255.255.255.0"):
    return SimpleNamespace(family=socket.AF_INET, address=ip, netmask=netmask)


def _up(*names: str, down: tuple[str, ...] = ()):
    return {name: SimpleNamespace(isup=name not in down) for name in names}


def test_recognises_vpns_by_name_or_range_and_ignores_normal_adapters() -> None:
    addresses = {
        "Ethernet 2": [_address("192.168.1.20")],
        "vEthernet (WSL)": [_address("172.20.0.1", "255.255.240.0")],
        "Tailscale": [_address("100.101.2.3", "255.255.255.255")],
        "Mi red de juegos": [_address("26.10.0.5", "255.0.0.0")],
        "ZeroTier One [8056c2e21c000001]": [_address("10.147.17.4")],
        "Hamachi": [_address("25.1.2.3", "255.0.0.0")],
        "wg0": [_address("10.8.0.2")],
        "Loopback Pseudo-Interface 1": [_address("127.0.0.1", "255.0.0.0")],
    }
    found = vpn_service.detect(addresses, _up(*addresses, down=("Hamachi",)))

    assert {(network.name, network.address) for network in found} == {
        ("Tailscale", "100.101.2.3"),
        ("Radmin VPN", "26.10.0.5"),
        ("ZeroTier", "10.147.17.4"),
        ("WireGuard", "10.8.0.2"),
    }
    tailscale = next(network for network in found if network.name == "Tailscale")
    # Peers live anywhere in the Tailscale range, not just this PC's /32.
    assert tailscale.contains("100.80.9.9")
    zerotier = next(network for network in found if network.name == "ZeroTier")
    assert zerotier.contains("10.147.17.200") and not zerotier.contains("192.168.1.5")


def _network(ip: str = "100.101.2.3", cidr: str = "100.64.0.0/10") -> VpnNetwork:
    return VpnNetwork("Tailscale", "Tailscale", ip, ipaddress.IPv4Network(cidr))


def test_peers_are_only_restricted_once_the_panel_opened_to_a_vpn() -> None:
    access = PanelVpnAccess()
    assert access.peer_is_allowed("192.168.1.5")

    access.activate([_network()])
    assert access.peer_is_allowed("127.0.0.1")
    assert access.peer_is_allowed("100.90.1.1")
    assert not access.peer_is_allowed("192.168.1.5")
    assert not access.peer_is_allowed("8.8.8.8")


@pytest.mark.asyncio
async def test_middleware_turns_away_anyone_outside_the_vpn(monkeypatch) -> None:
    access = PanelVpnAccess()
    access.activate([_network()])
    monkeypatch.setattr("app.core.security_middleware.panel_vpn_access", access)
    reached: list[str] = []

    async def app(scope, receive, send):
        reached.append(scope["client"][0])

    guard = RequestGuardMiddleware(app)
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    for client in ("192.168.1.5", "100.90.1.1"):
        scope = {"type": "http", "path": "/", "method": "GET", "headers": [(b"host", b"100.101.2.3:8080")], "client": (client, 5000)}
        await guard(scope, receive, send)

    assert reached == ["100.90.1.1"]
    assert sent[0]["status"] == 403


def test_friends_get_the_vpn_address_when_there_is_nothing_else() -> None:
    tunnel = TunnelStatus(is_running=False, public_address=None, message="")
    info = _friend_connection_info(
        port=25565, custom_address=None, configured_address=None, tunnel=tunnel, vpn_networks=[_network()]
    )
    assert info.source == "vpn" and info.public_address == "100.101.2.3:25565"
    assert info.can_share_with_friends and "Tailscale" in info.message

    playit = TunnelStatus(is_running=True, public_address="mi-server.joinmc.link", message="")
    info = _friend_connection_info(
        port=25565, custom_address=None, configured_address=None, tunnel=playit, vpn_networks=[_network()]
    )
    assert info.source == "playit_detected"
    assert [item.address for item in info.vpn_addresses] == ["100.101.2.3:25565"]


def test_panel_access_setting_is_saved_and_off_by_default(tmp_path: Path) -> None:
    assert not vpn_service.panel_access_enabled(tmp_path)
    vpn_service.save_panel_access(tmp_path, True)
    assert vpn_service.panel_access_enabled(tmp_path)
    vpn_service.save_panel_access(tmp_path, False)
    assert not vpn_service.panel_access_enabled(tmp_path)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_run_panel_binds_loopback_and_the_vpn_never_every_network(tmp_path: Path, monkeypatch) -> None:
    import run_panel

    configured = SimpleNamespace(panel_mode="local", panel_host="127.0.0.1", panel_port=_free_port(), panel_directory=tmp_path)
    monkeypatch.setattr(run_panel, "settings", configured)
    access = PanelVpnAccess()
    monkeypatch.setattr(vpn_service, "panel_vpn_access", access)
    # 127.0.0.2 stands in for the VPN address: it can be bound on any PC.
    monkeypatch.setattr(vpn_service, "detect", lambda: [_network("127.0.0.2", "127.0.0.2/32")])

    assert run_panel._vpn_sockets() is None  # off by default

    vpn_service.save_panel_access(tmp_path, True)
    sockets = run_panel._vpn_sockets()
    try:
        assert sorted(sock.getsockname()[0] for sock in sockets) == ["127.0.0.1", "127.0.0.2"]
        assert access.restrict_peers and [network.address for network in access.networks] == ["127.0.0.2"]
    finally:
        for sock in sockets or []:
            sock.close()


@pytest.mark.asyncio
async def test_only_someone_at_this_pc_can_open_the_panel_to_the_vpn(tmp_path: Path, monkeypatch) -> None:
    from fastapi import HTTPException
    from starlette.requests import Request

    from app.api import endpoints_network

    monkeypatch.setattr(endpoints_network, "settings", SimpleNamespace(panel_mode="local", panel_directory=tmp_path, panel_port=8080))
    remote = Request({"type": "http", "headers": [(b"host", b"100.101.2.3:8080")], "client": ("100.90.1.1", 5000)})
    with pytest.raises(HTTPException) as raised:
        await endpoints_network.update_vpn_access(endpoints_network.VpnAccessUpdate(panel_access=True), remote)
    assert raised.value.status_code == 403
    assert not vpn_service.panel_access_enabled(tmp_path)
