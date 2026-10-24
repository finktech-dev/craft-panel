"""Lanzador limpio y elegante del panel web sin trazas de error al cerrar."""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
import urllib.request
import webbrowser
import uvicorn

from app.core.config import settings

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

def main() -> None:
    _configure_windows_event_loop()

    threading.Thread(target=_open_browser_when_ready, daemon=True, name="open-panel-browser").start()

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
        # En Windows, server.run() envuelve el bucle de asyncio
        server.run()
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
        pass
    finally:
        print("\n" + "=" * 50)
        print("  [Panel Web] Apagado ordenado completado.")
        print("=" * 50)


if __name__ == "__main__":
    main()
