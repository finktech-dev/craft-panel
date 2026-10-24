"""Where the address for friends is saved: craftpanel.txt when it exists, else the panel."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from app.core.config import Settings
from app.services.server_settings_file import (
    FILENAME,
    SettingsFileError,
    ValidationContext,
    parse_public_address,
    server_settings_file,
)

logger = logging.getLogger(__name__)
_PANEL_FILE = ".server_connection.json"


class FriendAddressError(ValueError):
    """The address is not valid or could not be saved; the message is safe to show."""


def normalize_address(value: str) -> str:
    """``host`` or ``host:port`` without spaces or a scheme; raises :class:`FriendAddressError`."""
    address = value.strip()
    for prefix in ("minecraft://", "tcp://", "http://", "https://"):
        if address.casefold().startswith(prefix):
            address = address[len(prefix):]
    address = address.rstrip("/")
    if not address or any(character.isspace() for character in address):
        raise FriendAddressError("Escribí una dirección como mi-servidor.joinmc.link o mi-servidor.ply.gg:12345.")
    try:
        return parse_public_address(address, ValidationContext(server_directory=None))
    except ValueError as error:
        raise FriendAddressError(str(error)) from None


def _panel_file(configured: Settings) -> Path:
    assert configured.panel_directory is not None
    return configured.panel_directory / _PANEL_FILE


def panel_address(configured: Settings) -> str | None:
    """The address saved by the panel itself (Ajustes or onboarding)."""
    try:
        data = json.loads(_panel_file(configured).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("public_address") if isinstance(data, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def save_address(configured: Settings, value: str) -> Literal["craftpanel.txt", "panel"]:
    """Save a validated address; returns where it went."""
    address = normalize_address(value)
    if server_settings_file.path(configured).is_file():
        try:
            server_settings_file.save_fields(configured, values={"public_address": address})
        except SettingsFileError as error:
            problem = error.errors[0].message if error.errors else f"No se pudo guardar {FILENAME}."
            raise FriendAddressError(problem) from None
        return "craftpanel.txt"
    try:
        _panel_file(configured).write_text(json.dumps({"public_address": address}, indent=2), encoding="utf-8")
    except OSError as error:
        logger.warning("Could not save the friends address: %s", error.strerror)
        raise FriendAddressError("No se pudo guardar la dirección. Probá de nuevo.") from None
    return "panel"
