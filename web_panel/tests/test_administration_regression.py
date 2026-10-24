"""Regression tests for the admin panel and its JS modules."""

import pathlib
import pytest
from starlette.testclient import TestClient

from main import app, templates
from app.core.security import get_current_admin


@pytest.fixture
def client():
    # TestClient unauthenticated
    return TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=True)


@pytest.fixture
def auth_client():
    # TestClient authenticated via dependency override
    app.dependency_overrides[get_current_admin] = lambda: "session"
    client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=True)
    yield client
    app.dependency_overrides.pop(get_current_admin, None)


def test_modular_js_files_exist():
    """Check that the 5 modular JavaScript files exist on disk and are not empty."""
    js_dir = pathlib.Path(__file__).parent.parent / "static" / "js"
    expected_files = [
        "admin-tabs.js",
        "admin-configs.js",
        "admin-restrictions.js",
        "admin-ranks.js",
        "admin-discord.js",
    ]
    for fname in expected_files:
        fpath = js_dir / fname
        assert fpath.is_file(), f"Falta el archivo estático {fname}"
        content = fpath.read_text(encoding="utf-8")
        assert len(content.strip()) > 500, f"El archivo {fname} parece estar incompleto o truncado ({len(content)} bytes)"


def test_administration_html_contains_modular_scripts():
    """Check that administration.html includes the <script> tags in the right order."""
    template_path = pathlib.Path(__file__).parent.parent / "templates" / "administration.html"
    assert template_path.is_file()
    html = template_path.read_text(encoding="utf-8")

    assert '<script src="/static/js/admin-tabs.js"></script>' in html
    assert '<script src="/static/js/admin-configs.js"></script>' in html
    assert '<script src="/static/js/admin-restrictions.js"></script>' in html
    assert '<script src="/static/js/admin-ranks.js"></script>' in html
    assert '<script src="/static/js/admin-discord.js"></script>' in html

    # Check that no inline <script> tag was left unclosed
    assert html.count("<script>") == 0, "No debe haber bloques <script> inline sin modularizar en administration.html"


def test_administration_master_tabs_structure():
    """Check that the 4 isolated top-level tabs exist and are well formed."""
    template_path = pathlib.Path(__file__).parent.parent / "templates" / "administration.html"
    html = template_path.read_text(encoding="utf-8")

    assert 'id="admin-master-tabs"' in html
    assert 'id="panel-master-ranks"' in html
    assert 'id="panel-master-rules"' in html
    assert 'id="panel-master-configs"' in html
    assert 'id="panel-master-discord"' in html


def test_administration_template_renders_cleanly():
    """Check that Jinja2 can compile and render administration.html without syntax errors."""
    dummy_request = {"type": "http", "method": "GET", "path": "/administration", "headers": []}
    from starlette.requests import Request
    req = Request(dummy_request)
    context = {
        "request": req,
        "current_page": "administration",
        "is_admin": True,
        "public_address": "127.0.0.1:25565",
        "minecraft_version": "1.21.1",
        "two_factor_enabled": False,
        "csrf_token": "test-csrf-token",
    }
    rendered = templates.get_template("administration.html").render(context)
    assert '<html' in rendered or '<section' in rendered
    assert '/static/js/admin-tabs.js' in rendered
    assert '/static/js/admin-configs.js' in rendered
    assert '/static/js/admin-restrictions.js' in rendered
    assert '/static/js/admin-ranks.js' in rendered
    assert '/static/js/admin-discord.js' in rendered


def test_static_assets_http_delivery(client):
    """Check that FastAPI serves the 5 JS files over HTTP with status 200."""
    endpoints = [
        "/static/js/admin-tabs.js",
        "/static/js/admin-configs.js",
        "/static/js/admin-restrictions.js",
        "/static/js/admin-ranks.js",
        "/static/js/admin-discord.js",
    ]
    for ep in endpoints:
        res = client.get(ep)
        assert res.status_code == 200, f"Error al servir {ep}: {res.status_code}"
        assert len(res.text) > 500, f"Respuesta vacía o muy corta para {ep}"


def test_administration_route_auth_redirect(client):
    """Check that an anonymous user is redirected to login when opening /administration."""
    res = client.get("/administration", follow_redirects=False)
    assert res.status_code in (302, 303, 307)
    assert res.headers["location"] == "/"


def test_healthcheck(client):
    """Check that the panel answers the system health check."""
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"


def test_api_endpoints_contracts_authenticated(auth_client):
    """Check that the REST endpoints used by the 4 JS modules exist and return valid data."""
    # 1. WorldEdit status
    we_res = auth_client.get("/api/worldedit/status")
    assert we_res.status_code == 200
    assert "enabled" in we_res.json()

    # 2. Restrictions summary
    sum_res = auth_client.get("/api/restrictions/summary")
    assert sum_res.status_code == 200
    data = sum_res.json()
    assert "blocked_items" in data
    assert "blocked_mobs" in data
    assert "disabled_villagers" in data

    # 3. Restrictions catalog
    cat_res = auth_client.get("/api/restrictions/catalog")
    assert cat_res.status_code == 200
    cat_data = cat_res.json()
    assert "items" in cat_data
    assert "mobs" in cat_data
    assert "villagers" in cat_data

    # 4. Discord config
    disc_res = auth_client.get("/api/discord/config")
    assert disc_res.status_code == 200
    disc_data = disc_res.json()
    assert "webhook_url" in disc_data
    assert "events_webhook_url" in disc_data
