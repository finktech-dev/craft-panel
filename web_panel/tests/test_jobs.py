"""Background jobs: lifecycle, persisted history, progress reporting and the HTTP contract."""

from __future__ import annotations

import asyncio
import json
import logging
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.api import endpoints_backups, endpoints_jobs, endpoints_server
from app.core.config import Settings, settings
from app.core.rate_limit import limiter
from app.core.security import get_current_admin
from app.services import job_service as job_module
from app.services.backup_service import BACKUP_STEPS, RESTORE_STEPS, BackupService, BackupServiceError
from app.services.job_service import (
    GENERIC_ERROR_MESSAGE,
    PANEL_CLOSED_MESSAGE,
    JobConflictError,
    JobService,
)
from app.services.server_process import ServerStartTimeoutError

STEPS = (("first", "Primer paso"), ("second", "Segundo paso"), ("third", "Tercer paso"))


class RecordingSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def broadcast_json(self, payload) -> None:
        self.messages.append(json.loads(json.dumps(payload)))


class StoppedServer:
    is_running = False


class RunningServer:
    is_running = True


class SilentDiscord:
    async def send_backup_created(self, backup) -> None:
        return None


def _jobs(tmp_path: Path, **kwargs) -> tuple[JobService, RecordingSocket]:
    socket = RecordingSocket()
    return JobService(history_path=tmp_path / "jobs.json", websocket=socket, **kwargs), socket


def _backup_service(tmp_path: Path) -> BackupService:
    configured = Settings(project_root=tmp_path, backup_min_free_disk_gb=0)
    assert configured.server_directory is not None
    world = configured.server_directory / "world"
    (world / "region").mkdir(parents=True)
    (world / "level.dat").write_bytes(b"level")
    for index in range(5):
        (world / "region" / f"r.{index}.0.mca").write_bytes(bytes([index]) * 2048)
    return BackupService(configured_settings=configured, manager=StoppedServer(), discord=SilentDiscord())


def _step_order(calls: list[tuple[str, str | None, float | None]]) -> list[str]:
    order: list[str] = []
    for step, _, _ in calls:
        if not order or order[-1] != step:
            order.append(step)
    return order


# --------------------------------------------------------------- job lifecycle
@pytest.mark.asyncio
async def test_successful_job_records_steps_message_and_result(tmp_path: Path) -> None:
    service, _ = _jobs(tmp_path)

    async def work(reporter):
        reporter("first")
        reporter("second", "Copiados 1 de 2 archivos.", 50)
        reporter.done_message = "Todo listo."
        return {"value": 1}

    job = service.submit("backup", "Copia del mundo", STEPS, work)
    finished = await service.wait(job.id)

    assert finished.status == "succeeded"
    assert finished.message == "Todo listo."
    assert finished.result == {"value": 1}
    assert [step.state for step in finished.steps] == ["done", "done", "skipped"]
    assert finished.started_at and finished.finished_at
    assert finished.error is None


@pytest.mark.asyncio
async def test_failure_is_captured_with_plain_message_and_next_step(tmp_path: Path, caplog) -> None:
    service, _ = _jobs(tmp_path)

    async def work(reporter):
        reporter("second")
        raise BackupServiceError("Espacio insuficiente para un backup seguro.")

    with caplog.at_level(logging.WARNING, logger="jobs"):
        job = service.submit("backup", "Copia del mundo", STEPS, work)
        finished = await service.wait(job.id)

    assert finished.status == "failed"
    assert finished.error == "Espacio insuficiente para un backup seguro."
    assert finished.next_step  # what to do next is always offered
    assert [step.state for step in finished.steps] == ["skipped", "failed", "pending"]
    assert "Espacio insuficiente" in caplog.text


@pytest.mark.asyncio
async def test_unexpected_errors_are_logged_and_shown_generically(tmp_path: Path, caplog) -> None:
    service, _ = _jobs(tmp_path)

    async def work(reporter):
        raise ZeroDivisionError("internal detail")

    with caplog.at_level(logging.ERROR, logger="jobs"):
        job = service.submit("restore", "Volver a una copia", STEPS, work)
        finished = await service.wait(job.id)

    assert finished.status == "failed"
    assert finished.error == GENERIC_ERROR_MESSAGE
    assert "internal detail" not in finished.error
    assert "ZeroDivisionError" in caplog.text


@pytest.mark.asyncio
async def test_history_is_persisted_and_survives_a_new_service(tmp_path: Path) -> None:
    service, _ = _jobs(tmp_path)

    async def work(reporter):
        reporter("first")
        return {"backup": "backup_x.zip"}

    job = service.submit("backup", "Copia del mundo", STEPS, work)
    await service.wait(job.id)

    reloaded, _ = _jobs(tmp_path)
    restored = reloaded.get(job.id)
    assert restored is not None
    assert restored.status == "succeeded"
    assert restored.result == {"backup": "backup_x.zip"}
    assert [item.id for item in reloaded.recent()] == [job.id]


