"""Mesh VPNs on this PC (Tailscale, ZeroTier, Radmin VPN, Hamachi, NetBird, WireGuard).

Friends on the same VPN can join the Minecraft server through this PC's VPN
address, and the owner can open the panel from another device on it. Nothing
here talks to the VPN programs: adapters are recognised by their name or by the
address range each program uses, so any of them works the same way.

Opening the panel to the VPN is opt-in and stored in ``.network_settings.json``.
``run_panel`` binds the panel to 127.0.0.1 plus each VPN address found at start
(never to every network), and :func:`peer_is_allowed` rejects anyone else.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_SETTINGS_FILE = ".network_settings.json"


@dataclass(frozen=True, slots=True)
class _Kind:
    name: str
    keywords: tuple[str, ...]
    # Range the program hands out; an adapter inside it is recognised even with a custom name.
    network: str | None = None


_KINDS: tuple[_Kind, ...] = (
    _Kind("Tailscale", ("tailscale",), "100.64.0.0/10"),
    _Kind("NetBird", ("netbird", "wt0"), "100.64.0.0/10"),
    _Kind("ZeroTier", ("zerotier",)),
    _Kind("Radmin VPN", ("radmin",), "26.0.0.0/8"),
    _Kind("Hamachi", ("hamachi",), "25.0.0.0/8"),
    _Kind("WireGuard", ("wireguard",)),
)


@dataclass(frozen=True, slots=True)
class VpnNetwork:
    name: str
    adapter: str
    address: str
    network: ipaddress.IPv4Network

    def contains(self, host: str | None) -> bool:
        try:
            return host is not None and ipaddress.ip_address(host) in self.network
        except ValueError:
            return False


def _kind_for(adapter: str, address: ipaddress.IPv4Address) -> _Kind | None:
    lowered = adapter.casefold()
    for kind in _KINDS:
        if any(keyword in lowered for keyword in kind.keywords):
            return kind
    if lowered.startswith("wg"):
        return next(kind for kind in _KINDS if kind.name == "WireGuard")
    # Range fallback: 100.64/10 is shared by Tailscale and NetBird, so name it after the first.
    for kind in _KINDS:
        if kind.network and address in ipaddress.ip_network(kind.network):
            return kind
    return None


def detect(addresses=None, stats=None) -> list[VpnNetwork]:
    """VPN adapters that are up and have an IPv4 address; ``addresses``/``stats`` are for tests."""
    if addresses is None or stats is None:
        import psutil

        addresses = psutil.net_if_addrs() if addresses is None else addresses
        stats = psutil.net_if_stats() if stats is None else stats
    found: list[VpnNetwork] = []
    for adapter, entries in addresses.items():
        state = stats.get(adapter)
        if state is not None and not state.isup:
            continue
        for entry in entries:
            if entry.family != socket.AF_INET:
                continue
            try:
                address = ipaddress.IPv4Address(entry.address)
            except ValueError:
                continue
            if address.is_loopback or address.is_link_local:
                continue
            kind = _kind_for(adapter, address)
            if kind is None:
                continue
            if kind.network:
                network = ipaddress.IPv4Network(kind.network)
            else:
                network = ipaddress.IPv4Network(f"{address}/{entry.netmask or '255.255.255.0'}", strict=False)
            found.append(VpnNetwork(kind.name, adapter, str(address), network))
    return found


# --- Opening the panel to the VPN ---------------------------------------------------------


def _settings_path(panel_directory: Path) -> Path:
    return panel_directory / _SETTINGS_FILE


def panel_access_enabled(panel_directory: Path) -> bool:
    try:
        data = json.loads(_settings_path(panel_directory).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("panel_vpn_access") is True


def save_panel_access(panel_directory: Path, enabled: bool) -> None:
    target = _settings_path(panel_directory)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps({"panel_vpn_access": enabled}, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


class PanelVpnAccess:
    """The VPN networks the running panel listens on; set once by ``run_panel``."""

    def __init__(self) -> None:
        self.networks: tuple[VpnNetwork, ...] = ()
        # Only when the panel itself is bound to loopback does it restrict peers;
        # an owner who set panel_host to a LAN address keeps that behaviour.
        self.restrict_peers = False

    def activate(self, networks: list[VpnNetwork]) -> None:
        self.networks = tuple(networks)
        self.restrict_peers = True

    def peer_is_allowed(self, host: str | None) -> bool:
        if not self.restrict_peers or host is None:
            return True
        try:
            if ipaddress.ip_address(host).is_loopback:
                return True
        except ValueError:
            # Test clients and Unix sockets have no IP address.
            return True
        return any(network.contains(host) for network in self.networks)


panel_vpn_access = PanelVpnAccess()
