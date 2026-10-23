"""Thresholds behind the dashboard safety center."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.external_server_service import ExternalServer
from app.services.safety_service import (
    SafetyService,
    _ago,
    access_item,
    backup_item,
    diagnostics_item,
    disk_item,
    summarize,
)

GIB = 1024**3


@pytest.mark.parametrize(
    ("properties", "public", "level"),
    [
        ({"online-mode": "true", "white-list": "true"}, True, "ok"),
        ({"online-mode": "false", "white-list": "true"}, True, "warn"),
        ({"online-mode": "true", "white-list": "false"}, False, "ok"),
        ({"online-mode": "false", "white-list": "false"}, True, "danger"),
        ({"online-mode": "true", "white-list": "false"}, True, "danger"),
        ({"online-mode": "false", "white-list": "false"}, False, "warn"),
    ],
)
def test_access_levels(properties, public, level) -> None:
    item = access_item(properties, whitelisted_players=3, public_tunnel=public)
    assert item.level == level
    assert item.action_href in {"/worlds#whitelist", "/worlds#props"}
    assert "PID" not in item.detail and "online-mode" not in item.detail


def test_disk_levels() -> None:
    assert disk_item(5 * GIB, 4 * GIB, 10 * GIB).level == "danger"
    assert disk_item(20 * GIB, 4 * GIB, 10 * GIB).level == "warn"
    assert disk_item(200 * GIB, 4 * GIB, 10 * GIB).level == "ok"
    assert disk_item(50 * GIB, None, 10 * GIB).level == "ok"


def test_backup_levels() -> None:
    assert backup_item(None, 6, world_exists=True).level == "danger"
    assert backup_item(None, 6, world_exists=False).level == "unknown"
    assert backup_item(2 * 3600, 6, world_exists=True).level == "ok"
    assert backup_item(30 * 3600, 6, world_exists=True).level == "warn"


def test_diagnostics_prefers_external_server_then_recent_crash() -> None:
    external = ExternalServer(pid=10, name="java.exe", reason="server_directory", port=25565)
    assert diagnostics_item(external, None).level == "warn"
    assert diagnostics_item(None, 3600).action_href == "/crashes"
    assert diagnostics_item(None, 30 * 86400).level == "ok"


def test_summary_takes_the_worst_level() -> None:
    items = [backup_item(3600, 6, True), access_item({"white-list": "false"}, 0, True)]
    summary = summarize(items)
    assert summary.level == "danger"
    assert summary.headline == "Hay algo importante para revisar"


def test_service_reads_real_files(tmp_path: Path) -> None:
    configured = Settings(project_root=tmp_path, backup_min_free_disk_gb=0)
    assert configured.server_directory is not None and configured.backups_directory is not None
    (configured.server_directory / "world").mkdir(parents=True)
    (configured.server_directory / "whitelist.json").write_text(json.dumps([{"name": "Alex"}]), encoding="utf-8")
    configured.backups_directory.mkdir(parents=True)
    (configured.backups_directory / "backup_1.zip").write_bytes(b"zip")

    summary = SafetyService(configured).summary(
        {"online-mode": "true", "white-list": "true", "level-name": "world"}, public_tunnel=True, own_pid=None
    )

    levels = {item.key: item.level for item in summary.items}
    assert levels["access"] == "ok"
    assert levels["backups"] == "ok"
    assert "1 amigo en la lista" in summary.items[0].detail


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(30, "hace 1 minuto"), (600, "hace 10 minutos"), (3600, "hace 1 hora"), (3 * 3600, "hace 3 horas"),
     (30 * 3600, "ayer"), (2 * 86400, "hace 2 días")],
)
def test_relative_times_read_naturally(seconds, expected) -> None:
    assert _ago(seconds) == expected
