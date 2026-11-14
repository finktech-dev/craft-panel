"""Set the server-list icon (``server-icon.png``) shown next to the server in Minecraft.

Minecraft only reads a 64x64 PNG named ``server-icon.png`` from the server folder, and
only at startup. This service takes any photo the user uploads, crops it to a square and
shrinks it to 64x64, so they never have to resize it by hand.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from app.core.config import Settings, settings

_ICON_NAME = "server-icon.png"
_ICON_SIZE = 64
_CHUNK_SIZE = 256 * 1024
# A source photo, not the final icon (which ends up a few KB after shrinking to 64x64).
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024


class ServerIconError(Exception):
    """A friendly, user-facing problem while setting the icon."""


class ServerIconService:
    def __init__(self, configured_settings: Settings = settings) -> None:
        self._settings = configured_settings

    def _server_dir(self) -> Path:
        directory = self._settings.server_directory
        if directory is None or not directory.is_dir():
            raise ServerIconError("Todavía no hay un servidor instalado.")
        return directory

    def icon_path(self) -> Path:
        return self._server_dir() / _ICON_NAME

    def has_icon(self) -> bool:
        try:
            return self.icon_path().is_file()
        except ServerIconError:
            return False

    def read_icon(self) -> bytes | None:
        if not self.has_icon():
            return None
        try:
            return self.icon_path().read_bytes()
        except OSError:
            return None

    async def set_icon(self, uploaded_file: UploadFile) -> None:
        raw = await self._read_capped(uploaded_file)
        png = await asyncio.to_thread(self._to_icon_png, raw)
        await asyncio.to_thread(self._write_atomic, png)

    async def remove_icon(self) -> None:
        path = self.icon_path()
        await asyncio.to_thread(self._unlink, path)

    async def _read_capped(self, uploaded_file: UploadFile) -> bytes:
        buffer = bytearray()
        try:
            while chunk := await uploaded_file.read(_CHUNK_SIZE):
                buffer += chunk
                if len(buffer) > _MAX_UPLOAD_BYTES:
                    raise ServerIconError("La imagen es muy grande (máximo 8 MB).")
        finally:
            await uploaded_file.close()
        if not buffer:
            raise ServerIconError("No recibimos ninguna imagen.")
        return bytes(buffer)

    def _to_icon_png(self, raw: bytes) -> bytes:
        try:
            with Image.open(io.BytesIO(raw)) as image:
                square = _center_square(image.convert("RGBA"))
                icon = square.resize((_ICON_SIZE, _ICON_SIZE), Image.LANCZOS)
                output = io.BytesIO()
                icon.save(output, format="PNG")
                return output.getvalue()
        except (UnidentifiedImageError, OSError, ValueError) as error:
            raise ServerIconError("No pudimos leer la imagen. Probá con un PNG o un JPG.") from error

    def _write_atomic(self, png: bytes) -> None:
        path = self.icon_path()
        tmp = path.with_name(f".{path.name}.tmp")
        try:
            tmp.write_bytes(png)
            tmp.replace(path)
        except OSError as error:
            raise ServerIconError(f"No se pudo guardar la imagen: {error}") from error

    def _unlink(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise ServerIconError(f"No se pudo quitar la imagen: {error}") from error


def _center_square(image: Image.Image) -> Image.Image:
    """Crop to the largest centered square so the icon is filled, never stretched."""
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


server_icon_service = ServerIconService()