@pytest.mark.asyncio
async def test_jobs_running_when_the_panel_died_are_marked_failed(tmp_path: Path) -> None:
    service, _ = _jobs(tmp_path)
    release = asyncio.Event()

    async def work(reporter):
        reporter("second")
        await release.wait()

    job = service.submit("backup", "Copia del mundo", STEPS, work)
    await asyncio.sleep(0.01)
    on_disk = json.loads((tmp_path / "jobs.json").read_text(encoding="utf-8"))
    assert on_disk["jobs"][0]["status"] == "running"

    # A new process reads the history while the old task never finished.
    reloaded, _ = _jobs(tmp_path)
    interrupted = reloaded.get(job.id)
    assert interrupted.status == "failed"
    assert interrupted.error == PANEL_CLOSED_MESSAGE
    assert interrupted.steps[1].state == "failed"
    assert reloaded.active() == []
    persisted = json.loads((tmp_path / "jobs.json").read_text(encoding="utf-8"))
    assert persisted["jobs"][0]["status"] == "failed"

    release.set()
    await service.wait(job.id)


@pytest.mark.asyncio
async def test_shutdown_records_interrupted_jobs(tmp_path: Path) -> None:
    service, _ = _jobs(tmp_path)

    async def work(reporter):
        await asyncio.sleep(10)

    job = service.submit("install_java", "Descargar Java", STEPS, work)
    await asyncio.sleep(0.01)
    service.shutdown()
    service._tasks[job.id].cancel()
    await service.wait(job.id)

    assert service.get(job.id).status == "failed"
    assert service.get(job.id).error == PANEL_CLOSED_MESSAGE


@pytest.mark.asyncio
async def test_conflicting_jobs_fail_fast_instead_of_queueing(tmp_path: Path) -> None:
    service, _ = _jobs(tmp_path)
    release = asyncio.Event()

    async def blocked(reporter):
        await release.wait()

    async def quick(reporter):
        return None

    running = service.submit("backup", "Copia del mundo", STEPS, blocked)
    with pytest.raises(JobConflictError, match="copia del mundo"):
        service.submit("backup", "Copia del mundo", STEPS, quick)
    with pytest.raises(JobConflictError):
        service.submit("restore", "Volver a una copia", STEPS, quick)
    other = service.submit("install_java", "Descargar Java", STEPS, quick)  # unrelated work is fine
    await service.wait(other.id)

    release.set()
    await service.wait(running.id)
    again = service.submit("backup", "Copia del mundo", STEPS, quick)
    assert (await service.wait(again.id)).status == "succeeded"


@pytest.mark.asyncio
async def test_progress_from_worker_threads_is_applied_on_the_loop(tmp_path: Path) -> None:
    service, _ = _jobs(tmp_path)
    seen: list[float | None] = []

    def blocking(reporter) -> None:
        reporter("second", "Trabajando en un hilo.", 40)

    async def work(reporter):
        await asyncio.to_thread(blocking, reporter)
        await asyncio.sleep(0.01)
        seen.append(service.get(reporter.job_id).percent)

    job = service.submit("backup", "Copia del mundo", STEPS, work)
    await service.wait(job.id)

    assert seen == [40.0]


@pytest.mark.asyncio
async def test_history_keeps_only_the_most_recent_jobs(tmp_path: Path) -> None:
    service, _ = _jobs(tmp_path, max_jobs=3)

    async def work(reporter):
        return None

    ids = []
    for _ in range(5):
        job = service.submit("install_java", "Descargar Java", STEPS, work)
        await service.wait(job.id)
        ids.append(job.id)

    assert [job.id for job in service.recent()] == list(reversed(ids[-3:]))


@pytest.mark.asyncio
async def test_websocket_messages_carry_the_whole_job(tmp_path: Path) -> None:
    service, socket = _jobs(tmp_path)

    async def work(reporter):
        reporter("first", "Empezando.")
        return None

    job = service.submit("backup", "Copia del mundo", STEPS, work)
    await service.wait(job.id)
    await asyncio.sleep(0.01)

    assert socket.messages
    assert all(message["type"] == "job" for message in socket.messages)
    last = socket.messages[-1]["job"]
    assert last["id"] == job.id
    assert last["status"] == "succeeded"
    assert set(last) >= {
        "id", "kind", "title", "status", "steps", "current_step", "percent",
        "message", "error", "next_step", "created_at", "started_at", "finished_at", "result",
    }
    assert last["steps"][0] == {"key": "first", "label": "Primer paso", "state": "done"}
    assert [message["job"]["status"] for message in socket.messages][0] in {"queued", "running"}


