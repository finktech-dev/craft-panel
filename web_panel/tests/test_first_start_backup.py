"""Regression coverage for the first safe backup after a new world is ready."""

from __future__ import annotations

import pytest

from app.api import endpoints_server


class ReadyServer:
    async def wait_until_ready(self) -> None:
        return None


class EmptyBackups:
    def __init__(self) -> None:
        self.created = 0

    async def list_backups(self):
        return []

    async def create_backup(self) -> None:
        self.created += 1


class ExistingBackups(EmptyBackups):
    async def list_backups(self):
        return [object()]


@pytest.mark.asyncio
async def test_first_backup_is_created_only_after_world_ready(monkeypatch) -> None:
    backups = EmptyBackups()
    monkeypatch.setattr(endpoints_server, "server_manager", ReadyServer())
    monkeypatch.setattr(endpoints_server, "backup_service", backups)

    await endpoints_server._create_first_backup_after_ready()

    assert backups.created == 1


@pytest.mark.asyncio
async def test_first_backup_does_not_duplicate_existing_backups(monkeypatch) -> None:
    backups = ExistingBackups()
    monkeypatch.setattr(endpoints_server, "server_manager", ReadyServer())
    monkeypatch.setattr(endpoints_server, "backup_service", backups)

    await endpoints_server._create_first_backup_after_ready()

    assert backups.created == 0