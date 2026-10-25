"""Starts the web panel and exits quietly, without error traces, when it is closed."""

from __future__ import annotations

import asyncio
import logging
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
import uvicorn

from app.core.config import settings
from app.services import vpn_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("panel")


def _configure_windows_event_loop() -> None:
    """Use the Windows event loop implementation that supports subprocesses."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def _browser_host(host: str) -> str:
    """A wildcard bind address (0.0.0.0, ::) cannot be opened in a browser; use this PC."""
    if host in {"0.0.0.0", "::", ""}:
        return "127.0.0.1"
    return f"[{host}]" if ":" in host else host


def _open_browser_when_ready() -> None:
    """Avoid opening localhost before Uvicorn is actually listening."""
    base_url = f"http://{_browser_host(settings.panel_host)}:{settings.panel_port}"
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=0.5) as response:
                if response.status == 200:
                    webbrowser.open(base_url)
                    return
        except OSError:
            time.sleep(0.25)

def _vpn_sockets() -> list[socket.socket] | None:
    """Loopback plus each VPN address, when the owner opened the panel to the VPN.

    Never a wildcard address: Wi-Fi and the home network keep not reaching the panel.
    Returns ``None`` to let Uvicorn bind ``panel_host`` as usual.
    """
    if settings.panel_mode != "local" or settings.panel_host not in {"127.0.0.1", "localhost"}:
        return None
    assert settings.panel_directory is not None
    if not vpn_service.panel_access_enabled(settings.panel_directory):
        return None
    networks = vpn_service.detect()
    if not networks:
        logger.info("Panel access through a VPN is on, but no VPN is connected; only this PC can open the panel.")
        return None
    sockets: list[socket.socket] = []
    bound: list[vpn_service.VpnNetwork] = []
    for host, network in [("127.0.0.1", None), *((network.address, network) for network in networks)]:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind((host, settings.panel_port))
        except OSError as error:
            listener.close()
            if network is None:
                raise
            logger.warning("Could not open the panel on %s: %s", network.name, error.strerror)
            continue
        listener.set_inheritable(True)
        sockets.append(listener)
        if network is not None:
            bound.append(network)
            logger.info("Panel also reachable through %s at http://%s:%s", network.name, network.address, settings.panel_port)
    vpn_service.panel_vpn_access.activate(bound)
    return sockets


def main() -> None:
    _configure_windows_event_loop()

    threading.Thread(target=_open_browser_when_ready, daemon=True, name="open-panel-browser").start()
    sockets = _vpn_sockets()

    config = uvicorn.Config(
        "main:app",
        host=settings.panel_host,
        port=settings.panel_port,
        log_level="info",
        access_log=True,
        # Uvicorn's reload worker selects WindowsSelectorEventLoopPolicy, which
        # cannot create subprocesses. The panel needs them to run Minecraft.
        reload=False,
    )
    server = uvicorn.Server(config)

    if settings.admin_pin_generated_this_start:
        print("[Panel Web] Se generó una contraseña de administrador nueva.")
        print("[Panel Web] Abrí el panel en esta PC para verla una sola vez y guardala en un lugar seguro.")

    try:
        # On Windows, server.run() wraps the asyncio loop
        server.run(sockets=sockets)
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
        pass
    finally:
        print("\n" + "=" * 50)
        print("  [Panel Web] Apagado ordenado completado.")
        print("=" * 50)


if __name__ == "__main__":
    main()
