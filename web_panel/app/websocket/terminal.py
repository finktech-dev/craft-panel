"""Endpoint WebSocket de la terminal administrativa en vivo."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import websocket_is_admin
from app.services.server_process import ServerProcessError, server_manager
from app.websocket.manager import connection_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ws", tags=["terminal"])


@router.websocket("/terminal")
async def terminal_socket(websocket: WebSocket) -> None:
    """Entrega historial, retransmite logs y reenvía comandos a STDIN."""
    if not await websocket_is_admin(websocket):
        await websocket.close(code=1008, reason="Autenticación de administrador requerida.")
        return
    await connection_manager.connect(websocket)
    await connection_manager.send_json(
        websocket,
        {
            "type": "history",
            "lines": server_manager.history,
            "state": server_manager.state,
        },
    )

    try:
        while True:
            command = _extract_command(await websocket.receive_text())
            try:
                await server_manager.send_command(command)
            except ServerProcessError as error:
                await connection_manager.send_json(websocket, {"type": "error", "message": str(error)})
            else:
                await connection_manager.send_json(websocket, {"type": "command_accepted", "command": command})
    except WebSocketDisconnect:
        logger.debug("Cliente desconectado de la terminal.")
    except ValueError as error:
        await connection_manager.send_json(websocket, {"type": "error", "message": str(error)})
    finally:
        connection_manager.disconnect(websocket)


def _extract_command(payload: str) -> str:
    """Acepta texto plano o ``{\"type\": \"command\", \"command\": \"...\"}``."""
    try:
        decoded: Any = json.loads(payload)
    except json.JSONDecodeError:
        return payload

    if not isinstance(decoded, Mapping) or decoded.get("type") != "command":
        raise ValueError("Formato de mensaje no válido para la terminal.")
    command = decoded.get("command")
    if not isinstance(command, str):
        raise ValueError("El campo command debe ser texto.")
    return command
