"""Public shape of background jobs (long operations with progress)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class JobStepOut(BaseModel):
    key: str
    label: str
    state: Literal["pending", "running", "done", "failed", "skipped"]


class JobOut(BaseModel):
    id: str
    kind: str
    title: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    steps: list[JobStepOut]
    current_step: int | None = None
    percent: float | None = None
    message: str
    error: str | None = None
    next_step: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None


class JobAccepted(BaseModel):
    """Answer of every endpoint that starts a job (HTTP 202).

    ``success`` and ``message`` keep older clients that only showed a sentence working.
    """

    success: bool = True
    job_id: str
    job: JobOut
    message: str
