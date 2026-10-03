"""Coverage for the read-only backup safety contract."""

from __future__ import annotations

import asyncio
import tempfile
import zipfile
from pathlib import Path

from app.core.config import Settings
from app.services.backup_service import BackupService


class RunningServer:
    is_running = True


def test_safety_overview_reports_integrity_provenance_and_live_restore_block() -> None:
    with tempfile.TemporaryDirectory() as directory:
        configured = Settings(project_root=Path(directory))
        assert configured.backups_directory is not None
        assert configured.server_directory is not None
        configured.backups_directory.mkdir(parents=True)
        with zipfile.ZipFile(configured.backups_directory / "panel.zip", "w") as archive:
            archive.writestr("world/level.dat", "safe")
        simplebackups = configured.server_directory / "simplebackups"
        simplebackups.mkdir(parents=True)
        (simplebackups / "broken.zip").write_bytes(b"not a zip")

        overview = asyncio.run(BackupService(configured, manager=RunningServer()).safety_overview())

    entries = {entry.filename: entry for entry in overview.backups}
    assert overview.total_backups == 2
    assert overview.verified_backups == 1
    assert overview.corrupted_backups == 1
    assert entries["panel.zip"].provenance == "panel"
    assert entries["panel.zip"].integrity == "verified"
    assert entries["panel.zip"].restore_ready is False
    assert entries["broken.zip"].provenance == "simplebackups"
    assert entries["broken.zip"].integrity == "corrupt"
