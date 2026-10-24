"""Discord chat bridge detection, and the status banner's text and font."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import ImageFont

from app.core.config import Settings
from app.schemas.mod import ModItem
from app.services import banner_service as banner_module
from app.services.banner_service import DEFAULT_TITLE, BannerService
from app.services.discord_bridge import DiscordBridgeService


class FakeMods:
    def __init__(self, items: list[ModItem]) -> None:
        self._items = items

    async def list_mods(self) -> list[ModItem]:
        return self._items


def _mod(filename: str, mod_id: str | None, enabled: bool = True) -> ModItem:
    return ModItem(filename=filename, name=filename, size_mb=1.0, is_enabled=enabled, modified_at="2026-10-24T00:00:00", mod_id=mod_id)


def _settings(tmp_path: Path) -> Settings:
    configured = Settings(project_root=tmp_path)
    assert configured.config_directory is not None
    configured.config_directory.mkdir(parents=True)
    return configured


@pytest.mark.asyncio
async def test_no_bridge_suggests_simple_discord_link(tmp_path: Path) -> None:
    status = await DiscordBridgeService(_settings(tmp_path), FakeMods([_mod("jei.jar", "jei")])).status()
    assert status.installed is False
    assert status.suggestion.name == "Simple Discord Link"
    assert status.suggestion.modrinth_url == "https://modrinth.com/mod/sdlink"


@pytest.mark.asyncio
async def test_bridge_found_by_mod_id_with_its_settings_file(tmp_path: Path) -> None:
    configured = _settings(tmp_path)
    folder = configured.config_directory / "simple-discord-link"
    (folder / "embeds").mkdir(parents=True)
    (folder / "embeds" / "default.json").write_text("{}", encoding="utf-8")
    (folder / "simple-discord-link.toml").write_text("botToken = ''\n", encoding="utf-8")
    status = await DiscordBridgeService(configured, FakeMods([_mod("SimpleDiscordLink-Universal-3.4.5.jar", "sdlink")])).status()
    assert status.installed and status.enabled
    assert status.name == "Simple Discord Link"
    assert status.config_file == "simple-discord-link/simple-discord-link.toml"


@pytest.mark.asyncio
async def test_bridge_found_by_file_name_and_reported_when_off(tmp_path: Path) -> None:
    mods = FakeMods([_mod("Mc2Discord-neoforge-4.3.1.jar.disabled", None, enabled=False)])
    status = await DiscordBridgeService(_settings(tmp_path), mods).status()
    assert status.installed is True
    assert status.enabled is False
    assert status.name == "Mc2Discord"
    assert status.config_file is None


def test_banner_speaks_spanish_and_uses_a_font_with_accents(tmp_path: Path) -> None:
    drawn: list[str] = []
    original_text = banner_module.ImageDraw.ImageDraw.text

    def spy(self, xy, text, *args, **kwargs):
        drawn.append(text)
        return original_text(self, xy, text, *args, **kwargs)

    metrics = SimpleNamespace(get_server_metrics=lambda: SimpleNamespace(is_running=False, ram_used_mb=0))
    tunnel = SimpleNamespace(status=lambda: SimpleNamespace(public_address=None))
    service = BannerService(Settings(project_root=tmp_path, public_address=""), metrics, tunnel)
    try:
        banner_module.ImageDraw.ImageDraw.text = spy
        png = service.generate_status_banner()
    finally:
        banner_module.ImageDraw.ImageDraw.text = original_text
    assert png.startswith(b"\x89PNG")
    assert DEFAULT_TITLE in drawn
    assert "Apagado" in drawn
    assert "Todavía no hay dirección para compartir" in drawn
    assert not any(word in " ".join(drawn) for word in ("OFFLINE", "ONLINE", "RAM", "server status"))
    # On Windows a system font with accents is used instead of Pillow's bundled one.
    font = banner_module._font(16)
    if any(path.is_file() for path in banner_module._font_candidates(False)):
        assert isinstance(font, ImageFont.FreeTypeFont)
        assert font.getmask("ó").getbbox() is not None