# ----------------------------------------------------- real progress reporting
@pytest.mark.asyncio
async def test_backup_reports_prepare_archive_verify_retention(tmp_path: Path) -> None:
    service = _backup_service(tmp_path)
    calls: list[tuple[str, str | None, float | None]] = []

    backup = await service.create_backup(progress=lambda step, message=None, percent=None: calls.append((step, message, percent)))

    assert (service.backups_directory / backup.filename).is_file()
    assert _step_order(calls) == [key for key, _ in BACKUP_STEPS]
    archive = [call for call in calls if call[0] == "archive" and call[2] is not None]
    assert archive and archive[-1][2] == pytest.approx(100.0)
    assert "6 de 6 archivos" in archive[-1][1]


@pytest.mark.asyncio
async def test_backup_without_progress_keeps_working(tmp_path: Path) -> None:
    service = _backup_service(tmp_path)
    assert (await service.create_backup()).filename.startswith("backup_")


@pytest.mark.asyncio
async def test_restore_reports_extract_verify_swap(tmp_path: Path) -> None:
    service = _backup_service(tmp_path)
    backup = await service.create_backup()
    (service.world_directory / "level.dat").write_bytes(b"changed after the copy")
    calls: list[tuple[str, str | None, float | None]] = []

    await service.restore_backup(backup.filename, progress=lambda step, message=None, percent=None: calls.append((step, message, percent)))

    assert _step_order(calls) == [key for key, _ in RESTORE_STEPS]
    extract = [call for call in calls if call[0] == "extract" and call[2] is not None]
    assert extract and extract[-1][2] == pytest.approx(100.0)
    assert (service.world_directory / "level.dat").read_bytes() == b"level"


@pytest.mark.asyncio
async def test_a_broken_progress_listener_never_breaks_the_backup(tmp_path: Path) -> None:
    service = _backup_service(tmp_path)

    def broken(step, message=None, percent=None):
        raise RuntimeError("listener bug")

    assert (await service.create_backup(progress=broken)).filename.endswith(".zip")


# ------------------------------------------------------------------ HTTP layer
@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    limiter.reset()
    jobs, socket = _jobs(tmp_path / "panel")
    monkeypatch.setattr(job_module, "job_service", jobs)
    backups = _backup_service(tmp_path)
    monkeypatch.setattr(endpoints_backups, "backup_service", backups)
    monkeypatch.setattr(endpoints_backups, "server_manager", StoppedServer())
    app = FastAPI()
    app.include_router(endpoints_backups.router, prefix="/api")
    app.include_router(endpoints_server.router, prefix="/api")
    app.include_router(endpoints_jobs.router, prefix="/api")
    app.dependency_overrides[get_current_admin] = lambda: "admin"
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    yield client, jobs, backups, socket
    limiter.reset()


@pytest.mark.asyncio
async def test_backup_endpoint_answers_202_with_a_job_id(api) -> None:
    client, jobs, backups, socket = api
    async with client:
        response = await client.post("/api/backups")
        assert response.status_code == 202
        body = response.json()
        assert body["job_id"] == body["job"]["id"]
        assert body["job"]["kind"] == "backup"
        assert [step["key"] for step in body["job"]["steps"]] == [key for key, _ in BACKUP_STEPS]

        await jobs.wait(body["job_id"])
        detail = (await client.get(f"/api/jobs/{body['job_id']}")).json()
        assert detail["status"] == "succeeded"
        assert detail["result"]["backup"]["filename"].startswith("backup_")
        assert [job["id"] for job in (await client.get("/api/jobs")).json()] == [body["job_id"]]
        assert (await client.get("/api/jobs/unknown")).status_code == 404
    assert any(message["job"]["id"] == body["job_id"] for message in socket.messages)


@pytest.mark.asyncio
async def test_backup_endpoint_conflicts_fail_fast_with_409(api) -> None:
    client, jobs, backups, _ = api
    async with client:
        async with backups._operation_lock:
            busy = await client.post("/api/backups")
        assert busy.status_code == 409
        assert "operación de backups en curso" in busy.json()["detail"]

        release = asyncio.Event()

        async def blocked(reporter):
            await release.wait()

        running = jobs.submit("restore", "Volver a una copia", RESTORE_STEPS, blocked)
        conflict = await client.post("/api/backups")
        assert conflict.status_code == 409
        assert "volver a una copia" in conflict.json()["detail"]
        release.set()
        await jobs.wait(running.id)
    assert len(jobs.recent()) == 1  # nothing was queued behind the running job


