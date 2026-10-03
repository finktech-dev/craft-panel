"""Registro y difusión segura de conexiones WebSocket activas."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Mantiene clientes conectados y aísla fallos de un cliente del resto."""

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

    async def send_json(self, websocket: WebSocket, payload: Mapping[str, Any]) -> None:
        try:
            await websocket.send_json(dict(payload))
        except Exception:  # El socket puede cerrarse entre el receive y el send.
            logger.debug("Cliente WebSocket desconectado durante un envío.", exc_info=True)
            self.disconnect(websocket)

    async def broadcast_json(self, payload: Mapping[str, Any]) -> None:
        for websocket in tuple(self._connections):
            await self.send_json(websocket, payload)


connection_manager = ConnectionManager()
