"""Ranks created in the panel live on the server, and "Subir/Bajar de rango" work without a LuckPerms track."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.luckperms import LuckPermsCustomRank, LuckPermsPanelConfig
from app.services import luckperms_service as module
from app.services.luckperms_service import LuckPermsService


@pytest.fixture
def service(tmp_path: Path, monkeypatch) -> LuckPermsService:
    configured = Settings(project_root=tmp_path)
    configured.panel_directory.mkdir(parents=True, exist_ok=True)
    configured.mods_directory.mkdir(parents=True)
    # LuckPerms detected from its jar: on, with no local file yet.
    (configured.mods_directory / "LuckPerms-NeoForge-5.4.jar").write_bytes(b"")
    monkeypatch.setattr("app.core.config.settings", configured)
    return LuckPermsService()


def test_created_ranks_are_kept_on_the_server_for_every_browser(service: LuckPermsService) -> None:
    rank = LuckPermsCustomRank(id="guardia", name="Guardia", weight=60, tag="&9[Guardia]")
    availability = service.save_custom_rank(rank)
    assert availability.enabled
    assert [r.id for r in availability.custom_ranks] == ["guardia"]
    # The built-in ranks are still there next to it.
    assert any(r["id"] == "vip" for r in availability.primary_ranks)

    # A second panel or browser reads the same list from the server.
    assert [r.id for r in LuckPermsService().get_configuration().custom_ranks] == ["guardia"]

    # Turning ranks on again does not forget them.
    service.save_configuration(LuckPermsPanelConfig(enabled=True))
    assert [r.id for r in service.get_configuration().custom_ranks] == ["guardia"]

    assert service.delete_custom_rank("guardia").custom_ranks == []


def test_rank_ids_must_be_safe_luckperms_group_names() -> None:
    with pytest.raises(ValidationError):
        LuckPermsCustomRank(id="vip owner", name="x")
    with pytest.raises(ValidationError):
        LuckPermsCustomRank(id="vip;op", name="x")


class FakeServer:
    """Answers "/lp user X info" with a Primary Group line in the console history."""

    def __init__(self, primary: str | None) -> None:
        self.is_running = True
        self.primary = primary
        self.commands: list[str] = []
        self.history: list[dict] = []

    async def send_command(self, command: str) -> None:
        self.commands.append(command)
        if command.endswith(" info") and self.primary is not None:
            self.history.append({"timestamp": datetime.now(UTC).isoformat(), "message": f"[LP] - Primary Group: §a{self.primary}"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current", "direction", "expected"),
    [("vip", "up", "mod"), ("vip", "down", "default"), ("admin", "up", "owner"), ("default", "initial", "default")],
)
async def test_rank_steps_follow_the_ranks_by_priority(service, monkeypatch, current, direction, expected) -> None:
    server = FakeServer(current)
    monkeypatch.setattr(module, "server_manager", server)
    result = await service.change_primary_rank("Steve", direction)
    assert result["success"], result
    assert server.commands[-1] == f"/lp user Steve parent set {expected}"
    assert not any("promote" in command or "jerarquia" in command for command in server.commands)


@pytest.mark.asyncio
async def test_created_ranks_take_their_place_in_the_ladder(service, monkeypatch) -> None:
    service.save_custom_rank(LuckPermsCustomRank(id="guardia", name="Guardia", weight=60))
    server = FakeServer("vip")
    monkeypatch.setattr(module, "server_manager", server)
    result = await service.change_primary_rank("Steve", "up")
    assert server.commands[-1] == "/lp user Steve parent set guardia"
    assert "Guardia" in result["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current", "direction", "words"),
    [("owner", "up", "el más alto"), ("default", "down", "el más bajo"), ("piratas", "up", "no está en tu lista"), (None, "up", "Ya entró")],
)
async def test_rank_steps_explain_what_they_cannot_do(service, monkeypatch, current, direction, words) -> None:
    server = FakeServer(current)
    monkeypatch.setattr(module, "server_manager", server)
    monkeypatch.setattr(module.asyncio, "sleep", _no_wait)
    loop_time = iter(range(0, 100, 5))
    monkeypatch.setattr(module.asyncio.get_running_loop(), "time", lambda: next(loop_time))
    result = await service.change_primary_rank("Steve", direction)
    assert not result["success"]
    assert words in result["message"]
    assert not any("parent set" in command for command in server.commands)


async def _no_wait(_seconds: float) -> None:
    return None
