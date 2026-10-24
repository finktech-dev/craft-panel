"""Public PNG banner with a snapshot of the server status."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.core.config import Settings, settings
from app.services.metrics_service import MetricsService, metrics_service
from app.services.playit_service import PlayitService, playit_service
from app.services.server_version_service import ServerVersionService

DEFAULT_TITLE = "Servidor de Minecraft"


class BannerService:
    def __init__(
        self,
        configured_settings: Settings = settings,
        metrics: MetricsService = metrics_service,
        tunnel: PlayitService = playit_service,
    ) -> None:
        self._settings = configured_settings
        self._metrics = metrics
        self._tunnel = tunnel
        self._versions = ServerVersionService(configured_settings)

    def generate_status_banner(self) -> bytes:
        metrics = self._metrics.get_server_metrics()
        tunnel = self._tunnel.status()
        online = metrics.is_running
        state_label = "Encendido" if online else "Apagado"
        state_color = (136, 189, 86) if online else (236, 122, 106)
        ram_used_gb = metrics.ram_used_mb / 1024
        public_address = tunnel.public_address or self._settings.effective_public_address
        address_label = public_address or "Todavía no hay dirección para compartir"

        image = Image.new("RGB", (600, 160), (26, 25, 24))
        draw = ImageDraw.Draw(image)
        title_font = _font(24, bold=True)
        body_font = _font(16)
        small_font = _font(13)
        draw.rounded_rectangle((1, 1, 598, 158), radius=14, outline=(51, 50, 47), width=2, fill=(34, 33, 32))
        draw.rectangle((20, 22, 25, 136), fill=state_color)
        title = self._settings.effective_server_name or self._settings.banner_title.strip() or DEFAULT_TITLE
        draw.text((43, 18), _fit(draw, title, title_font, 530), fill=(247, 246, 243), font=title_font)
        subtitle = (
            self._settings.banner_subtitle.strip()
            or self._settings.discord_server_software_label.strip()
            or self._versions.detect().label
            or "Minecraft"
        )
        draw.text((43, 52), _fit(draw, subtitle, small_font, 530), fill=(162, 158, 149), font=small_font)
        draw.ellipse((43, 86, 55, 98), fill=state_color)
        draw.text((64, 81), state_label, fill=(247, 246, 243), font=body_font)
        if online:
            draw.text((180, 83), f"Memoria {ram_used_gb:.1f} de {self._settings.effective_ram_gb:.0f} GB".replace(".", ","), fill=(194, 191, 183), font=small_font)
        draw.text((43, 118), _fit(draw, address_label, small_font, 530), fill=(163, 208, 119) if public_address else (162, 158, 149), font=small_font)

        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()


def _fit(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> str:
    """Shorten text with an ellipsis so it never runs past the card."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(f"{text}…", font=font) > width:
        text = text[:-1]
    return f"{text.rstrip()}…"


def _font_candidates(bold: bool) -> list[Path]:
    """Fonts with accents (á, é, ñ). Pillow's bundled one lacks them and draws boxes."""
    names = ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"]
    folders: list[Path] = []
    if sys.platform == "win32":
        folders.append(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts")
    folders += [Path("/usr/share/fonts/truetype/dejavu"), Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental")]
    return [folder / name for name in names for folder in folders]


@lru_cache(maxsize=8)
def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    for candidate in _font_candidates(bold):
        if candidate.is_file():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Older Pillow versions.
        return ImageFont.load_default()


banner_service = BannerService()
