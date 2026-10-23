"""Regression tests for authentication, sessions, CSRF, Host checks and headers."""

from __future__ import annotations

import time
from pathlib import Path

import pyotp
import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core import security
from app.core.config import settings
from app.core.rate_limit import limiter
from main import app

PIN = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def _isolated_auth_state(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "admin_pin", SecretStr(PIN))
    monkeypatch.setattr(security.totp_manager, "_secret_path", tmp_path / ".totp_secret")
    monkeypatch.setattr(security.totp_manager, "_last_used_counter", -1)
    security.login_attempt_tracker._attempts.clear()
    security.global_login_failures._attempts.clear()
    security._revoked_sessions.entries.clear()
    limiter.reset()
    yield
    security.login_attempt_tracker._attempts.clear()
    security.global_login_failures._attempts.clear()


def _client(peer: str = "127.0.0.1", **kwargs) -> TestClient:
    return TestClient(app, base_url="http://127.0.0.1:8080", client=(peer, 50000), **kwargs)


def _login(client: TestClient, pin: str = PIN, **kwargs):
    return client.post("/api/auth/login", json={"pin": pin}, **kwargs)


def _csrf(client: TestClient) -> str:
    page = client.get("/")
    marker = 'name="csrf-token" content="'
    start = page.text.index(marker) + len(marker)
    return page.text[start : page.text.index('"', start)]


@pytest.mark.parametrize("host", ["evil.example", "attacker.rebind.network:8080", "localhost.evil.example"])
def test_forged_host_header_is_rejected(host: str) -> None:
    response = _client().get("/api/public/status", headers={"host": host})
    assert response.status_code == 400


@pytest.mark.parametrize("host", ["127.0.0.1:8080", "localhost:8080", "[::1]:8080", "192.168.1.20:8080", "abc-def.trycloudflare.com"])
def test_loopback_lan_and_quick_tunnel_hosts_are_allowed(host: str) -> None:
    assert _client().get("/api/public/status", headers={"host": host}).status_code == 200


def test_configured_reverse_proxy_domain_is_allowed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "allowed_hosts", ["*.example.org"])
    assert _client().get("/api/public/status", headers={"host": "panel.example.org"}).status_code == 200


def test_cross_site_login_is_rejected() -> None:
    response = _login(_client(), headers={"origin": "https://evil.example"})
    assert response.status_code == 403


def test_state_change_without_csrf_token_is_rejected() -> None:
    client = _client()
    assert _login(client).status_code == 200
    assert client.post("/api/backups/audit").status_code == 403
    token = _csrf(client)
    assert client.post("/api/auth/logout", headers={"x-csrf-token": token}).status_code == 204


def test_wrong_pin_locks_out_after_five_attempts() -> None:
    client = _client(peer="203.0.113.7")
    statuses = [_login(client, pin="wrong-password-123").status_code for _ in range(5)]
    assert statuses[:4] == [401] * 4 and statuses[4] == 429
    # Even the right PIN is refused while the IP is locked.
    assert _login(client).status_code == 429


def test_rotating_forwarded_ips_hits_the_global_limit() -> None:
    client = _client()
    codes = [
        _login(client, pin="wrong-password-123", headers={"x-forwarded-for": f"198.51.100.{index}"}).status_code
        for index in range(31)
    ]
    assert codes[-1] == 429
    # The owner at the PC (no proxy headers) is never locked out by remote attempts.
    assert _login(client).status_code == 200


def test_non_ascii_pin_does_not_crash() -> None:
    assert _login(_client(), pin="contraseña-ñandú-✓").status_code == 401


def test_logout_revokes_a_copied_cookie() -> None:
    client = _client()
    assert _login(client).status_code == 200
    stolen = dict(client.cookies)
    token = _csrf(client)
    assert client.post("/api/auth/logout", headers={"x-csrf-token": token}).status_code == 204
    replay = _client(cookies=stolen)
    assert replay.get("/api/access/me").status_code == 401


