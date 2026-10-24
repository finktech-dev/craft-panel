"""In-process background jobs with step progress, a short history and live updates.

Long operations (backups, restores, installs, restarts) run as asyncio tasks
owned by :class:`JobService`. Every job exposes an ordered list of steps, the
current step, an optional percent for that step and one plain sentence of what
is happening. Updates are pushed over the shared WebSocket broadcast as
``{"type": "job", "job": {...}}`` and the recent history is persisted to a small
JSON file, so a page reload or a panel restart still shows what happened.

Jobs never queue behind each other: a job that conflicts with one that is
already running is rejected immediately with :class:`JobConflictError` (409).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, get_args

from app.core.config import settings
from app.services.progress import StepPlan
from app.websocket.manager import ConnectionManager, connection_manager

logger = logging.getLogger("jobs")

JobKind = Literal["backup", "restore", "install_server", "install_java", "restart", "graceful_restart", "start"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
StepState = Literal["pending", "running", "done", "failed", "skipped"]

MAX_JOBS = 50
PANEL_CLOSED_MESSAGE = "El panel se cerró mientras corría."
CANCELLED_MESSAGE = "Se canceló antes de terminar."
GENERIC_ERROR_MESSAGE = "Algo falló de forma inesperada. Probá de nuevo; si se repite, revisá el registro del panel."
_ACTIVE_STATUSES: frozenset[str] = frozenset({"queued", "running"})
_HISTORY_VERSION = 1
# Percent-only updates are coalesced so a fast zip or download does not flood sockets or disk.
_BROADCAST_INTERVAL_SECONDS = 0.3
_PERSIST_INTERVAL_SECONDS = 2.0

_LIFECYCLE: frozenset[str] = frozenset({"start", "restart", "graceful_restart"})
# Which kinds may not run at the same time. Lifecycle operations must not overlap
# each other, a restore or a runtime install; backups and restores share one lock.
_CONFLICTS: dict[str, frozenset[str]] = {
    "backup": frozenset({"backup", "restore"}),
    "restore": frozenset({"backup", "restore", "install_server"}) | _LIFECYCLE,
    "install_server": frozenset({"install_server", "restore"}) | _LIFECYCLE,
    "install_java": frozenset({"install_java"}),
    "start": frozenset({"restore", "install_server"}) | _LIFECYCLE,
    "restart": frozenset({"restore", "install_server"}) | _LIFECYCLE,
    "graceful_restart": frozenset({"restore", "install_server"}) | _LIFECYCLE,
}

# What to do next when a job fails, in the same plain voice as the rest of the panel.
NEXT_STEPS: dict[str, str] = {
    "backup": "Probá de nuevo en un rato. Si vuelve a fallar, revisá que quede espacio libre en el disco.",
    "restore": "Probá de nuevo con el servidor apagado, o elegí otra copia.",
    "install_server": "No se reemplazó nada. Revisá tu conexión a Internet y probá de nuevo.",
    "install_java": "Revisá tu conexión a Internet y probá de nuevo, o instalá Java a mano.",
    "start": "Mirá la consola o la sección Problemas para ver qué pasó, y probá encenderlo de nuevo.",
    "restart": "Mirá la consola o la sección Problemas para ver qué pasó, y probá encenderlo de nuevo.",
    "graceful_restart": "Mirá la consola o la sección Problemas para ver qué pasó, y probá encenderlo de nuevo.",
}


class JobConflictError(RuntimeError):
    """Another job that cannot overlap with this one is still running."""

    status_code = 409


def _now() -> str:
    return datetime.now(UTC).isoformat()


def describe_error(error: BaseException) -> str:
    """Plain message for a failure: service errors already speak to the host."""
    detail = getattr(error, "detail", None)  # fastapi.HTTPException
    if isinstance(detail, str) and detail.strip():
        return detail
    if hasattr(error, "status_code") and str(error).strip():
        return str(error)
    return GENERIC_ERROR_MESSAGE


@dataclass(slots=True)
class JobStep:
    key: str
    label: str
    state: StepState = "pending"


@dataclass(slots=True)
class Job:
    id: str
    kind: str
    title: str
    steps: list[JobStep]
    status: JobStatus = "queued"
    current_step: int | None = None
    percent: float | None = None
    message: str = "En espera…"
    error: str | None = None
    next_step: str | None = None
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None

    @property
    def is_active(self) -> bool:
        return self.status in _ACTIVE_STATUSES

    def step_index(self, key: str) -> int | None:
        return next((index for index, step in enumerate(self.steps) if step.key == key), None)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job | None":
        """Rebuild a persisted job; malformed entries are dropped instead of crashing the panel."""
        try:
            status = data.get("status")
            if status not in get_args(JobStatus):
                return None
            steps = [
                JobStep(key=str(step["key"]), label=str(step["label"]), state=step.get("state", "pending"))
                for step in data.get("steps", [])
                if isinstance(step, dict)
            ]
            return cls(
                id=str(data["id"]),
                kind=str(data["kind"]),
                title=str(data.get("title") or data["kind"]),
                steps=steps,
                status=status,
                current_step=data.get("current_step") if isinstance(data.get("current_step"), int) else None,
                percent=data.get("percent") if isinstance(data.get("percent"), (int, float)) else None,
                message=str(data.get("message") or ""),
                error=data.get("error") if isinstance(data.get("error"), str) else None,
                next_step=data.get("next_step") if isinstance(data.get("next_step"), str) else None,
                created_at=str(data.get("created_at") or _now()),
                started_at=data.get("started_at"),
                finished_at=data.get("finished_at"),
                result=data.get("result") if isinstance(data.get("result"), dict) else None,
            )
        except (KeyError, TypeError, ValueError):
            return None


class JobReporter:
    """Progress callback handed to services: ``reporter(step, message, percent)``.

    Safe to call from worker threads; updates are applied on the event loop.
    The work function may set ``done_message`` to describe the outcome.
    """

    def __init__(self, service: "JobService", job_id: str) -> None:
        self._service = service
        self.job_id = job_id
        self.done_message: str | None = None

    def __call__(self, step: str, message: str | None = None, percent: float | None = None) -> None:
        self._service._dispatch(self.job_id, step, message, percent)

    def say(self, message: str, percent: float | None = None) -> None:
        """Update the sentence (and optionally the percent) without changing the step."""
        self._service._dispatch(self.job_id, None, message, percent)


JobWork = Callable[[JobReporter], Awaitable[Any]]


class JobService:
    def __init__(
        self,
        history_path: Path | None = None,
        websocket: ConnectionManager | None = connection_manager,
        max_jobs: int = MAX_JOBS,
    ) -> None:
        self._history_path = history_path
        self._websocket = websocket
        self._max_jobs = max_jobs
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._background: set[asyncio.Task[Any]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loaded = False
        self._closing = False
        self._dirty: set[str] = set()
        self._flush_handle: asyncio.TimerHandle | None = None
        self._last_persist = 0.0

    # ----------------------------------------------------------------- queries
    def recent(self, limit: int = MAX_JOBS) -> list[Job]:
        """Newest first."""
        self._ensure_loaded()
        return list(reversed(self._jobs.values()))[: max(0, limit)]

    def get(self, job_id: str) -> Job | None:
        self._ensure_loaded()
        return self._jobs.get(job_id)

    def active(self) -> list[Job]:
        return [job for job in self.recent() if job.is_active]

    def conflicting_job(self, kind: str) -> Job | None:
        blocked = _CONFLICTS.get(kind, frozenset({kind}))
        return next((job for job in self.active() if job.kind in blocked), None)

    # -------------------------------------------------------------- lifecycle
    def submit(
        self,
        kind: JobKind,
        title: str,
        steps: StepPlan,
        work: JobWork,
        *,
        success_message: str = "Listo.",
    ) -> Job:
        """Create a job and start it right away; never queue behind a conflicting one."""
        self._ensure_loaded()
        if conflict := self.conflicting_job(kind):
            raise JobConflictError(f"Ya hay una operación en curso ({conflict.title.lower()}). Esperá a que termine.")
        self._loop = asyncio.get_running_loop()
        job = Job(
            id=uuid.uuid4().hex,
            kind=kind,
            title=title,
            steps=[JobStep(key=key, label=label) for key, label in steps],
        )
        self._remember(job)
        task = self._loop.create_task(self._run(job, work, success_message), name=f"job-{kind}-{job.id[:8]}")
        self._tasks[job.id] = task
        task.add_done_callback(lambda finished, job_id=job.id: self._task_done(job_id, finished))
        self._changed(job, important=True)
        return job

    async def wait(self, job_id: str) -> Job | None:
        """Wait until a job finishes (used by tests and by callers that need the outcome)."""
        task = self._tasks.get(job_id)
        if task is not None:
            await asyncio.wait({task})
        return self.get(job_id)

    def spawn(self, coroutine: Coroutine[Any, Any, Any], name: str) -> asyncio.Task[Any]:
        """Fire-and-forget task whose failure is logged instead of silently lost."""
        task = asyncio.get_running_loop().create_task(coroutine, name=name)
        self._background.add(task)
        task.add_done_callback(self._background_done)
        return task

    def shutdown(self) -> None:
        """Mark that the panel is closing: interrupted jobs are recorded as such."""
        self._closing = True
        if not self._loaded:
            return  # nothing was ever read or started in this process
        for job in self._jobs.values():
            if job.is_active:
                self._finish(job, "failed", error=PANEL_CLOSED_MESSAGE, broadcast=False)
        self._persist(force=True)

    async def _run(self, job: Job, work: JobWork, success_message: str) -> None:
        job.status = "running"
        job.started_at = _now()
        job.message = job.steps[0].label if job.steps else "Trabajando…"
        self._changed(job, important=True)
        reporter = JobReporter(self, job.id)
        try:
            result = await work(reporter)
        except asyncio.CancelledError:
            if job.is_active:
                if self._closing:
                    self._finish(job, "failed", error=PANEL_CLOSED_MESSAGE)
                else:
                    self._finish(job, "cancelled", message=CANCELLED_MESSAGE)
            raise
        except Exception as error:  # noqa: BLE001 - every failure is recorded on the job
            message = describe_error(error)
            if message == GENERIC_ERROR_MESSAGE:
                logger.exception("Job %s (%s) failed unexpectedly.", job.id, job.kind)
            else:
                logger.warning("Job %s (%s) failed: %s", job.id, job.kind, message)
            if job.is_active:
                self._finish(job, "failed", error=message)
        else:
            if not job.is_active:
                return  # already recorded as interrupted by shutdown()
            if hasattr(result, "model_dump"):
                result = result.model_dump(mode="json")
            job.result = result if isinstance(result, dict) else None
            self._finish(job, "succeeded", message=reporter.done_message or success_message)

    def _finish(
        self,
        job: Job,
        status: JobStatus,
        *,
        message: str | None = None,
        error: str | None = None,
        broadcast: bool = True,
    ) -> None:
        job.status = status
        job.finished_at = _now()
        job.error = error
        for step in job.steps:
            if step.state == "running":
                step.state = "done" if status == "succeeded" else "failed"
            elif step.state == "pending" and status == "succeeded":
                step.state = "skipped"
        if status == "succeeded":
            job.percent = 100.0
        if status == "failed":
            job.next_step = NEXT_STEPS.get(job.kind)
        job.message = message or error or job.message
        if broadcast:
            self._changed(job, important=True)

    def _task_done(self, job_id: str, task: asyncio.Task[None]) -> None:
        self._tasks.pop(job_id, None)
        if task.cancelled():
            return
        if (error := task.exception()) is not None:
            logger.error("Job task %s ended with an unhandled error.", job_id, exc_info=error)

    def _background_done(self, task: asyncio.Task[Any]) -> None:
        self._background.discard(task)
        if task.cancelled():
            return
        if (error := task.exception()) is not None:
            logger.error("Background task %s failed.", task.get_name(), exc_info=error)

    # --------------------------------------------------------------- progress
    def _dispatch(self, job_id: str, step: str | None, message: str | None, percent: float | None) -> None:
        loop = self._loop
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if loop is None or running is loop:
            self._apply(job_id, step, message, percent)
        elif not loop.is_closed():
            loop.call_soon_threadsafe(self._apply, job_id, step, message, percent)

    def _apply(self, job_id: str, step: str | None, message: str | None, percent: float | None) -> None:
        job = self._jobs.get(job_id)
        if job is None or not job.is_active:
            return
        step_changed = False
        index = job.step_index(step) if step is not None else None
        if index is not None and index != job.current_step:
            for item in job.steps[:index]:
                if item.state == "running":
                    item.state = "done"
                elif item.state == "pending":
                    item.state = "skipped"
            job.steps[index].state = "running"
            job.current_step = index
            job.percent = None
            step_changed = True
            if message is None:
                message = job.steps[index].label
        if message is not None:
            job.message = message
        if percent is not None:
            job.percent = round(max(0.0, min(100.0, float(percent))), 1)
        self._changed(job, important=step_changed)

    # ------------------------------------------------------ storage & sockets
    def _remember(self, job: Job) -> None:
        self._jobs[job.id] = job
        while len(self._jobs) > self._max_jobs:
            oldest_id = next((job_id for job_id, item in self._jobs.items() if not item.is_active), None)
            if oldest_id is None:
                break
            del self._jobs[oldest_id]

    def _changed(self, job: Job, *, important: bool) -> None:
        if important:
            self._dirty.discard(job.id)
            self._persist(force=True)
            self._broadcast(job)
            return
        self._dirty.add(job.id)
        if self._flush_handle is None and self._loop is not None and not self._loop.is_closed():
            self._flush_handle = self._loop.call_later(_BROADCAST_INTERVAL_SECONDS, self._flush)

    def _flush(self) -> None:
        self._flush_handle = None
        pending, self._dirty = self._dirty, set()
        for job_id in pending:
            if (job := self._jobs.get(job_id)) is not None:
                self._broadcast(job)
        self._persist(force=False)

    def _broadcast(self, job: Job) -> None:
        if self._websocket is None:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self.spawn(self._websocket.broadcast_json({"type": "job", "job": job.to_dict()}), "job-broadcast")

    def _persist(self, *, force: bool) -> None:
        if self._history_path is None:
            return
        now = time.monotonic()
        if not force and now - self._last_persist < _PERSIST_INTERVAL_SECONDS:
            return
        self._last_persist = now
        payload = {"version": _HISTORY_VERSION, "jobs": [job.to_dict() for job in self._jobs.values()]}
        temporary = self._history_path.with_name(f"{self._history_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(temporary, self._history_path)
        except OSError as error:
            logger.warning("Could not save the job history: %s", error)
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self._history_path is None or not self._history_path.is_file():
            return
        try:
            data = json.loads(self._history_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            logger.warning("Ignoring an unreadable job history: %s", error)
            return
        entries = data.get("jobs", []) if isinstance(data, dict) else []
        interrupted = False
        for entry in entries if isinstance(entries, list) else []:
            job = Job.from_dict(entry) if isinstance(entry, dict) else None
            if job is None or job.id in self._jobs:
                continue
            if job.is_active:
                # This process did not start it, so whatever was running died with the old panel.
                self._finish(job, "failed", error=PANEL_CLOSED_MESSAGE, broadcast=False)
                interrupted = True
            self._remember(job)
        if interrupted:
            self._persist(force=True)


def _default_history_path() -> Path | None:
    return settings.panel_directory / ".jobs_history.json" if settings.panel_directory else None


job_service = JobService(history_path=_default_history_path())
