"""Tareas simples persistentes del panel, sin requerir scripts de Windows."""
from __future__ import annotations
import json
import os
import uuid
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.core.config import Settings, settings
from app.services.backup_service import backup_service

class SchedulerService:
    def __init__(self, configured_settings: Settings = settings) -> None:
        self._settings = configured_settings
        self.scheduler = AsyncIOScheduler(timezone="America/Argentina/Buenos_Aires")
    @property
    def state_path(self) -> Path:
        assert self._settings.panel_directory is not None
        return self._settings.panel_directory / ".scheduled_tasks.json"
    def start(self) -> None:
        if self.scheduler.running: return
        self.scheduler.start()
        hours = self._load_backup_interval() or self._settings.auto_backup_interval_hours
        self._schedule_backup(hours)
        self.scheduler.add_job(
            backup_service.audit_and_purge_backups,
            "interval",
            hours=self._settings.backup_integrity_check_interval_hours,
            id="backup-integrity-audit",
            replace_existing=True,
            name="Verificación y purga segura de backups",
        )
    def shutdown(self) -> None:
        if self.scheduler.running: self.scheduler.shutdown(wait=False)
    def jobs(self) -> list[dict[str, str | None]]:
        return [{"id": job.id, "name": job.name, "next_run": job.next_run_time.isoformat() if job.next_run_time else None} for job in self.scheduler.get_jobs()]
    def add_backup(self, hours: int) -> list[dict[str, str | None]]:
        self._schedule_backup(hours)
        self._save_backup_interval(hours)
        return self.jobs()
    def _schedule_backup(self, hours: int) -> None:
        self.scheduler.add_job(backup_service.create_backup, "interval", hours=hours, id="panel-backup", replace_existing=True, name=f"Backup cada {hours}h")
    def _load_backup_interval(self) -> int | None:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8")).get("backup_interval_hours")
            return value if isinstance(value, int) and 1 <= value <= 168 else None
        except (OSError, json.JSONDecodeError): return None
    def _save_backup_interval(self, hours: int) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps({"backup_interval_hours": hours}, indent=2) + "\n", encoding="utf-8"); os.replace(temporary, self.state_path)
        finally:
            if temporary.exists(): temporary.unlink()
scheduler_service = SchedulerService()
