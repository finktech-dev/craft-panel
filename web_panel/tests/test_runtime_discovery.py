"""Coverage for the portable, read-only discovery contract."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.core.config import Settings
from app.services.runtime_discovery import RuntimeDiscoveryService


def _settings(tmp_path: Path) -> Settings:
    return Settings(project_root=tmp_path)


def _java_runner(*_args, **_kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["java", "--version"], returncode=0, stdout="openjdk 21.0.8 2025-07-15\n", stderr=""
    )


def test_discovery_is_portable_and_detects_java_neoforge_and_whitelist(tmp_path: Path) -> None:
    configured = _settings(tmp_path)
    assert configured.server_directory is not None
    (configured.server_directory / "libraries/net/neoforged/neoforge").mkdir(parents=True)
    (configured.server_directory / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (configured.server_directory / "server.properties").write_text(
        "online-mode=false\nwhite-list=true\n", encoding="utf-8"
    )

    result = RuntimeDiscoveryService(
        configured,
        system_name="Linux",
        environ={"JAVA_HOME": "/opt/java"},
        which=lambda _: None,
        command_runner=_java_runner,
    ).discover()

    assert result.operating_system == "linux"
    assert result.java.state == "available"
    assert result.java.major_version == 21
    assert result.minecraft.loader == "neoforge"
    assert result.minecraft.start_script.endswith("run.sh")
    assert result.accounts.state == "whitelist"


def test_discovery_never_reads_player_accounts_or_requires_java(tmp_path: Path) -> None:
    configured = _settings(tmp_path)
    assert configured.server_directory is not None
    configured.server_directory.mkdir(parents=True)
    (configured.server_directory / "server.properties").write_text("online-mode=true\n", encoding="utf-8")

    result = RuntimeDiscoveryService(
        configured,
        system_name="Darwin",
        environ={},
        which=lambda _: None,
    ).discover()

    assert result.operating_system == "macos"
    assert result.java.state == "missing"
    assert result.minecraft.state == "not_detected"
    assert result.accounts.state == "online_accounts"


def test_java_version_failure_is_reported_without_a_fallback_process(tmp_path: Path) -> None:
    service = RuntimeDiscoveryService(
        _settings(tmp_path),
        system_name="Windows",
        environ={},
        which=lambda _: r"C:\\Java\\bin\\java.exe",
        command_runner=lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="not a Java runtime"
        ),
    )

    result = service.discover()

    assert result.operating_system == "windows"
    assert result.java.state == "unusable"

def test_java_17_is_detected_for_a_compatible_minecraft_version(tmp_path: Path) -> None:
    configured = _settings(tmp_path)
    configured.minecraft_version = "1.20.4"
    service = RuntimeDiscoveryService(
        configured,
        system_name="Windows",
        environ={},
        which=lambda _: r"C:\Java17\bin\java.exe",
        command_runner=lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="openjdk 17.0.12 2024-07-16\n", stderr=""
        ),
    )

    result = service.discover()

    assert result.java.state == "available"
    assert result.java.major_version == 17
    assert "compatible" in result.java.message

def test_discovery_requires_a_native_import_script(tmp_path: Path) -> None:
    configured = _settings(tmp_path)
    assert configured.server_directory is not None
    configured.server_directory.mkdir(parents=True)
    (configured.server_directory / "run.bat").write_text("@echo off\n", encoding="utf-8")

    result = RuntimeDiscoveryService(
        configured,
        system_name="Linux",
        environ={},
        which=lambda _: None,
    ).discover()

    assert result.minecraft.state == "not_detected"
    assert result.minecraft.start_script is None

def test_discovery_falls_back_when_java_home_is_an_old_runtime(tmp_path: Path) -> None:
    configured = _settings(tmp_path)
    calls: list[tuple[str, ...]] = []

    def runner(args, **_kwargs):
        calls.append(tuple(args))
        if "java8" in args[0].casefold():
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="Unrecognized option: --version")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="openjdk 21.0.12\n", stderr="")

    result = RuntimeDiscoveryService(
        configured,
        system_name="Windows",
        environ={"JAVA_HOME": r"C:\\Java8"},
        which=lambda _: r"C:\\Java21\\bin\\java.exe",
        command_runner=runner,
    ).discover()

    assert result.java.state == "available"
    assert result.java.major_version == 21
    assert any("java8" in call[0].casefold() for call in calls)
    assert any("java21" in call[0].casefold() for call in calls)
