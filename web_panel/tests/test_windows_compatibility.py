"""Regression tests for Windows 10/11 first-run and daily-use behaviour."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.services import installer_service as installer_module
from app.services import java_runtime_service as java_module
from app.services.installer_service import InstallerService
from app.services.java_runtime_service import JavaRuntimeService
from app.services.playit_service import PlayitService
from app.services.runtime_discovery import RuntimeDiscoveryService

REPO_ROOT = Path(__file__).resolve().parents[2]
BATCH_FILES = sorted(REPO_ROOT.glob("*.bat"))


class StoppedServer:
    is_running = False


def _load_start_panel():
    spec = importlib.util.spec_from_file_location("start_panel_under_test", REPO_ROOT / "start_panel.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_batch_launchers_exist() -> None:
    names = {path.name for path in BATCH_FILES}
    assert {"iniciar_panel.bat", "restablecer_contrasena_panel.bat"} <= names


@pytest.mark.parametrize("batch_file", BATCH_FILES, ids=lambda path: path.name)
def test_batch_launchers_are_ascii_with_crlf_line_endings(batch_file: Path) -> None:
    content = batch_file.read_bytes()

    # cmd.exe parses batch files in the OEM code page; non-ASCII prints garbled.
    content.decode("ascii")
    assert not content.startswith(b"\xef\xbb\xbf")
    # LF-only batch files break "call :label" and "goto" in cmd.exe.
    assert content.count(b"\n") == content.count(b"\r\n")


def test_gitattributes_pins_script_line_endings() -> None:
    rules = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").split("\n")

    assert "*.bat text eol=crlf" in rules
    assert "*.sh text eol=lf" in rules


def test_windows_launcher_verifies_python_candidates_by_running_them() -> None:
    source = (REPO_ROOT / "iniciar_panel.bat").read_text(encoding="ascii")

    # The Microsoft Store alias passes "where python" but cannot run code.
    assert "sys.version_info < (3, 11)" in source
    assert "where python" not in source
    # PATH is stale right after a winget install in the same window.
    assert r"%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" in source
    assert "EnableDelayedExpansion" not in source.replace("DisableDelayedExpansion", "")


def test_password_reset_launcher_uses_the_panel_directory() -> None:
    source = (REPO_ROOT / "restablecer_contrasena_panel.bat").read_text(encoding="ascii")

    assert 'cd /d "%~dp0web_panel"' in source
    assert "if not exist \"%PYTHON%\" goto :missing_venv" in source


def test_start_panel_rejects_missing_or_broken_interpreters(tmp_path: Path) -> None:
    start_panel = _load_start_panel()

    assert start_panel.venv_is_usable(tmp_path / "python.exe") is False
    broken = tmp_path / "broken.exe"
    broken.write_bytes(b"not an executable")
    assert start_panel.venv_is_usable(broken) is False
    assert start_panel.venv_is_usable(Path(sys.executable)) is True


def test_start_panel_runs_the_panel_from_the_web_panel_directory(monkeypatch, tmp_path: Path) -> None:
    start_panel = _load_start_panel()
    python = tmp_path / ".venv" / "python"
    python.parent.mkdir()
    python.write_bytes(b"")
    calls: list[tuple[tuple[str, ...], Path | None]] = []
    monkeypatch.setattr(start_panel, "VENV", python.parent)
    monkeypatch.setattr(start_panel, "PYTHON", python)
    monkeypatch.setattr(start_panel, "venv_is_usable", lambda *_args: True)
    monkeypatch.setattr(start_panel, "run", lambda *args, cwd=None: calls.append((args, cwd)))

    assert start_panel.main() == 0

    assert calls[-1] == ((str(python), "run_panel.py"), start_panel.PANEL)


def test_start_panel_recreates_a_broken_venv(monkeypatch, tmp_path: Path) -> None:
    start_panel = _load_start_panel()
    venv = tmp_path / ".venv"
    python = venv / "python"
    venv.mkdir()
    python.write_bytes(b"")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(start_panel, "VENV", venv)
    monkeypatch.setattr(start_panel, "PYTHON", python)
    monkeypatch.setattr(start_panel, "venv_is_usable", lambda *_args: False)
    monkeypatch.setattr(start_panel, "run", lambda *args, cwd=None: calls.append(args))

    assert start_panel.main() == 0

    assert calls[0] == (sys.executable, "-m", "venv", str(venv))


def test_generated_launch_scripts_keep_native_line_endings(tmp_path: Path) -> None:
    configured = Settings(project_root=tmp_path)
    assert configured.server_directory is not None
    configured.server_directory.mkdir(parents=True)
    service = InstallerService(configured_settings=configured, server=StoppedServer())

    service._write_safe_server_files("vanilla")

    run_bat = (configured.server_directory / "run.bat").read_bytes()
    run_sh = (configured.server_directory / "run.sh").read_bytes()
    assert run_bat == b"@echo off\r\njava @user_jvm_args.txt -jar server.jar %*\r\n"
    assert b"\r" not in run_sh


def test_installer_output_falls_back_to_the_windows_ansi_code_page(monkeypatch) -> None:
    monkeypatch.setattr(installer_module.locale, "getpreferredencoding", lambda _do_setlocale=True: "cp1252")

    assert installer_module._decode_process_line("C:\\Users\\José\\server".encode("cp1252")) == "C:\\Users\\José\\server"
    assert installer_module._decode_process_line("ñandú".encode("utf-8")) == "ñandú"


@pytest.mark.parametrize(
    ("os_name", "machine", "expected"),
    [
        ("windows", "AMD64", ("x64",)),
        ("windows", "ARM64", ("aarch64", "x64")),
        ("windows", "x86", ("x32",)),
        ("linux", "aarch64", ("aarch64",)),
        ("mac", "arm64", ("aarch64",)),
    ],
)
def test_java_download_architecture_candidates(os_name: str, machine: str, expected: tuple[str, ...]) -> None:
    assert JavaRuntimeService._architectures(os_name, machine) == expected


@pytest.mark.asyncio
async def test_java_download_falls_back_to_x64_on_windows_arm(monkeypatch) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        architecture = request.url.params["architecture"]
        requested.append(architecture)
        if architecture == "aarch64":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[{"binary": {"package": {"link": "https://github.com/adoptium/jre-x64.zip"}}}])

    original_allowed_client = java_module.allowed_client
    monkeypatch.setattr(java_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(java_module.platform, "machine", lambda: "ARM64")
    monkeypatch.setattr(
        java_module,
        "allowed_client",
        lambda hosts, **kwargs: original_allowed_client(hosts, transport=httpx.MockTransport(handler), **kwargs),
    )

    package = await JavaRuntimeService()._find_package(17)

    assert package == {"link": "https://github.com/adoptium/jre-x64.zip"}
    assert requested[0] == "aarch64"
    assert requested[-1] == "x64"


def test_java_runtime_move_retries_transient_windows_locks(monkeypatch, tmp_path: Path) -> None:
    attempts: list[int] = []
    real_replace = java_module.os.replace

    def flaky_replace(source, target):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError(13, "The process cannot access the file")
        real_replace(source, target)

    source = tmp_path / "staging"
    source.mkdir()
    monkeypatch.setattr(java_module.os, "replace", flaky_replace)
    monkeypatch.setattr(java_module.time, "sleep", lambda _seconds: None)

    JavaRuntimeService._replace_with_retry(source, tmp_path / "java")

    assert len(attempts) == 3
    assert (tmp_path / "java").is_dir()


def test_java_runtime_move_gives_up_after_persistent_locks(monkeypatch, tmp_path: Path) -> None:
    def locked(_source, _target):
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(java_module.os, "replace", locked)
    monkeypatch.setattr(java_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(PermissionError):
        JavaRuntimeService._replace_with_retry(tmp_path / "staging", tmp_path / "java")


def test_java_discovery_tolerates_non_utf8_console_output(tmp_path: Path) -> None:
    received: list[dict[str, object]] = []

    def runner(args, **kwargs):
        received.append(kwargs)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="openjdk 21.0.5\n", stderr="")

    RuntimeDiscoveryService(
        Settings(project_root=tmp_path),
        system_name="Windows",
        environ={},
        which=lambda _: r"C:\Java\bin\java.exe",
        command_runner=runner,
    ).discover()

    assert received and all(kwargs.get("errors") == "replace" for kwargs in received)


def test_playit_service_query_tolerates_localized_sc_output(monkeypatch, tmp_path: Path) -> None:
    received: dict[str, object] = {}

    def fake_run(args, **kwargs):
        received.update(kwargs)
        return subprocess.CompletedProcess(args=args, returncode=1060, stdout="", stderr="")

    monkeypatch.setattr("app.services.playit_service.platform.system", lambda: "Windows")
    monkeypatch.setattr("app.services.playit_service.subprocess.run", fake_run)

    assert PlayitService(configured_settings=Settings(project_root=tmp_path)).uses_external_agent is False
    assert received.get("errors") == "replace"
