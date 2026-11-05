"""Registry and safe broadcasting for active WebSocket connections."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

_SEND_TIMEOUT_SECONDS = 2.0


class ConnectionManager:
    """Track connected clients and isolate one client's failures from the rest."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    @property
    def active_connection_count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def _send_text(self, websocket: WebSocket, message: str) -> None:
        try:
            await asyncio.wait_for(websocket.send_text(message), timeout=_SEND_TIMEOUT_SECONDS)
        except Exception:  # Closed, broken or too slow: drop it so it cannot hold back the others.
            logger.debug("Cliente WebSocket desconectado durante un envío.", exc_info=True)
            self.disconnect(websocket)

    async def send_json(self, websocket: WebSocket, payload: Mapping[str, Any]) -> None:
        await self._send_text(websocket, json.dumps(dict(payload)))

    async def broadcast_json(self, payload: Mapping[str, Any]) -> None:
        message = json.dumps(dict(payload))
        clients = tuple(self._connections)
        if clients:
            await asyncio.gather(*(self._send_text(websocket, message) for websocket in clients))


connection_manager = ConnectionManager()
