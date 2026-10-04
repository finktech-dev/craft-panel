from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.schemas.onboarding import InstallServerRequest
from app.services.installer_service import InstallerConflictError, InstallerService, InstallerValidationError


class StoppedServer:
    is_running = False


@pytest.mark.asyncio
async def test_installer_requires_explicit_eula_acceptance(tmp_path):
    service = InstallerService(configured_settings=Settings(project_root=tmp_path), server=StoppedServer())

    with pytest.raises(InstallerValidationError, match="EULA"):
        await service.install_server("vanilla", "1.21.1", accept_eula=False)


def test_installer_never_overwrites_an_existing_runtime(tmp_path):
    configured = Settings(project_root=tmp_path)
    assert configured.server_directory is not None
    configured.server_directory.mkdir(parents=True)
    (configured.server_directory / "server.jar").write_bytes(b"runtime")
    service = InstallerService(configured_settings=configured, server=StoppedServer())

    with pytest.raises(InstallerConflictError, match="already exists"):
        service._assert_runtime_is_not_already_installed()
def test_installer_allows_a_stale_launch_script_without_a_runtime(tmp_path):
    configured = Settings(project_root=tmp_path)
    assert configured.server_directory is not None
    configured.server_directory.mkdir(parents=True)
    (configured.server_directory / "run.bat").write_text("stale launcher", encoding="utf-8")
    service = InstallerService(configured_settings=configured, server=StoppedServer())

    service._assert_runtime_is_not_already_installed()


def test_installer_generates_cross_platform_scripts_without_replacing_properties(tmp_path):
    configured = Settings(project_root=tmp_path)
    assert configured.server_directory is not None
    configured.server_directory.mkdir(parents=True)
    properties = configured.server_directory / "server.properties"
    properties.write_text("motd=Keep mine\n", encoding="utf-8")
    service = InstallerService(configured_settings=configured, server=StoppedServer())

    service._write_safe_server_files("vanilla")

    assert properties.read_text(encoding="utf-8") == "motd=Keep mine\n"
    assert (configured.server_directory / "eula.txt").read_text(encoding="utf-8") == "eula=true\n"
    assert "server.jar" in (configured.server_directory / "run.bat").read_text(encoding="utf-8")
    assert "server.jar" in (configured.server_directory / "run.sh").read_text(encoding="utf-8")

def test_onboarding_template_uses_guided_install_and_connection_actions():
    from pathlib import Path

    source = (Path(__file__).parent.parent / "static" / "js" / "onboarding.js").read_text(encoding="utf-8")
    assert "/api/onboarding/status" in source
    assert "/api/onboarding/install" in source
    assert "/api/tunnel/setup" in source
    assert "waitForPublicAddress" in source
    assert "/api/tunnel/status" in source


def test_first_login_shows_and_copies_the_generated_pin():
    from pathlib import Path

    source = (Path(__file__).parent.parent / "templates" / "login.html").read_text(encoding="utf-8")
    assert "initial_admin_pin" in source
    assert "initial-admin-pin" in source
    assert "copy-initial-pin" in source

def test_onboarding_import_is_a_safe_local_detection_flow():
    from pathlib import Path

    panel_root = Path(__file__).parent.parent
    template = (panel_root / "templates" / "onboarding.html").read_text(encoding="utf-8")
    source = (panel_root / "static" / "js" / "onboarding.js").read_text(encoding="utf-8")
    assert 'value="import"' in template
    assert "check-imported-server" in template
    assert "#check-imported-server" in source
    assert "/api/onboarding/install" in source


def test_install_request_rejects_import_as_an_install_action():
    with pytest.raises(ValueError):
        InstallServerRequest(flavor="import", minecraft_version="1.21.1", accept_eula=True)


def test_neoforge_scripts_are_preserved(tmp_path):
    configured = Settings(project_root=tmp_path)
    assert configured.server_directory is not None
    configured.server_directory.mkdir(parents=True)
    launch_script = configured.server_directory / "run.bat"
    launch_script.write_text("keep this script", encoding="utf-8")
    service = InstallerService(configured_settings=configured, server=StoppedServer())

    service._write_safe_server_files("neoforge")

    assert launch_script.read_text(encoding="utf-8") == "keep this script"

def test_server_start_command_is_native_to_the_host(monkeypatch, tmp_path):
    configured = Settings(project_root=tmp_path)
    assert configured.server_directory is not None
    configured.server_directory.mkdir(parents=True)

    monkeypatch.setattr("app.core.config.sys.platform", "win32")
    (configured.server_directory / "run.bat").write_text("@echo off\n", encoding="utf-8")
    assert configured.server_start_command == ("cmd.exe", "/d", "/s", "/c", "call run.bat nogui")

    monkeypatch.setattr("app.core.config.sys.platform", "linux")
    (configured.server_directory / "run.sh").write_text("#!/usr/bin/env sh\n", encoding="utf-8")
    assert configured.server_start_command == ("sh", "./run.sh", "nogui")


class FailingAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, *args, **kwargs):
        raise httpx.ConnectError("offline")


@pytest.mark.asyncio
async def test_vanilla_manifest_network_error_is_reported_as_installer_error(monkeypatch, tmp_path):
    from app.services.installer_service import InstallerServiceError

    monkeypatch.setattr("app.services.installer_service.httpx.AsyncClient", FailingAsyncClient)
    service = InstallerService(configured_settings=Settings(project_root=tmp_path), server=StoppedServer())

    with pytest.raises(InstallerServiceError, match="official server manifest"):
        await service._install_vanilla("1.21.1")


@pytest.mark.asyncio
async def test_fabric_manifest_network_error_is_reported_as_installer_error(monkeypatch, tmp_path):
    from app.services.installer_service import InstallerServiceError

    monkeypatch.setattr("app.services.installer_service.httpx.AsyncClient", FailingAsyncClient)
    service = InstallerService(configured_settings=Settings(project_root=tmp_path), server=StoppedServer())

    with pytest.raises(InstallerServiceError, match="Fabric installer manifest"):
        await service._install_fabric("1.21.1")
