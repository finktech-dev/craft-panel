"""Downloading Java into a folder the user cannot write must fail early and explain why."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.java_runtime_service import JavaRuntimeService, JavaRuntimeValidationError


def test_read_only_panel_folder_is_reported_before_downloading(tmp_path: Path, monkeypatch) -> None:
    service = JavaRuntimeService(Settings(project_root=tmp_path))

    def refuse(self, data):
        raise PermissionError("Access is denied")

    monkeypatch.setattr(Path, "write_bytes", refuse)
    with pytest.raises(JavaRuntimeValidationError) as error:
        service.preflight("1.21.1")
    message = str(error.value)
    assert "Archivos de programa" in message
    assert str(tmp_path) not in message  # never show the computer's paths
    assert error.value.status_code == 422


def test_writable_panel_folder_passes_and_leaves_no_trace(tmp_path: Path) -> None:
    configured = Settings(project_root=tmp_path)
    JavaRuntimeService(configured).preflight("1.21.1")
    assert configured.tools_directory is not None
    assert list(configured.tools_directory.iterdir()) == []


def test_broken_java_folder_is_set_aside_instead_of_asking_to_delete_it(tmp_path: Path) -> None:
    configured = Settings(project_root=tmp_path)
    assert configured.tools_directory is not None
    broken = configured.tools_directory / "java"
    (broken / "bin").mkdir(parents=True)
    (broken / "bin" / "leftover.txt").write_text("x", encoding="utf-8")

    JavaRuntimeService(configured).preflight("1.21.1")  # no longer refuses
    JavaRuntimeService._set_aside_broken(broken)

    assert not broken.exists()
    assert (configured.tools_directory / "java.bak" / "bin" / "leftover.txt").is_file()
