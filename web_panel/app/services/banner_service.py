"""Banner PNG público con una fotografía instantánea del estado del servidor."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from app.core.config import Settings, settings
from app.services.metrics_service import MetricsService, metrics_service
from app.services.playit_service import PlayitService, playit_service


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

    def generate_status_banner(self) -> bytes:
        metrics = self._metrics.get_server_metrics()
        tunnel = self._tunnel.status()
        online = metrics.is_running
        state_label = "ONLINE · objetivo 20.0 TPS" if online else "OFFLINE"
        state_color = (52, 211, 153) if online else (251, 113, 133)
        ram_used_gb = metrics.ram_used_mb / 1024
        public_address = tunnel.public_address or self._settings.server_public_address or "Dirección aún no asignada"

        image = Image.new("RGB", (600, 160), (18, 21, 27))
        draw = ImageDraw.Draw(image)
        title_font = _font(22)
        body_font = _font(15)
        small_font = _font(12)
        draw.rounded_rectangle((1, 1, 598, 158), radius=14, outline=(190, 148, 64), width=2, fill=(24, 24, 27))
        draw.rectangle((20, 22, 25, 136), fill=(190, 148, 64))
        draw.text((43, 21), self._settings.banner_title, fill=(250, 204, 21), font=title_font)
        draw.text((43, 50), f"NeoForge {self._settings.minecraft_version}", fill=(161, 161, 170), font=small_font)
        draw.ellipse((43, 83, 55, 95), fill=state_color)
        draw.text((65, 80), state_label, fill=(244, 244, 245), font=body_font)
        draw.text((43, 111), f"RAM  {ram_used_gb:.1f} GB / {self._settings.allocated_ram_gb:.1f} GB", fill=(212, 212, 216), font=body_font)
        draw.text((330, 111), public_address, fill=(110, 231, 183), font=small_font)

        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()


def _font(size: int) -> ImageFont.ImageFont:
    """La fuente incluida por Pillow evita depender de fuentes del sistema Windows."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Compatibilidad con versiones Pillow más antiguas.
        return ImageFont.load_default()


banner_service = BannerService()
