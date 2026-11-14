"""Legacy Forge (Java 8) gets a launcher that inlines the JVM args, not @user_jvm_args.txt."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.services.installer_service import InstallerService
from tests.test_server_settings_file import settings_for


def _installer(configured: Settings) -> InstallerService:
    return InstallerService(configured)


def test_legacy_forge_launcher_inlines_jvm_args(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    root = configured.server_directory
    assert root is not None
    # Legacy Forge leaves a forge-*.jar in the root and no run scripts of its own.
    (root / "forge-1.12.2-14.23.5.2859.jar").write_bytes(b"x")

    _installer(configured)._write_safe_server_files("forge")

    bat = (root / "run.bat").read_text(encoding="utf-8")
    shell = (root / "run.sh").read_text(encoding="utf-8")
    # Java 8 cannot read the @argfile syntax, so it must not appear.
    assert "@user_jvm_args.txt" not in bat
    assert "@user_jvm_args.txt" not in shell
    # The RAM still comes from user_jvm_args.txt, read and passed inline.
    assert "user_jvm_args.txt" in bat
    assert "forge-1.12.2-14.23.5.2859.jar" in bat


def test_modern_forge_keeps_its_own_scripts(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    root = configured.server_directory
    assert root is not None
    # Modern Forge generates its own run.bat; the panel must not overwrite it.
    (root / "run.bat").write_text("@echo off\r\nforge-generated\r\n", encoding="utf-8", newline="")

    _installer(configured)._write_safe_server_files("forge")

    assert "forge-generated" in (root / "run.bat").read_text(encoding="utf-8")
