"""Status answers shown in the browser never carry host paths or the Windows user name."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.onboarding_service import OnboardingService
from app.services.playit_host import PlayitHostStatus
from app.services.playit_service import PlayitService
from app.services.runtime_discovery import RuntimeDiscoveryService

FAKE_USER = "PlayerOne"
WINDOWS_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:(\\\\|\\|/)")  # a drive letter, not "https:/"


def _assert_clean(body: str, *private: str) -> None:
    assert FAKE_USER not in body
    assert not WINDOWS_PATH.search(body), body
    for value in private:
        assert value not in body and value.replace("\\", "\\\\") not in body


class NoCatalog:
    async def list_versions(self, _flavor):
        from app.services.version_catalog_service import VersionCatalogError

        raise VersionCatalogError("offline")


@pytest.fixture
def host(tmp_path: Path):
    """A clone inside a user profile, with Java from the Minecraft Launcher and a server."""
    profile = tmp_path / "Users" / FAKE_USER
    configured = Settings(project_root=profile / "Desktop" / "craft-panel")
    assert configured.server_directory is not None
    configured.server_directory.mkdir(parents=True)
    (configured.server_directory / "run.bat").write_text("@echo off\r\n", encoding="utf-8")
    (configured.server_directory / "server.jar").write_bytes(b"")
    local = profile / "AppData" / "Local"
    java = (
        local / "Packages" / "Microsoft.4297127D64EC6_8wekyb3d8bbwe" / "LocalCache" / "Local" / "runtime"
        / "java-runtime-delta" / "windows-x64" / "java-runtime-delta" / "bin" / "java.exe"
    )
    java.parent.mkdir(parents=True)
    java.write_bytes(b"MZ")

    def runner(args, **_kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="",
            stderr='openjdk version "21.0.3" 2024-04-16 LTS\nOpenJDK Runtime Environment Microsoft-9388422 (build 21.0.3+9-LTS)\n',
        )

    discovery = RuntimeDiscoveryService(
        configured, system_name="Windows", environ={"LOCALAPPDATA": str(local), "USERNAME": FAKE_USER},
        which=lambda _name: None, command_runner=runner, registry=None,
    )
    return configured, discovery, str(profile)


def test_runtime_discovery_answer_has_no_paths(host) -> None:
    _configured, discovery, profile = host

    result = discovery.discover()

    assert result.java.state == "available" and result.minecraft.state == "detected"
    _assert_clean(result.model_dump_json(), profile)


@pytest.mark.parametrize("state", ["running", "stopped", "not_installed"])
def test_tunnel_status_has_no_paths(host, state: str) -> None:
    configured, _discovery, profile = host
    service = PlayitService(configured)
    service._host_status = PlayitHostStatus(state=state, service_installed=state != "not_installed", app_installed=state != "not_installed")
    service._host_checked_at = float("inf")

    _assert_clean(service.status().model_dump_json(), profile)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["running", "stopped", "not_installed"])
async def test_onboarding_status_has_no_paths(host, state: str) -> None:
    configured, discovery, profile = host
    tunnel = PlayitService(configured)
    tunnel._host_status = PlayitHostStatus(state=state, service_installed=state != "not_installed", app_installed=state != "not_installed")
    tunnel._host_checked_at = float("inf")
    service = OnboardingService(configured_settings=configured, discovery=discovery, tunnel=tunnel, catalog=NoCatalog())

    status = await service.status("1.21.1")

    _assert_clean(status.model_dump_json(), profile)
