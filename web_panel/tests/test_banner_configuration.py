"""The public banner must not contain source-server branding."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.services.banner_service import BannerService


def test_banner_title_is_configurable(tmp_path: Path) -> None:
    configured = Settings(project_root=tmp_path, banner_title="Friends' server")
    assert configured.banner_title == "Friends' server"


def test_banner_service_has_no_source_server_tagline() -> None:
    source = Path(__file__).parents[1] / "app" / "services" / "banner_service.py"
    assert "host-specific-server-name" not in source.read_text(encoding="utf-8").lower()
