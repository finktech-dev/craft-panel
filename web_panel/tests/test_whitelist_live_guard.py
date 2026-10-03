"""Live whitelist changes must be confirmed by Minecraft and never overwrite stale JSON."""

from __future__ import annotations

import pytest

from app.services.server_process import ServerProcessError
from app.services.whitelist_service import WhitelistService, WhitelistServiceError


class LiveManager:
    is_running = True

    def __init__(self, failure: bool = False) -> None:
        self.failure = failure
        self.commands: list[tuple[str, str]] = []

    async def send_command_and_wait_for_log(self, command: str, confirmation: str) -> None:
        self.commands.append((command, confirmation))
        if self.failure:
            raise ServerProcessError("no response")


@pytest.mark.asyncio
async def test_live_add_does_not_write_a_stale_whitelist_file(monkeypatch):
    manager = LiveManager()
    service = WhitelistService(manager=manager)
    monkeypatch.setattr(service, "_read_file", lambda: [])
    wrote = False

    def write_unexpectedly(_data):
        nonlocal wrote
        wrote = True

    monkeypatch.setattr(service, "_write_file", write_unexpectedly)
    result = await service.add_player("ExamplePlayer")

    assert result["success"] is True
    assert manager.commands == [("/whitelist add ExamplePlayer", "Added ExamplePlayer to the whitelist")]
    assert wrote is False


@pytest.mark.asyncio
async def test_live_remove_failure_never_reports_success_or_writes(monkeypatch):
    service = WhitelistService(manager=LiveManager(failure=True))
    monkeypatch.setattr(service, "_read_file", lambda: [{"name": "ExamplePlayer"}])
    monkeypatch.setattr(service, "_write_file", lambda _data: pytest.fail("must not write on live failure"))

    with pytest.raises(WhitelistServiceError, match="no confirmó"):
        await service.remove_player("ExamplePlayer")


@pytest.mark.asyncio
async def test_live_toggle_uses_confirmed_console_path_not_offline_file_write(monkeypatch):
    manager = LiveManager()
    service = WhitelistService(manager=manager)
    monkeypatch.setattr(
        "app.services.whitelist_service.server_properties_service.update_properties",
        lambda _updates: pytest.fail("live toggle must not use offline server.properties write"),
    )

    result = await service.toggle(True)

    assert result["success"] is True
    assert manager.commands == [("/whitelist on", "Whitelist is now turned on")]
