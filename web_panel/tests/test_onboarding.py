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
    assert configured.server_start_command == ("cmd.exe", "/d", "/s", "/c", "call .\\run.bat nogui")

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


class FakeCatalog:
    def __init__(self, neoforge: dict[str, str] | None = None) -> None:
        self.neoforge = neoforge or {}

    async def latest_neoforge_build(self, minecraft_version):
        from app.services.version_catalog_service import VersionCatalogValidationError

        if minecraft_version not in self.neoforge:
            raise VersionCatalogValidationError(f"NeoForge no tiene versiones para Minecraft {minecraft_version}.")
        return self.neoforge[minecraft_version]

    async def latest_fabric_loader(self, minecraft_version):
        return "0.20.1"

    async def latest_fabric_installer(self):
        return "1.1.2"


def _artifact_transport(monkeypatch, artifacts: dict[str, bytes], checksum_override: str | None = None):
    """Serve fake Maven artifacts (and their .sha1) through every httpx client the installer opens."""
    import hashlib

    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        if url.endswith(".sha1") and url[:-5] in artifacts:
            digest = checksum_override or hashlib.sha1(artifacts[url[:-5]]).hexdigest()
            return httpx.Response(200, text=f"{digest}\n")
        if url in artifacts:
            return httpx.Response(200, content=artifacts[url])
        return httpx.Response(404)

    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr("app.services.installer_service.httpx.AsyncClient", factory)
    return requested


@pytest.mark.asyncio
@pytest.mark.parametrize(("minecraft", "build"), [("1.21.1", "21.1.264"), ("1.20.4", "20.4.237"), ("26.1.2", "26.1.2.122")])
async def test_neoforge_installs_the_latest_stable_build_for_any_version(monkeypatch, tmp_path, minecraft, build):
    url = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{build}/neoforge-{build}-installer.jar"
    requested = _artifact_transport(monkeypatch, {url: b"installer-bytes"})
    configured = Settings(project_root=tmp_path)
    service = InstallerService(configured_settings=configured, server=StoppedServer(), catalog=FakeCatalog({minecraft: build}))
    java_calls: list[tuple[str, ...]] = []

    async def fake_java(*args):
        java_calls.append(args)

    monkeypatch.setattr(service, "_run_java", fake_java)
    await service._install_neoforge(minecraft)

    assert requested == [f"{url}.sha1", url]
    assert configured.neoforge_installer_path.read_bytes() == b"installer-bytes"
    assert java_calls and "--install-server" in java_calls[0]


@pytest.mark.asyncio
async def test_neoforge_override_is_used_when_it_targets_the_chosen_version(monkeypatch, tmp_path):
    url = "https://maven.neoforged.net/releases/net/neoforged/neoforge/21.1.200/neoforge-21.1.200-installer.jar"
    _artifact_transport(monkeypatch, {url: b"pinned"})
    configured = Settings(project_root=tmp_path, neoforge_version="21.1.200")
    service = InstallerService(configured_settings=configured, server=StoppedServer(), catalog=FakeCatalog())

    async def fake_java(*args):
        return None

    monkeypatch.setattr(service, "_run_java", fake_java)
    await service._install_neoforge("1.21.1")

    assert configured.neoforge_installer_path.read_bytes() == b"pinned"


@pytest.mark.asyncio
async def test_neoforge_without_builds_for_the_version_is_a_validation_error(tmp_path):
    service = InstallerService(configured_settings=Settings(project_root=tmp_path), server=StoppedServer(), catalog=FakeCatalog())

    with pytest.raises(InstallerValidationError, match="1.12.2"):
        await service._install_neoforge("1.12.2")


@pytest.mark.asyncio
async def test_neoforge_download_with_a_wrong_checksum_is_discarded(monkeypatch, tmp_path):
    from app.services.installer_service import InstallerServiceError

    url = "https://maven.neoforged.net/releases/net/neoforged/neoforge/21.1.264/neoforge-21.1.264-installer.jar"
    _artifact_transport(monkeypatch, {url: b"tampered"}, checksum_override="0" * 40)
    configured = Settings(project_root=tmp_path)
    service = InstallerService(configured_settings=configured, server=StoppedServer(), catalog=FakeCatalog({"1.21.1": "21.1.264"}))

    with pytest.raises(InstallerServiceError, match="checksum"):
        await service._install_neoforge("1.21.1")
    assert not configured.neoforge_installer_path.exists()


@pytest.mark.asyncio
async def test_fabric_installs_the_latest_stable_loader_for_the_chosen_version(monkeypatch, tmp_path):
    url = "https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.1.2/fabric-installer-1.1.2.jar"
    _artifact_transport(monkeypatch, {url: b"fabric-installer"})
    configured = Settings(project_root=tmp_path)
    service = InstallerService(configured_settings=configured, server=StoppedServer(), catalog=FakeCatalog())
    java_calls: list[tuple[str, ...]] = []

    async def fake_java(*args):
        java_calls.append(args)

    monkeypatch.setattr(service, "_run_java", fake_java)
    await service._install_fabric("26.3")

    args = java_calls[0]
    assert args[args.index("-mcversion") + 1] == "26.3"
    assert args[args.index("-loader") + 1] == "0.20.1"


@pytest.mark.asyncio
async def test_loader_install_checks_java_for_the_chosen_version_first(tmp_path):
    from app.schemas.runtime import JavaRuntimeStatus

    class OldJava:
        def java_status(self, minecraft_version):
            return JavaRuntimeStatus(
                state="unusable", major_version=21,
                message=f"Se encontró Java 21, pero Minecraft {minecraft_version} necesita Java 25 o superior.",
            )

    service = InstallerService(
        configured_settings=Settings(project_root=tmp_path), server=StoppedServer(), catalog=FakeCatalog(), discovery=OldJava()
    )

    with pytest.raises(InstallerValidationError, match="Java 25"):
        await service.install_server("neoforge", "26.1", accept_eula=True)


@pytest.mark.asyncio
async def test_installer_rejects_a_missing_minecraft_version(tmp_path):
    service = InstallerService(configured_settings=Settings(project_root=tmp_path), server=StoppedServer())

    with pytest.raises(InstallerValidationError, match="versión de Minecraft"):
        await service.install_neoforge()
