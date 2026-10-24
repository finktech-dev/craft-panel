"""Saving mod settings: no lost updates from quick toggles or edits made elsewhere."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.config_service import ConfigConflictError, ConfigService


class StoppedServer:
    is_running = False
    state = "STOPPED"


def _service(tmp_path: Path) -> tuple[ConfigService, Path]:
    configured = Settings(project_root=tmp_path)
    assert configured.config_directory is not None
    configured.config_directory.mkdir(parents=True)
    path = configured.config_directory / "example-common.toml"
    path.write_text("# keep me\n[general]\nalpha = false\nbeta = false\n", encoding="utf-8")
    return ConfigService(configured, StoppedServer()), path


@pytest.mark.asyncio
async def test_two_quick_switch_changes_both_survive(tmp_path: Path) -> None:
    service, path = _service(tmp_path)
    await asyncio.gather(
        service.save("example-common.toml", None, {"general.alpha": True}),
        service.save("example-common.toml", None, {"general.beta": True}),
    )
    text = path.read_text(encoding="utf-8")
    assert "alpha = true" in text and "beta = true" in text
    assert "# keep me" in text


@pytest.mark.asyncio
async def test_whole_file_save_refuses_when_the_file_changed_meanwhile(tmp_path: Path) -> None:
    service, path = _service(tmp_path)
    opened = await service.read("example-common.toml")
    # Someone edits it in Notepad after the panel opened it.
    path.write_text("[general]\nalpha = true\nbeta = true\n", encoding="utf-8")
    with pytest.raises(ConfigConflictError, match="cambió desde que lo abriste"):
        await service.save("example-common.toml", "[general]\nalpha = false\n", None, opened.fingerprint)
    assert path.read_text(encoding="utf-8") == "[general]\nalpha = true\nbeta = true\n"


@pytest.mark.asyncio
async def test_whole_file_save_works_from_the_current_version(tmp_path: Path) -> None:
    service, path = _service(tmp_path)
    opened = await service.read("example-common.toml")
    saved = await service.save("example-common.toml", "[general]\nalpha = true\n", None, opened.fingerprint)
    assert path.read_text(encoding="utf-8") == "[general]\nalpha = true\n"
    assert saved.fingerprint != opened.fingerprint
