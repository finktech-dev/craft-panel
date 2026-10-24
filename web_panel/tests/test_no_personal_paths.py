"""The panel never shows paths that reveal the host's Windows user folder."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from main import templates

PANEL_ROOT = Path(__file__).parent.parent
TEMPLATE_NAMES = sorted(path.name for path in (PANEL_ROOT / "templates").glob("*.html") if not path.name.startswith("_"))
# C:\Users\name, c:/users/name or an escaped C:\\Users\\name inside a script string.
USER_FOLDER = re.compile(r"[a-z]:(\\{1,2}|/)users(\\{1,2}|/)", re.IGNORECASE)


def _render(name: str) -> str:
    context = {
        "request": None,
        "current_page": name.removesuffix(".html"),
        "is_admin": True,
        "public_address": "play.example.invalid",
        "minecraft_version": "1.21.1",
        "two_factor_enabled": False,
        "csrf_token": "test-csrf-token",
        "initial_admin_pin": "first-run-password",
    }
    return templates.env.get_template(name).render(**context)


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_rendered_pages_show_no_user_folder_paths(name: str) -> None:
    html = _render(name)
    assert not USER_FOLDER.search(html), f"{name} shows a path inside a Windows user folder"
    assert "\\Users\\" not in html, name


@pytest.mark.parametrize("script", sorted((PANEL_ROOT / "static" / "js").glob("*.js")), ids=lambda path: path.name)
def test_page_scripts_hold_no_user_folder_paths(script: Path) -> None:
    assert not USER_FOLDER.search(script.read_text(encoding="utf-8")), script.name


def test_every_page_was_checked() -> None:
    assert {"administration.html", "worlds.html", "backups.html", "mods.html", "console.html"} <= set(TEMPLATE_NAMES)
