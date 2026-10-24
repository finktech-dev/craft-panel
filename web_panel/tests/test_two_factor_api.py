"""Regression tests for the 2FA endpoints used by the Ajustes page."""

from __future__ import annotations

import json
from pathlib import Path

import pyotp
import pytest
from starlette.testclient import TestClient

from app.core import security
from app.core.config import settings
from app.core.passwords import hash_password
from app.core.rate_limit import limiter
from main import app

PIN = "correct-horse-battery-staple"
PIN_HASH = hash_password(PIN, log2_n=10)


@pytest.fixture(autouse=True)
def _isolated_auth_state(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "_admin_password_hash", PIN_HASH)
    monkeypatch.setattr(settings, "_initial_admin_password", None)
    monkeypatch.setattr(settings, "_admin_pin_generated_this_start", False)
    monkeypatch.setattr(security.totp_manager, "_secret_path", tmp_path / ".totp_secret")
    monkeypatch.setattr(security.totp_manager, "_last_used_counter", -1)
    security.login_attempt_tracker._attempts.clear()
    security.global_login_failures._attempts.clear()
    limiter.reset()
    yield
    security.login_attempt_tracker._attempts.clear()


def _signed_in_client() -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 50000))
    assert client.post("/api/auth/login", json={"pin": PIN}).status_code == 200
    page = client.get("/")
    marker = 'name="csrf-token" content="'
    start = page.text.index(marker) + len(marker)
    return client, {"x-csrf-token": page.text[start : page.text.index('"', start)]}


def _enable(client: TestClient, headers: dict[str, str]) -> str:
    setup = client.post("/api/auth/2fa/setup", json={}, headers=headers)
    assert setup.status_code == 200
    body = setup.json()
    secret = body["manual_entry_key"]
    assert body["qr_code_base64"]
    assert client.post("/api/auth/2fa/verify", json={"code": pyotp.TOTP(secret).now()}, headers=headers).json() == {
        "enabled": True
    }
    return secret


def _forget_used_codes() -> None:
    # Each code works once; tests that need a second code in the same 30 s window reset this.
    security.totp_manager._last_used_counter = -1


def test_enrolling_returns_a_qr_and_a_manual_key() -> None:
    client, headers = _signed_in_client()
    secret = _enable(client, headers)
    assert len(secret) >= 16
    assert client.get("/api/auth/2fa/status").json() == {"enabled": True}


def test_setup_and_disable_need_a_session() -> None:
    client = TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 50000))
    assert client.post("/api/auth/2fa/setup", json={}).status_code == 401
    assert client.post("/api/auth/2fa/disable", json={"code": "123456"}).status_code == 401


def test_re_enrolling_requires_a_current_code() -> None:
    client, headers = _signed_in_client()
    secret = _enable(client, headers)
    _forget_used_codes()

    assert client.post("/api/auth/2fa/setup", json={}, headers=headers).status_code == 400
    assert client.post("/api/auth/2fa/setup", headers=headers).status_code == 400
    assert client.post("/api/auth/2fa/setup", json={"code": "000000"}, headers=headers).status_code == 400
    state = json.loads(security.totp_manager._secret_path.read_text())
    assert "pending_secret" not in state  # nothing was started without the code

    response = client.post("/api/auth/2fa/setup", json={"code": pyotp.TOTP(secret).now()}, headers=headers)
    assert response.status_code == 200
    new_secret = response.json()["manual_entry_key"]
    assert new_secret != secret
    # The old factor stays active until the new one is confirmed.
    assert security.totp_manager.is_enabled
    _forget_used_codes()
    assert client.post("/api/auth/2fa/verify", json={"code": pyotp.TOTP(new_secret).now()}, headers=headers).status_code == 200
    assert json.loads(security.totp_manager._secret_path.read_text())["secret"] == new_secret


def test_turning_off_requires_a_current_code() -> None:
    client, headers = _signed_in_client()
    secret = _enable(client, headers)
    _forget_used_codes()

    assert client.post("/api/auth/2fa/disable", json={}, headers=headers).status_code == 400
    assert client.post("/api/auth/2fa/disable", json={"code": "000000"}, headers=headers).status_code == 400
    assert security.totp_manager.is_enabled

    response = client.post("/api/auth/2fa/disable", json={"code": pyotp.TOTP(secret).now()}, headers=headers)
    assert response.json() == {"enabled": False}
    assert not security.totp_manager.is_enabled
    assert not security.totp_manager._secret_path.exists()


def test_code_used_to_turn_off_or_change_cannot_be_reused() -> None:
    client, headers = _signed_in_client()
    secret = _enable(client, headers)
    _forget_used_codes()
    code = pyotp.TOTP(secret).now()
    assert client.post("/api/auth/2fa/setup", json={"code": code}, headers=headers).status_code == 200
    assert client.post("/api/auth/2fa/disable", json={"code": code}, headers=headers).status_code == 400


def test_setup_confirmation_code_cannot_be_replayed_to_sign_in() -> None:
    client, headers = _signed_in_client()
    secret = security.totp_manager.begin_setup()
    code = pyotp.TOTP(secret).now()
    assert security.totp_manager.verify_setup_code(code)
    assert security.totp_manager.verify_login_code(code) is False


def test_wrong_current_codes_lock_out_2fa_changes() -> None:
    client, headers = _signed_in_client()
    _enable(client, headers)
    statuses = [
        client.post("/api/auth/2fa/disable", json={"code": "000000"}, headers=headers).status_code for _ in range(5)
    ]
    assert statuses[:4] == [400] * 4 and statuses[4] == 429
    assert security.totp_manager.is_enabled


def test_turning_off_when_never_enabled_only_drops_a_pending_setup() -> None:
    client, headers = _signed_in_client()
    assert client.post("/api/auth/2fa/setup", json={}, headers=headers).status_code == 200
    assert client.post("/api/auth/2fa/disable", json={}, headers=headers).json() == {"enabled": False}
    assert not security.totp_manager._secret_path.exists()


def test_login_page_asks_for_the_code_when_2fa_is_on() -> None:
    client, headers = _signed_in_client()
    secret = _enable(client, headers)
    anonymous = TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 50001))
    page = anonymous.get("/").text
    assert 'id="totp-code"' in page and 'name="totp_code"' in page
    assert anonymous.post("/api/auth/login", json={"pin": PIN}).status_code == 401
    _forget_used_codes()
    response = anonymous.post("/api/auth/login", json={"pin": PIN, "totp_code": pyotp.TOTP(secret).now()})
    assert response.status_code == 200


def test_settings_page_shows_the_two_factor_section() -> None:
    client, headers = _signed_in_client()
    page = client.get("/administration").text
    assert "Verificación en dos pasos" in page
    assert 'data-enabled="false"' in page
    assert "/static/js/admin-two-factor.js" in page
    _enable(client, headers)
    assert 'data-enabled="true"' in client.get("/administration").text
