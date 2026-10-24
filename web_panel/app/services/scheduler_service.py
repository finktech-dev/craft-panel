"""Simple persistent panel tasks, with no Windows scripts required.

``backup_interval`` and ``daily_restart`` from craftpanel.txt take priority
over the interval saved from Ajustes; the file is re-read every minute so
hand edits apply without restarting the panel.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import Settings, settings
from app.services.backup_service import backup_service
from app.services.server_settings_file import SettingsFileError, read_server_settings, server_settings_file

logger = logging.getLogger(__name__)

BACKUP_JOB_ID = "panel-backup"
DAILY_RESTART_JOB_ID = "daily-restart"
SETTINGS_SYNC_JOB_ID = "settings-file-sync"


def _local_timezone():
    """The PC's own time zone: a daily restart at 05:30 means 05:30 on this computer."""
    try:
        import tzlocal

        return tzlocal.get_localzone()
    except Exception:  # noqa: BLE001 - fall back to the current UTC offset
        from datetime import datetime

        return datetime.now().astimezone().tzinfo


class SchedulerService:
    def __init__(self, configured_settings: Settings = settings) -> None:
        self._settings = configured_settings
        self.scheduler = AsyncIOScheduler(timezone=_local_timezone())
        self._daily_restart_action: Callable[[], Awaitable[None]] | None = None
        self._applied: tuple[object, ...] | None = None

    @property
    def state_path(self) -> Path:
        assert self._settings.panel_directory is not None
        return self._settings.panel_directory / ".scheduled_tasks.json"

    def start(self) -> None:
        if self.scheduler.running:
            return
        self.scheduler.start()
        self.sync_with_settings_file()
        self.scheduler.add_job(
            backup_service.audit_and_purge_backups,
            "interval",
            hours=self._settings.backup_integrity_check_interval_hours,
            id="backup-integrity-audit",
            replace_existing=True,
            name="Verificación y purga segura de backups",
        )
        self.scheduler.add_job(
            self.sync_with_settings_file,
            "interval",
            minutes=1,
            id=SETTINGS_SYNC_JOB_ID,
            replace_existing=True,
            name="Leer craftpanel.txt",
        )

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def set_daily_restart_action(self, action: Callable[[], Awaitable[None]]) -> None:
        """The API layer provides the graceful-restart job; the scheduler only decides when."""
        self._daily_restart_action = action
        self._applied = None

    def backup_interval_seconds(self) -> int:
        from_file = read_server_settings(self._settings).value("backup_interval")
        if from_file:
            return int(from_file)
        return (self._load_backup_interval() or self._settings.auto_backup_interval_hours) * 3600

    def sync_with_settings_file(self) -> None:
        """Re-read craftpanel.txt and reschedule what it controls, only when something changed."""
        file_settings = read_server_settings(self._settings)
        daily = file_settings.value("daily_restart")
        wanted = (self.backup_interval_seconds(), daily, self._daily_restart_action is not None)
        if wanted == self._applied:
            return
        self._applied = wanted
        self._schedule_backup_seconds(wanted[0])
        if daily is not None and self._daily_restart_action is not None:
            hour, minute = daily
            self.scheduler.add_job(
                self._daily_restart_action,
                CronTrigger(hour=hour, minute=minute, timezone=self.scheduler.timezone),
                id=DAILY_RESTART_JOB_ID,
                replace_existing=True,
                name=f"Reinicio diario a las {hour:02d}:{minute:02d}",
            )
        elif self.scheduler.get_job(DAILY_RESTART_JOB_ID) is not None:
            self.scheduler.remove_job(DAILY_RESTART_JOB_ID)

    def jobs(self) -> list[dict[str, str | None]]:
        return [{"id": job.id, "name": job.name, "next_run": job.next_run_time.isoformat() if getattr(job, "next_run_time", None) else None} for job in self.scheduler.get_jobs()]

    def add_backup(self, hours: int) -> list[dict[str, str | None]]:
        """Interval chosen in Ajustes. When craftpanel.txt exists it is written there too, so both agree."""
        self._save_backup_interval(hours)
        if server_settings_file.load(self._settings).exists:
            try:
                server_settings_file.save_fields(self._settings, values={"backup_interval": f"{hours}h"})
            except SettingsFileError as error:
                logger.warning("Could not write backup_interval to craftpanel.txt: %s", error)
        self._applied = None
        self.sync_with_settings_file()
        return self.jobs()

    def _schedule_backup_seconds(self, seconds: int) -> None:
        hours = seconds / 3600
        label = f"{hours:g}h"
        self.scheduler.add_job(
            backup_service.create_scheduled_backup,
            "interval",
            seconds=seconds,
            id=BACKUP_JOB_ID,
            replace_existing=True,
            name=f"Backup cada {label}",
        )

    def _load_backup_interval(self) -> int | None:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8")).get("backup_interval_hours")
            return value if isinstance(value, int) and 1 <= value <= 168 else None
        except (OSError, json.JSONDecodeError):
            return None

    def _save_backup_interval(self, hours: int) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps({"backup_interval_hours": hours}, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, self.state_path)
        finally:
            if temporary.exists():
                temporary.unlink()


scheduler_service = SchedulerService()
