"""Regression tests for hashed storage of the administrator password."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.core import passwords, security
from app.core.config import Settings, settings
from app.core.passwords import hash_password, is_password_hash, verify_password
from app.core.rate_limit import limiter
from reset_admin_password import reset_password

LEGACY_PIN = "legacy-plain-password-42"


@pytest.fixture(autouse=True)
def _no_env_password(monkeypatch):
    monkeypatch.delenv("MINECRAFT_ADMIN_PIN", raising=False)


def _secrets_file(root: Path) -> Path:
    return root / "web_panel" / ".panel_secrets.json"


def _read(root: Path) -> dict[str, object]:
    return json.loads(_secrets_file(root).read_text(encoding="utf-8"))


def _write(root: Path, values: dict[str, object]) -> None:
    target = _secrets_file(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(values), encoding="utf-8")


def test_hash_uses_scrypt_with_a_random_salt_and_verifies() -> None:
    first = hash_password("correct-horse-battery-staple")
    second = hash_password("correct-horse-battery-staple")
    assert first != second  # per-password salt
    assert first.startswith("scrypt$15$8$1$")
    assert "correct-horse" not in first
    assert verify_password("correct-horse-battery-staple", first)
    assert verify_password("correct-horse-battery-staple", second)


def test_wrong_password_and_malformed_hashes_are_rejected() -> None:
    stored = hash_password("correct-horse-battery-staple", log2_n=10)
    assert not verify_password("correct-horse-battery-stapl", stored)
    assert not verify_password("", stored)
    assert not verify_password("contraseña-ñandú-\ud800", stored)
    assert not verify_password("correct-horse-battery-staple", "correct-horse-battery-staple")
    assert not is_password_hash("correct-horse-battery-staple")
    # Absurd cost parameters from a tampered file are refused instead of computed.
    _, _, r, p, salt, key = stored.split("$")
    assert not verify_password("correct-horse-battery-staple", f"scrypt$30${r}${p}${salt}${key}")


def test_verification_uses_a_constant_time_compare(monkeypatch) -> None:
    calls: list[tuple[bytes, bytes]] = []
    real_compare = passwords.secrets.compare_digest

    def spy(left, right):
        calls.append((left, right))
        return real_compare(left, right)

    monkeypatch.setattr(passwords.secrets, "compare_digest", spy)
    stored = hash_password("correct-horse-battery-staple", log2_n=10)
    assert verify_password("correct-horse-battery-staple", stored)
    assert not verify_password("wrong-password-123456", stored)
    assert len(calls) == 2
    assert all(isinstance(left, bytes) and len(left) == len(right) == 32 for left, right in calls)


def test_first_start_stores_only_a_hash_and_keeps_the_password_in_memory(tmp_path: Path) -> None:
    config = Settings(project_root=tmp_path)
    generated = config.initial_admin_password
    assert generated and config.admin_pin_generated_this_start
    stored = _read(tmp_path)
    assert generated not in _secrets_file(tmp_path).read_text(encoding="utf-8")
    assert "admin_pin" not in stored
    assert stored["admin_password_unclaimed"] is True
    assert verify_password(generated, str(stored["admin_password_hash"]))
    assert config.admin_password_hash == stored["admin_password_hash"]


def test_restart_before_first_login_shows_a_new_password(tmp_path: Path) -> None:
    first = Settings(project_root=tmp_path).initial_admin_password
    restarted = Settings(project_root=tmp_path)
    second = restarted.initial_admin_password
    assert first and second and first != second
    assert verify_password(second, str(_read(tmp_path)["admin_password_hash"]))
    assert not verify_password(first, str(_read(tmp_path)["admin_password_hash"]))


def test_first_login_forgets_the_password_and_restart_keeps_the_hash(tmp_path: Path) -> None:
    config = Settings(project_root=tmp_path)
    generated = config.initial_admin_password
    session_secret = _read(tmp_path)["session_secret"]
    config.mark_admin_password_claimed()
    assert config.initial_admin_password is None
    assert "admin_password_unclaimed" not in _read(tmp_path)

    restarted = Settings(project_root=tmp_path)
    assert restarted.initial_admin_password is None
    assert not restarted.admin_pin_generated_this_start
    assert verify_password(generated, str(restarted.admin_password_hash))
    assert _read(tmp_path)["session_secret"] == session_secret


def test_plain_text_password_from_older_versions_is_migrated(tmp_path: Path) -> None:
    session_secret = "s" * 48
    _write(tmp_path, {"admin_pin": LEGACY_PIN, "session_secret": session_secret, "other": "kept"})
    config = Settings(project_root=tmp_path)

    stored = _read(tmp_path)
    assert "admin_pin" not in stored
    assert LEGACY_PIN not in _secrets_file(tmp_path).read_text(encoding="utf-8")
    assert stored["session_secret"] == session_secret  # nobody is signed out by the upgrade
    assert stored["other"] == "kept"
    # Same password still works, and no first-run password is shown.
    assert verify_password(LEGACY_PIN, str(stored["admin_password_hash"]))
    assert verify_password(LEGACY_PIN, str(config.admin_password_hash))
    assert config.initial_admin_password is None


def test_environment_password_is_hashed_in_memory_and_never_written(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MINECRAFT_ADMIN_PIN", "environment-password-99")
    config = Settings(project_root=tmp_path)
    assert config.admin_pin is None  # the plain value is not kept around
    assert verify_password("environment-password-99", str(config.admin_password_hash))
    assert not verify_password("environment-password-98", str(config.admin_password_hash))
    assert config.initial_admin_password is None
    text = _secrets_file(tmp_path).read_text(encoding="utf-8")
    assert "environment-password-99" not in text
    assert "admin_password_hash" not in json.loads(text)


def test_reset_tool_prints_a_generated_password_once_and_stores_only_its_hash(tmp_path: Path) -> None:
    target = tmp_path / ".panel_secrets.json"
    target.write_text(json.dumps({"admin_pin": LEGACY_PIN, "session_secret": "s" * 48, "admin_password_unclaimed": True}))
    printed: list[str] = []
    reset_password(target, prompt=lambda _message: "", output=printed.append)

    stored = json.loads(target.read_text(encoding="utf-8"))
    assert set(stored) == {"admin_password_hash", "session_secret"}
    assert stored["session_secret"] != "s" * 48  # open sessions are signed out
    shown = [line.strip() for line in printed if line.strip() and verify_password(line.strip(), stored["admin_password_hash"])]
    assert len(shown) == 1
    assert shown[0] not in target.read_text(encoding="utf-8")
    assert not verify_password(LEGACY_PIN, stored["admin_password_hash"])


def test_reset_tool_accepts_a_chosen_password_without_printing_it(tmp_path: Path) -> None:
    target = tmp_path / ".panel_secrets.json"
    answers = iter(["my-chosen-password-77", "my-chosen-password-77"])
    printed: list[str] = []
    reset_password(target, prompt=lambda _message: next(answers), output=printed.append)
    stored = json.loads(target.read_text(encoding="utf-8"))
    assert verify_password("my-chosen-password-77", stored["admin_password_hash"])
    assert not any("my-chosen-password-77" in line for line in printed)
    assert "my-chosen-password-77" not in target.read_text(encoding="utf-8")


def test_reset_tool_leaves_everything_untouched_when_confirmation_differs(tmp_path: Path) -> None:
    target = tmp_path / ".panel_secrets.json"
    original = json.dumps({"admin_password_hash": hash_password(LEGACY_PIN, log2_n=10), "session_secret": "s" * 48})
    target.write_text(original)
    answers = iter(["my-chosen-password-77", "my-chosen-password-78"])
    with pytest.raises(SystemExit):
        reset_password(target, prompt=lambda _message: next(answers), output=lambda _line: None)
    assert target.read_text() == original


def test_login_checks_the_hash_and_claims_the_first_run_password(monkeypatch, tmp_path: Path) -> None:
    from main import app

    target = tmp_path / ".panel_secrets.json"
    target.write_text(json.dumps({"admin_password_hash": "x", "admin_password_unclaimed": True, "session_secret": "s" * 48}))
    monkeypatch.setattr(settings, "local_secrets_path", target)
    monkeypatch.setattr(settings, "_admin_password_hash", hash_password(LEGACY_PIN, log2_n=10))
    monkeypatch.setattr(settings, "_initial_admin_password", LEGACY_PIN)
    monkeypatch.setattr(settings, "_admin_pin_generated_this_start", True)
    monkeypatch.setattr(security.totp_manager, "_secret_path", tmp_path / ".totp_secret")
    security.login_attempt_tracker._attempts.clear()
    limiter.reset()

    client = TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 50000))
    assert LEGACY_PIN in client.get("/").text
    assert client.post("/api/auth/login", json={"pin": "not-the-password-1"}).status_code == 401
    assert settings.initial_admin_password == LEGACY_PIN  # a failed attempt changes nothing
    assert client.post("/api/auth/login", json={"pin": LEGACY_PIN}).status_code == 200
    assert settings.initial_admin_password is None
    assert "admin_password_unclaimed" not in json.loads(target.read_text())
    fresh_browser = TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 50001))
    assert LEGACY_PIN not in fresh_browser.get("/").text
    security.login_attempt_tracker._attempts.clear()
