"""Mods folder history: snapshots on every change, external changes and safe rollback."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from app.api import endpoints_mods
from app.core.config import Settings
from app.schemas.mod import ModHistoryRestoreRequest
from app.services import mod_history_service as history_module
from app.services.mod_history_service import (
    RESTORE_WHILE_RUNNING_MESSAGE,
    ModHistoryConflictError,
    ModHistoryError,
    ModHistoryNotFoundError,
    ModHistoryService,
    is_mod_filename,
)
from app.services.mod_service import ModService


class _Server:
    def __init__(self) -> None:
        self.is_running = False


def _jar(mod_id: str, version: str, name: str | None = None, salt: str = "") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "fabric.mod.json",
            json.dumps({"id": mod_id, "name": name or mod_id.title(), "version": version}),
        )
        archive.writestr("padding.txt", "x" * 200 + salt)
    return buffer.getvalue()


def _upload(name: str, content: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=name, headers=Headers({}))


def _service(tmp_path: Path, **history_options) -> tuple[ModService, _Server]:
    server = _Server()
    service = ModService(configured_settings=Settings(project_root=tmp_path), manager=server)
    if history_options:
        service.history = ModHistoryService(service._settings, server, **history_options)
    service.mods_directory.mkdir(parents=True, exist_ok=True)
    return service, server


def _folder(service: ModService) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in service.mods_directory.iterdir()
        if path.is_file()
    }


def _install_stub(service: ModService, filename: str, content: bytes):
    async def fake_install(*_args, **_kwargs):
        destination = service.mods_directory / filename
        destination.write_bytes(content)
        return service._mod_item_from_path(destination)

    return fake_install


@pytest.mark.asyncio
async def test_each_panel_action_records_a_snapshot_with_a_plain_summary(tmp_path: Path, monkeypatch) -> None:
    service, _ = _service(tmp_path)
    (service.mods_directory / "lib.jar").write_bytes(_jar("lib", "1.0", "Lib"))

    await service.upload_mod(_upload("create-0.5.jar", _jar("create", "0.5", "Create")))
    await service.toggle_mod("lib.jar")
    await service.bulk_action("enable", ["lib.jar.disabled"])
    monkeypatch.setattr(service, "_install_modrinth_mod", _install_stub(service, "create-6.0.jar", _jar("create", "6.0", "Create")))
    await service.install_modrinth_mod("create", replace_filename="create-0.5.jar")
    monkeypatch.setattr(service, "_install_modrinth_mod", _install_stub(service, "jei.jar", _jar("jei", "1", "JEI")))
    await service.install_modrinth_mod("jei")
    await service.delete_mod("jei.jar")

    history = service.history.list_history()
    assert [entry["action"] for entry in history] == [
        "delete", "install", "update", "bulk_enable", "toggle", "upload",
    ]
    assert [entry["summary"] for entry in history] == [
        "Quitaste JEI",
        "Instalaste JEI",
        "Actualizaste Create de 0.5 a 6.0",
        "Encendiste Lib",
        "Apagaste Lib",
        "Agregaste Create",
    ]
    update = history[2]
    assert (update["added"], update["removed"], update["updated"]) == (0, 0, 1)
    assert all(entry["restorable"] for entry in history)
    # The update replaced the old jar instead of leaving both versions installed.
    assert set(_folder(service)) == {"lib.jar", "create-6.0.jar"}


@pytest.mark.asyncio
async def test_failed_action_leaves_no_snapshot(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    with pytest.raises(Exception):
        await service.upload_mod(_upload("bad.jar", b"MZ not a jar"))
    await service.upload_mod(_upload("good.jar", _jar("good", "1")))
    with pytest.raises(Exception):
        await service.upload_mod(_upload("good.jar", _jar("good", "2")))
    assert [entry["action"] for entry in service.history.list_history()] == ["upload"]


@pytest.mark.asyncio
async def test_external_changes_are_detected_once_and_only_changed_files_are_hashed(tmp_path: Path, monkeypatch) -> None:
    service, _ = _service(tmp_path)
    for index in range(3):
        (service.mods_directory / f"mod{index}.jar").write_bytes(_jar(f"mod{index}", "1"))
    await service.list_mods()  # first look: baseline only
    assert service.history.list_history() == []

    hashed: list[str] = []
    original = history_module._sha256_file
    monkeypatch.setattr(history_module, "_sha256_file", lambda path: hashed.append(path.name) or original(path))

    (service.mods_directory / "extra.jar").write_bytes(_jar("extra", "1", "Extra"))
    (service.mods_directory / "mod0.jar").unlink()
    await service.list_mods()
    await service.list_mods()

    assert hashed == ["extra.jar"]
    history = service.history.list_history()
    assert len(history) == 1
    assert history[0]["action"] == "external"
    assert history[0]["summary"] == "Cambios hechos por fuera del panel: se agregó Extra y se quitó Mod0"
    # The jar deleted by hand is still in the cache, so the point can be restored.
    assert history[0]["restorable"] is True
    service.history.restore(history[0]["id"])
    assert set(_folder(service)) == {"mod0.jar", "mod1.jar", "mod2.jar"}


@pytest.mark.asyncio
async def test_identical_jars_are_cached_once(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    content = _jar("same", "1")
    (service.mods_directory / "a.jar").write_bytes(content)
    await service.upload_mod(_upload("b.jar", content))
    await service.toggle_mod("a.jar")
    await service.delete_mod("b.jar")
    cached = [p.name for p in service.history.jars_directory.iterdir() if p.suffix == ".jar"]
    assert cached == [f"{hashlib.sha256(content).hexdigest()}.jar"]


@pytest.mark.asyncio
async def test_retention_never_drops_jars_referenced_by_kept_snapshots(tmp_path: Path) -> None:
    jar_size = len(_jar("m", "1", salt="0"))
    service, _ = _service(tmp_path, max_snapshots=4, max_history_bytes=jar_size * 2)
    for index in range(8):
        await service.upload_mod(_upload(f"m{index}.jar", _jar(f"m{index}", "1", salt=str(index))))
        await service.delete_mod(f"m{index}.jar")

    manifest = json.loads(service.history.manifest_path.read_text(encoding="utf-8"))
    snapshots = manifest["snapshots"]
    assert 1 <= len(snapshots) <= 4
    referenced = {record["sha256"] for snapshot in snapshots for record in snapshot["files"]}
    cached = {p.stem for p in service.history.jars_directory.glob("*.jar")}
    assert referenced <= cached
    assert cached <= referenced | {r["sha256"] for r in manifest["current"]}
    assert all(entry["restorable"] for entry in service.history.list_history())


@pytest.mark.asyncio
async def test_rollback_restores_exact_bytes_and_enabled_state_and_can_be_undone(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    (service.mods_directory / "a.jar").write_bytes(_jar("a", "1", "A"))
    (service.mods_directory / "b.jar.disabled").write_bytes(_jar("b", "1", "B"))
    (service.mods_directory / "notes.txt").write_text("not a mod")
    await service.list_mods()
    original = _folder(service)

    await service.delete_mod("a.jar")
    await service.toggle_mod("b.jar.disabled")
    await service.upload_mod(_upload("c.jar", _jar("c", "1", "C")))
    changed = _folder(service)

    target = service.history.list_history()[-1]
    detail = service.history.get_history(target["id"])
    assert "Vuelve A 1" in detail["lines"] and "Se quita C 1" in detail["lines"] and "Se apaga B" in detail["lines"]

    result = service.history.restore(target["id"])
    assert _folder(service) == original
    assert result["undo_id"]
    assert service.history.list_history()[0]["action"] == "restore"

    service.history.restore(result["undo_id"])
    assert _folder(service) == changed
    assert not [p for p in service.mods_directory.iterdir() if p.is_dir()]


@pytest.mark.asyncio
async def test_rollback_is_refused_while_the_server_is_running(tmp_path: Path) -> None:
    service, server = _service(tmp_path)
    await service.upload_mod(_upload("a.jar", _jar("a", "1")))
    snapshot_id = service.history.list_history()[0]["id"]
    before = _folder(service)
    server.is_running = True
    with pytest.raises(ModHistoryConflictError, match=RESTORE_WHILE_RUNNING_MESSAGE):
        service.history.restore(snapshot_id)
    assert _folder(service) == before


@pytest.mark.asyncio
async def test_partial_failure_while_swapping_leaves_the_folder_unchanged(tmp_path: Path, monkeypatch) -> None:
    service, _ = _service(tmp_path)
    for name in ("a.jar", "b.jar", "c.jar"):
        (service.mods_directory / name).write_bytes(_jar(name[0], "1"))
    await service.list_mods()
    await service.bulk_action("delete", ["a.jar", "b.jar"])
    await service.upload_mod(_upload("d.jar", _jar("d", "1")))
    before = _folder(service)
    target = service.history.list_history()[-1]["id"]

    calls = {"count": 0}
    real_move = history_module._move

    def flaky_move(source: Path, destination: Path) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("disk went away")
        real_move(source, destination)

    monkeypatch.setattr(history_module, "_move", flaky_move)
    with pytest.raises(ModHistoryError, match="quedaron como estaban"):
        service.history.restore(target)
    assert _folder(service) == before
    assert not [p for p in service.mods_directory.iterdir() if p.is_dir()]
    # The failed attempt does not leave a "restore" entry behind.
    assert service.history.list_history()[0]["action"] == "upload"


@pytest.mark.asyncio
async def test_corrupted_cached_jar_is_detected_and_nothing_changes(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    content = _jar("a", "1")
    await service.upload_mod(_upload("a.jar", content))
    await service.delete_mod("a.jar")
    target = service.history.list_history()[0]["id"]
    cached = service.history.jars_directory / f"{hashlib.sha256(content).hexdigest()}.jar"
    cached.unlink()
    cached.write_bytes(b"tampered")
    with pytest.raises(ModHistoryError, match="copia sana"):
        service.history.restore(target)
    assert _folder(service) == {}


@pytest.mark.parametrize(
    "name",
    ["../evil.jar", "..\\evil.jar", "mods/evil.jar", "a.jar:stream", "CON.jar", "nul.jar.disabled", "evil.jar.", "evil.exe", ""],
)
def test_unsafe_mod_filenames_are_rejected(name: str) -> None:
    assert not is_mod_filename(name)


@pytest.mark.asyncio
async def test_tampered_manifest_cannot_point_outside_the_mods_folder(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    await service.upload_mod(_upload("a.jar", _jar("a", "1")))
    manifest_path = service.history.manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snapshot_id = manifest["snapshots"][0]["id"]
    manifest["snapshots"][0]["files"] = [
        {"filename": "../../outside.jar", "sha256": "0" * 64, "size": 1, "mtime_ns": 0, "enabled": True},
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ModHistoryNotFoundError):
        service.history.restore(snapshot_id)
    for bad_id in ("../history", "x" * 10, "20261023T120000Z-ABCDEF12"):
        with pytest.raises(ModHistoryNotFoundError):
            service.history.get_history(bad_id)
    assert not (tmp_path / "outside.jar").exists()


@pytest.mark.asyncio
async def test_restore_endpoint_requires_explicit_confirmation(tmp_path: Path, monkeypatch) -> None:
    service, _ = _service(tmp_path)
    await service.upload_mod(_upload("a.jar", _jar("a", "1")))
    snapshot_id = service.history.list_history()[0]["id"]
    monkeypatch.setattr(endpoints_mods, "mod_service", service)

    with pytest.raises(HTTPException) as refused:
        await endpoints_mods.restore_mod_history(snapshot_id, ModHistoryRestoreRequest())
    assert refused.value.status_code == 400
    assert "a.jar" in _folder(service)

    result = await endpoints_mods.restore_mod_history(snapshot_id, ModHistoryRestoreRequest(confirm=True))
    assert result.undo_id and _folder(service) == {}
    entries = await endpoints_mods.list_mod_history()
    assert entries[0].summary.startswith("Volviste a como estaban tus mods el ")
