"""Read-only access to background jobs, plus helpers for endpoints that start one."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import get_current_admin
from app.schemas.job import JobAccepted, JobOut
from app.services import job_service as job_module
from app.services.job_service import Job, JobConflictError, JobKind, JobWork
from app.services.progress import StepPlan

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(get_current_admin)])


def _service() -> job_module.JobService:
    # Resolved on each call so tests can swap the module-level instance.
    return job_module.job_service


@router.get("", response_model=list[JobOut])
async def list_jobs(limit: int = Query(default=20, ge=1, le=job_module.MAX_JOBS)) -> list[dict]:
    """Recent jobs, newest first. Running ones survive a page reload."""
    return [job.to_dict() for job in _service().recent(limit)]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str) -> dict:
    job = _service().get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos esa operación.")
    return job.to_dict()


def start_job(
    kind: JobKind,
    title: str,
    steps: StepPlan,
    work: JobWork,
    *,
    success_message: str = "Listo.",
) -> Job:
    """Start a job or answer 409 right away when a conflicting one is running."""
    try:
        return _service().submit(kind, title, steps, work, success_message=success_message)
    except JobConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


def accepted(job: Job, message: str) -> JobAccepted:
    return JobAccepted(job_id=job.id, job=JobOut.model_validate(job.to_dict()), message=message)
