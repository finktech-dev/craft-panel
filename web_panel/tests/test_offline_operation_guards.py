"""Regression coverage for operations that must never mutate files while Java is live."""

from __future__ import annotations

import pytest

from app.schemas.worlds import WorldCreateRequest
from app.services.backup_service import BackupConflictError, BackupService
from app.services.config_service import ConfigConflictError, ConfigService
from app.services.installer_service import InstallerConflictError, InstallerService
from app.services.mod_service import ModConflictError, ModService
from app.services.server_properties_service import ServerPropertiesService
from app.services.world_service import WorldService
from app.services.runtime_guard import ServerActiveError


class RunningServer:
    is_running = True


@pytest.mark.asyncio
async def test_mod_mutations_are_rejected_before_any_file_lookup():
    with pytest.raises(ModConflictError, match="servidor está encendido"):
        await ModService(manager=RunningServer()).delete_mod("example.jar")


@pytest.mark.asyncio
async def test_config_save_is_rejected_before_writing():
    with pytest.raises(ConfigConflictError, match="servidor está encendido"):
        await ConfigService(manager=RunningServer()).save("example.toml", "enabled = true")


@pytest.mark.asyncio
async def test_world_changes_and_server_properties_require_a_stopped_server():
    with pytest.raises(ServerActiveError, match="servidor está encendido"):
        await WorldService(manager=RunningServer()).create_world(WorldCreateRequest(world_name="nuevo_mundo"))
    with pytest.raises(ServerActiveError, match="servidor está encendido"):
        await ServerPropertiesService(manager=RunningServer()).update_properties({"motd": "Cambio"})


@pytest.mark.asyncio
async def test_restore_does_not_stop_or_replace_a_live_world():
    service = BackupService(manager=RunningServer())
    with pytest.raises(BackupConflictError, match="servidor está encendido"):
        await service.restore_backup("backup.zip")


@pytest.mark.asyncio
async def test_runtime_installer_is_rejected_while_server_is_running():
    with pytest.raises(InstallerConflictError, match="servidor está encendido"):
        await InstallerService(server=RunningServer()).install_neoforge()
