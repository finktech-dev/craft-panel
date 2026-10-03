"""Regression coverage for the read-only host readiness page."""

from pathlib import Path

from starlette.testclient import TestClient
from starlette.templating import Jinja2Templates

from main import app


def test_setup_template_uses_read_only_runtime_endpoint() -> None:
    local_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
    template = local_templates.get_template("setup.html")
    rendered = template.render(
        request={"type": "http", "method": "GET", "path": "/setup", "headers": []},
        current_page="setup", is_admin=True, public_address="", minecraft_version="1.21.1",
        two_factor_enabled=False, csrf_token="test",
    )
    assert "/static/js/setup.js" in rendered
    javascript = Path(__file__).parent.parent / "static" / "js" / "setup.js"
    source = javascript.read_text(encoding="utf-8")
    assert "/api/runtime/discovery" in source
    assert "/api/tunnel/status" in source
    assert "playit_enabled" in source
    assert "local-only" in rendered


def test_setup_page_requires_an_admin_session() -> None:
    client = TestClient(app, raise_server_exceptions=True)
    response = client.get("/setup", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