def test_session_has_an_absolute_lifetime(monkeypatch) -> None:
    client = _client()
    assert _login(client).status_code == 200
    assert client.get("/api/access/me").status_code == 200
    future = time.time() + settings.session_max_age_seconds + 5
    monkeypatch.setattr(security.time, "time", lambda: future)
    assert client.get("/api/access/me").status_code == 401


def test_login_rotates_the_session_cookie() -> None:
    client = _client()
    assert _login(client).status_code == 200
    first = client.cookies.get("minecraft_panel_session")
    assert _login(client).status_code == 200
    assert client.cookies.get("minecraft_panel_session") != first


def test_first_run_password_is_only_shown_on_this_pc(monkeypatch) -> None:
    monkeypatch.setattr(settings, "_admin_pin_generated_this_start", True)
    assert PIN in _client().get("/").text
    assert PIN not in _client().get("/", headers={"x-forwarded-for": "203.0.113.9"}).text
    assert PIN not in _client().get("/", headers={"host": "abc.trycloudflare.com"}).text
    assert PIN not in _client(peer="192.168.1.50").get("/", headers={"host": "192.168.1.10:8080"}).text


def test_oversized_bodies_are_rejected_before_parsing() -> None:
    response = _client().post(
        "/api/auth/login", content=b"{" + b" " * (2 * 1024 * 1024) + b"}", headers={"content-type": "application/json"}
    )
    assert response.status_code == 413


def test_security_headers_and_no_store() -> None:
    response = _client().get("/")
    csp = response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert "img-src 'self' data: https://mc-heads.net https://cdn.modrinth.com" in csp
    assert "ws: " not in csp
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"


def test_cookie_is_secure_when_reached_through_an_https_tunnel() -> None:
    client = _client()
    response = _login(client, headers={"x-forwarded-proto": "https", "host": "abc.trycloudflare.com"})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "strict-transport-security" in response.headers


def test_websocket_from_another_origin_is_refused() -> None:
    client = _client()
    assert _login(client).status_code == 200
    token = _csrf(client)
    # The test client always dials ws://testserver, so Host and cookie are set by hand.
    base_headers = {
        "host": "127.0.0.1:8080",
        "cookie": f"minecraft_panel_session={client.cookies.get('minecraft_panel_session')}",
    }
    with client.websocket_connect(
        f"/ws/terminal?csrf={token}", headers={**base_headers, "origin": "http://127.0.0.1:8080"}
    ) as socket:
        assert socket.receive_json()["type"] == "history"
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/ws/terminal?csrf={token}", headers={**base_headers, "origin": "https://evil.example"}
        ) as socket:
            socket.receive_json()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/ws/terminal?csrf={token}", headers={**base_headers, "host": "evil.example"}
        ) as socket:
            socket.receive_json()


def test_totp_codes_cannot_be_replayed() -> None:
    manager = security.totp_manager
    secret = manager.begin_setup()
    assert manager.verify_setup_code(pyotp.TOTP(secret).now())
    code = pyotp.TOTP(secret).now()
    assert manager.verify_login_code(code) is True
    assert manager.verify_login_code(code) is False


def test_restarting_2fa_setup_keeps_the_active_factor() -> None:
    manager = security.totp_manager
    secret = manager.begin_setup()
    assert manager.verify_setup_code(pyotp.TOTP(secret).now())
    manager.begin_setup()
    assert manager.is_enabled
    assert manager.verify_login_code(None) is False


def test_api_docs_are_not_published() -> None:
    client = _client()
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_public_endpoints_need_no_session_and_admin_ones_do() -> None:
    client = _client()
    assert client.get("/api/public/status").status_code == 200
    assert client.get("/api/auth/2fa/status").status_code == 200
    assert client.get("/api/server/banner.png").status_code == 200
    for path in ("/api/backups", "/api/mods", "/api/configs", "/api/tunnel/status", "/api/discord/config"):
        assert client.get(path).status_code == 401, path


def test_static_files_cannot_escape_the_static_folder() -> None:
    client = _client()
    for path in ("/static/..%2f..%2fmain.py", "/static/../main.py", "/static/%2e%2e/.panel_secrets.json"):
        response = client.get(path)
        assert response.status_code == 404, path
