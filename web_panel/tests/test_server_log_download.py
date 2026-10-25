"""Downloading the server log to ask for help: whole file, addresses and the Windows user hidden."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import endpoints_server


def _use_log(monkeypatch, path: Path) -> None:
    monkeypatch.setattr(endpoints_server, "settings", SimpleNamespace(server_log_file=path))


@pytest.mark.asyncio
async def test_download_hides_player_addresses_and_the_user_folder(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "latest.log"
    log.write_text(
        "[12:00:00] [Server thread/INFO]: Steve[/203.0.113.7:51234] logged in with entity id 1\n"
        "[12:00:01] [main/INFO]: Loading C:\\Users\\Juana\\servidor\\mods\n",
        encoding="utf-8",
    )
    _use_log(monkeypatch, log)

    response = await endpoints_server.download_server_log()
    text = response.body.decode("utf-8")

    assert "203.0.113.7" not in text and "Steve[/<ip>]" in text
    assert "Juana" not in text
    assert "attachment" in response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_a_huge_log_keeps_its_newest_lines(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "latest.log"
    log.write_text("vieja\n" * 50 + "la última línea\n", encoding="utf-8")
    _use_log(monkeypatch, log)
    monkeypatch.setattr(endpoints_server, "LOG_DOWNLOAD_MAX_BYTES", 100)

    text = (await endpoints_server.download_server_log()).body.decode("utf-8")

    assert text.startswith("# (Registro recortado")
    assert text.rstrip().endswith("la última línea")


@pytest.mark.asyncio
async def test_no_log_yet_explains_what_to_do(tmp_path: Path, monkeypatch) -> None:
    _use_log(monkeypatch, tmp_path / "logs" / "latest.log")
    with pytest.raises(HTTPException) as raised:
        await endpoints_server.download_server_log()
    assert raised.value.status_code == 404
