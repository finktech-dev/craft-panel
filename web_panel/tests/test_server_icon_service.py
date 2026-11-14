"""The server-icon service turns any photo into a 64x64 PNG named server-icon.png."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from app.services.server_icon_service import ServerIconError, ServerIconService
from tests.test_server_settings_file import settings_for


class _Upload:
    """Minimal stand-in for Starlette's UploadFile (read in chunks, then close)."""

    def __init__(self, data: bytes) -> None:
        self._buffer = io.BytesIO(data)
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)

    async def close(self) -> None:
        self.closed = True


def _png(width: int, height: int, color=(10, 120, 200, 255)) -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", (width, height), color).save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_set_icon_writes_a_64x64_png(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    service = ServerIconService(configured)

    await service.set_icon(_Upload(_png(500, 320)))

    icon = configured.server_directory / "server-icon.png"
    assert icon.is_file()
    assert service.has_icon()
    with Image.open(icon) as image:
        assert image.size == (64, 64)
        assert image.format == "PNG"


@pytest.mark.asyncio
async def test_remove_icon_deletes_the_file(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    service = ServerIconService(configured)
    await service.set_icon(_Upload(_png(64, 64)))
    assert service.has_icon()

    await service.remove_icon()

    assert not service.has_icon()
    assert service.read_icon() is None
    # Removing again is harmless (no server-icon.png to delete).
    await service.remove_icon()


@pytest.mark.asyncio
async def test_set_icon_rejects_a_file_that_is_not_an_image(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    service = ServerIconService(configured)

    with pytest.raises(ServerIconError):
        await service.set_icon(_Upload(b"this is not an image"))
    assert not service.has_icon()


@pytest.mark.asyncio
async def test_set_icon_rejects_an_empty_upload(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    service = ServerIconService(configured)

    with pytest.raises(ServerIconError):
        await service.set_icon(_Upload(b""))