@pytest.mark.asyncio
async def test_restore_endpoint_runs_as_a_job_and_refuses_a_live_server(api, monkeypatch) -> None:
    client, jobs, backups, _ = api
    backup = await backups.create_backup()
    async with client:
        monkeypatch.setattr(endpoints_backups, "server_manager", RunningServer())
        live = await client.post(f"/api/backups/{backup.filename}/restore")
        assert live.status_code == 409
        assert jobs.recent() == []

        monkeypatch.setattr(endpoints_backups, "server_manager", StoppedServer())
        assert (await client.post("/api/backups/missing.zip/restore")).status_code == 404
        response = await client.post(f"/api/backups/{backup.filename}/restore")
        assert response.status_code == 202
        finished = await jobs.wait(response.json()["job_id"])
    assert finished.kind == "restore"
    assert finished.status == "succeeded"
    assert [step.state for step in finished.steps] == ["done", "done", "done"]


class FakeLifecycle:
    """Stands in for the server manager inside restart jobs."""

    lifecycle_operation = None
    is_running = True
    state = "RUNNING"

    def __init__(self, ready_error: Exception | None = None) -> None:
        self.ready_error = ready_error

    async def graceful_restart(self, countdown_seconds: int = 10, dev_mode=None, progress=None) -> bool:
        for step in ("notice", "save", "stop", "start"):
            progress(step)
        return True

    async def restart(self, dev_mode=None, progress=None) -> bool:
        progress("stop")
        progress("start")
        return True

    async def wait_until_ready(self, timeout_seconds: float = 120.0) -> None:
        if self.ready_error:
            raise self.ready_error


@pytest.mark.asyncio
async def test_graceful_restart_answers_202_and_walks_every_step(api, monkeypatch) -> None:
    client, jobs, _, _ = api
    monkeypatch.setattr(endpoints_server, "server_manager", FakeLifecycle())
    monkeypatch.setattr(settings, "playit_enabled", False)
    async with client:
        response = await client.post("/api/server/graceful-restart?countdown=5")
        assert response.status_code == 202
        finished = await jobs.wait(response.json()["job_id"])

    assert finished.kind == "graceful_restart"
    assert finished.status == "succeeded"
    assert [step.key for step in finished.steps] == ["notice", "save", "stop", "start", "ready"]
    assert all(step.state == "done" for step in finished.steps)


@pytest.mark.asyncio
async def test_restart_that_is_still_loading_ends_with_a_clear_note(api, monkeypatch) -> None:
    client, jobs, _, _ = api
    monkeypatch.setattr(
        endpoints_server, "server_manager", FakeLifecycle(ServerStartTimeoutError("todavía no terminó"))
    )
    monkeypatch.setattr(settings, "playit_enabled", False)
    async with client:
        response = await client.post("/api/server/restart")
        finished = await jobs.wait(response.json()["job_id"])

    assert finished.status == "succeeded"
    assert "sigue cargando" in finished.message


@pytest.mark.asyncio
async def test_restart_whose_server_dies_while_loading_fails_with_next_step(api, monkeypatch) -> None:
    from app.services.server_process import ServerProcessError

    client, jobs, _, _ = api
    monkeypatch.setattr(
        endpoints_server,
        "server_manager",
        FakeLifecycle(ServerProcessError("El servidor se cerró antes de terminar de encender.")),
    )
    monkeypatch.setattr(settings, "playit_enabled", False)
    async with client:
        response = await client.post("/api/server/restart")
        finished = await jobs.wait(response.json()["job_id"])

    assert finished.status == "failed"
    assert finished.error == "El servidor se cerró antes de terminar de encender."
    assert finished.next_step
    assert finished.steps[-1].state == "failed"


@pytest.mark.asyncio
async def test_second_lifecycle_request_is_rejected_while_a_restart_job_runs(api, monkeypatch) -> None:
    client, jobs, _, _ = api
    release = asyncio.Event()

    class SlowLifecycle(FakeLifecycle):
        async def restart(self, dev_mode=None, progress=None) -> bool:
            await release.wait()
            return True

    monkeypatch.setattr(endpoints_server, "server_manager", SlowLifecycle())
    monkeypatch.setattr(settings, "playit_enabled", False)
    async with client:
        first = await client.post("/api/server/restart")
        second = await client.post("/api/server/graceful-restart")
        assert first.status_code == 202
        assert second.status_code == 409
        release.set()
        await jobs.wait(first.json()["job_id"])


def test_backup_archive_is_a_valid_zip_after_progress(tmp_path: Path) -> None:
    service = _backup_service(tmp_path)
    target = tmp_path / "manual.zip"
    service._create_archive_sync(target, progress=lambda *args: None)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == 6
