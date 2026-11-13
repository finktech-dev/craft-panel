"""Changing the version of a server that already exists keeps the user's data safe."""

import pytest

from app.core.config import Settings
from app.services.installer_service import (
    InstallerConflictError,
    InstallerService,
    InstallerServiceError,
    _StagedRuntime,
)


class StoppedServer:
    is_running = False


class RunningServer:
    is_running = True


def _make_fabric_server(root, loader="0.16.0"):
    """A minimal Fabric server plus the user data that must survive a version change."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "fabric-server-launch.jar").write_bytes(b"old-launch")
    libs = root / "libraries" / "net" / "fabricmc" / "fabric-loader" / loader
    libs.mkdir(parents=True)
    (libs / "fabric-loader.jar").write_bytes(b"old-loader")
    world = root / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"my-world")
    (root / "mods").mkdir()
    (root / "mods" / "cool-mod.jar").write_bytes(b"a-mod")
    (root / "config").mkdir()
    (root / "config" / "cool-mod.toml").write_text("keep=me", encoding="utf-8")
    (root / "server.properties").write_text("level-name=world\n", encoding="utf-8")
    (root / "user_jvm_args.txt").write_text("-Xmx8G\n", encoding="utf-8")


def _service(configured, server=None):
    return InstallerService(configured_settings=configured, server=server or StoppedServer())


def test_preflight_refuses_when_no_server_is_installed(tmp_path):
    configured = Settings(project_root=tmp_path)
    assert configured.server_directory is not None
    configured.server_directory.mkdir(parents=True)
    with pytest.raises(InstallerConflictError):
        _service(configured).change_version_preflight()


def test_preflight_refuses_while_the_server_runs(tmp_path):
    configured = Settings(project_root=tmp_path)
    assert configured.server_directory is not None
    _make_fabric_server(configured.server_directory)
    with pytest.raises(InstallerConflictError):
        _service(configured, server=RunningServer()).change_version_preflight()


def test_moving_the_runtime_aside_keeps_the_world_mods_and_config(tmp_path):
    configured = Settings(project_root=tmp_path)
    root = configured.server_directory
    assert root is not None
    _make_fabric_server(root)
    service = _service(configured)
    aside = root / ".runtime_old_test"

    service._move_runtime_aside(root, aside)

    # The runtime is gone from the server folder...
    assert not (root / "fabric-server-launch.jar").exists()
    assert not (root / "libraries").exists()
    # ...but every piece of user data stays exactly where it was.
    assert (root / "world" / "level.dat").read_bytes() == b"my-world"
    assert (root / "mods" / "cool-mod.jar").read_bytes() == b"a-mod"
    assert (root / "config" / "cool-mod.toml").read_text(encoding="utf-8") == "keep=me"
    assert (root / "server.properties").exists()
    assert (root / "user_jvm_args.txt").read_text(encoding="utf-8") == "-Xmx8G\n"
    # The old runtime is tucked away for a possible rollback.
    assert (aside / "fabric-server-launch.jar").read_bytes() == b"old-launch"


def test_restoring_the_runtime_brings_the_old_one_back(tmp_path):
    configured = Settings(project_root=tmp_path)
    root = configured.server_directory
    assert root is not None
    _make_fabric_server(root)
    service = _service(configured)
    aside = root / ".runtime_old_test"
    moved = service._move_runtime_aside(root, aside)

    # A failed install left a half-written new runtime behind.
    (root / "server.jar").write_bytes(b"partial-new")

    service._restore_runtime_aside(root, aside, moved)

    assert (root / "fabric-server-launch.jar").read_bytes() == b"old-launch"
    assert not (root / "server.jar").exists()  # the partial new runtime was dropped
    assert not aside.exists()
    assert (root / "world" / "level.dat").read_bytes() == b"my-world"


async def _run_change(service, **kwargs):
    return await service.change_version("1.21.4", **kwargs)


@pytest.mark.asyncio
async def test_change_version_replaces_runtime_and_keeps_the_world(tmp_path, monkeypatch):
    configured = Settings(project_root=tmp_path)
    root = configured.server_directory
    assert root is not None
    _make_fabric_server(root, loader="0.16.0")
    service = _service(configured)

    async def fake_java(_mc):
        return None

    async def fake_stage(_flavor, _mc):
        return _StagedRuntime(installer=tmp_path / "fake-installer.jar", loader="0.16.9")

    async def fake_apply(_flavor, _mc, _staged):
        new_libs = root / "libraries" / "net" / "fabricmc" / "fabric-loader" / "0.16.9"
        new_libs.mkdir(parents=True)
        (new_libs / "fabric-loader.jar").write_bytes(b"new-loader")
        (root / "fabric-server-launch.jar").write_bytes(b"new-launch")

    monkeypatch.setattr(service, "_assert_java_is_compatible", fake_java)
    monkeypatch.setattr(service, "_stage_runtime", fake_stage)
    monkeypatch.setattr(service, "_apply_runtime", fake_apply)

    await _run_change(service)

    assert (root / "fabric-server-launch.jar").read_bytes() == b"new-launch"
    assert (root / "libraries" / "net" / "fabricmc" / "fabric-loader" / "0.16.9").is_dir()
    assert not (root / "libraries" / "net" / "fabricmc" / "fabric-loader" / "0.16.0").exists()
    # User data untouched, and no leftover rollback folder.
    assert (root / "world" / "level.dat").read_bytes() == b"my-world"
    assert (root / "mods" / "cool-mod.jar").read_bytes() == b"a-mod"
    assert (root / "config" / "cool-mod.toml").exists()
    assert (root / "user_jvm_args.txt").read_text(encoding="utf-8") == "-Xmx8G\n"
    assert not any(root.glob(".runtime_old_*"))


@pytest.mark.asyncio
async def test_change_version_rolls_back_when_the_install_fails(tmp_path, monkeypatch):
    configured = Settings(project_root=tmp_path)
    root = configured.server_directory
    assert root is not None
    _make_fabric_server(root, loader="0.16.0")
    service = _service(configured)

    async def fake_java(_mc):
        return None

    async def fake_stage(_flavor, _mc):
        return _StagedRuntime(installer=tmp_path / "fake-installer.jar", loader="0.16.9")

    async def failing_apply(_flavor, _mc, _staged):
        raise InstallerServiceError("el instalador se cortó")

    monkeypatch.setattr(service, "_assert_java_is_compatible", fake_java)
    monkeypatch.setattr(service, "_stage_runtime", fake_stage)
    monkeypatch.setattr(service, "_apply_runtime", failing_apply)

    with pytest.raises(InstallerServiceError):
        await _run_change(service)

    # The old runtime and the world are back as if nothing happened.
    assert (root / "fabric-server-launch.jar").read_bytes() == b"old-launch"
    assert (root / "libraries" / "net" / "fabricmc" / "fabric-loader" / "0.16.0").is_dir()
    assert (root / "world" / "level.dat").read_bytes() == b"my-world"
    assert (root / "mods" / "cool-mod.jar").read_bytes() == b"a-mod"
    assert not any(root.glob(".runtime_old_*"))


@pytest.mark.asyncio
async def test_change_version_can_start_from_a_fresh_world(tmp_path, monkeypatch):
    configured = Settings(project_root=tmp_path)
    root = configured.server_directory
    assert root is not None
    _make_fabric_server(root, loader="0.16.0")
    service = _service(configured)

    async def fake_java(_mc):
        return None

    async def fake_stage(_flavor, _mc):
        return _StagedRuntime(installer=tmp_path / "fake-installer.jar", loader="0.16.9")

    async def fake_apply(_flavor, _mc, _staged):
        (root / "fabric-server-launch.jar").write_bytes(b"new-launch")
        new_libs = root / "libraries" / "net" / "fabricmc" / "fabric-loader" / "0.16.9"
        new_libs.mkdir(parents=True)
        (new_libs / "fabric-loader.jar").write_bytes(b"new-loader")

    monkeypatch.setattr(service, "_assert_java_is_compatible", fake_java)
    monkeypatch.setattr(service, "_stage_runtime", fake_stage)
    monkeypatch.setattr(service, "_apply_runtime", fake_apply)

    await _run_change(service, delete_world=True)

    assert not (root / "world").exists()  # started from scratch
    assert (root / "mods" / "cool-mod.jar").exists()  # mods are still kept
    assert (root / "fabric-server-launch.jar").read_bytes() == b"new-launch"
