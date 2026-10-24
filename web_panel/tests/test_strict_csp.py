"""Strict CSP regression tests: no inline scripts or inline event handlers anywhere."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from main import app, templates

PANEL_ROOT = Path(__file__).parent.parent
TEMPLATE_NAMES = sorted(path.name for path in (PANEL_ROOT / "templates").glob("*.html"))
NON_EXECUTABLE_SCRIPT_TYPES = {"application/json", "application/ld+json", "text/template"}
INLINE_HANDLER = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)


class _InlineCodeFinder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.problems: list[str] = []
        self._inline_script: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        for name, value in attrs:
            if name.lower().startswith("on"):
                self.problems.append(f"<{tag} {name}=...>")
            if name.lower() in {"href", "src", "action", "formaction"} and (value or "").strip().lower().startswith("javascript:"):
                self.problems.append(f"<{tag} {name}=javascript:...>")
        if tag == "script":
            script_type = (values.get("type") or "").strip().lower()
            executable = script_type not in NON_EXECUTABLE_SCRIPT_TYPES
            self._inline_script = "" if executable and not values.get("src") else None

    def handle_data(self, data: str) -> None:
        if self._inline_script is not None:
            self._inline_script += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._inline_script is not None:
            self.problems.append(f"inline <script>: {self._inline_script.strip()[:60]!r}")
            self._inline_script = None


def _render(name: str, two_factor_enabled: bool) -> str:
    context = {
        "request": None,
        "current_page": name.removesuffix(".html"),
        "is_admin": True,
        "public_address": "play.example.invalid",
        "minecraft_version": "1.21.1",
        "two_factor_enabled": two_factor_enabled,
        "csrf_token": "test-csrf-token",
        "initial_admin_pin": "first-run-password",
    }
    return templates.env.get_template(name).render(**context)


@pytest.mark.parametrize("two_factor_enabled", [False, True])
@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_rendered_templates_have_no_inline_scripts_or_handlers(name: str, two_factor_enabled: bool) -> None:
    html = _render(name, two_factor_enabled)
    finder = _InlineCodeFinder()
    finder.feed(html)
    finder.close()
    assert finder.problems == [], f"{name}: {finder.problems}"
    assert not INLINE_HANDLER.search(re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)), name


def test_every_template_was_checked() -> None:
    # Guard against the glob silently finding nothing.
    assert {"base.html", "login.html", "console.html", "worlds.html", "administration.html"} <= set(TEMPLATE_NAMES)


@pytest.mark.parametrize("script", sorted((PANEL_ROOT / "static" / "js").glob("*.js")), ids=lambda path: path.name)
def test_html_built_by_scripts_has_no_inline_handlers(script: Path) -> None:
    source = script.read_text(encoding="utf-8")
    # Markup in template literals or strings such as `<img ... onerror="...">`.
    assert not re.search(r"<[a-z][^<>]*\son[a-z]+\s*=", source, re.IGNORECASE), script.name
    assert "javascript:" not in source.lower(), script.name
    assert not re.search(r"setAttribute\(\s*['\"]on[a-z]+", source), script.name


def test_csp_header_forbids_inline_scripts() -> None:
    client = TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 50000))
    for path in ("/", "/api/public/status"):
        csp = client.get(path).headers["content-security-policy"]
        directives = {part.strip().split()[0]: part.strip().split()[1:] for part in csp.split(";") if part.strip()}
        assert directives["script-src"] == ["'self'"]
        assert "'unsafe-inline'" not in directives["default-src"]
        assert directives["object-src"] == ["'none'"]
