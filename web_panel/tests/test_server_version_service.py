"""Offline detection of the installed server, using fake directory trees."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.server_version_service import (
    ServerVersionInfo,
    ServerVersionService,
    data_pack_metadata,
    neoforge_to_minecraft,
)


def _service(tmp_path: Path, **overrides) -> tuple[ServerVersionService, Path]:
    configured = Settings(project_root=tmp_path, **overrides)
    assert configured.server_directory is not None
    configured.server_directory.mkdir(parents=True, exist_ok=True)
    return ServerVersionService(configured), configured.server_directory


def _jar(path: Path, entries: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


@pytest.mark.parametrize(
    ("neoforge", "minecraft"),
    [
        ("21.1.250", "1.21.1"),
        ("21.0.167", "1.21"),
        ("20.4.237", "1.20.4"),
        ("20.2.86-beta", "1.20.2"),
        ("21.11.48", "1.21.11"),
        ("26.1.0.12", "26.1"),
        ("26.1.2.120", "26.1.2"),
        ("26.3.0.75-beta", "26.3"),
    ],
)
def test_neoforge_versions_map_to_their_minecraft_release(neoforge: str, minecraft: str) -> None:
    assert neoforge_to_minecraft(neoforge) == minecraft


def test_unrecognized_neoforge_versions_are_not_guessed() -> None:
    assert neoforge_to_minecraft("47.1.3") is None
    assert neoforge_to_minecraft("garbage") is None


def test_empty_server_directory_is_unknown(tmp_path: Path) -> None:
    service, _root = _service(tmp_path)

    info = service.detect()

    assert info == ServerVersionInfo()
    assert info.loader == "unknown"
    assert info.label is None
    assert not info.is_installed


def test_missing_server_directory_is_unknown(tmp_path: Path) -> None:
    configured = Settings(project_root=tmp_path)
    assert ServerVersionService(configured).detect().loader == "unknown"


def test_neoforge_is_detected_from_libraries(tmp_path: Path) -> None:
    service, root = _service(tmp_path)
    (root / "libraries/net/neoforged/neoforge/21.1.9").mkdir(parents=True)
    (root / "libraries/net/neoforged/neoforge/21.1.250").mkdir(parents=True)

    info = service.detect()

    assert (info.loader, info.loader_version, info.minecraft_version) == ("neoforge", "21.1.250", "1.21.1")
    assert info.label == "Minecraft 1.21.1 con NeoForge 21.1.250"


def test_neoforge_start_script_picks_the_build_in_use(tmp_path: Path) -> None:
    service, root = _service(tmp_path)
    (root / "libraries/net/neoforged/neoforge/21.1.200").mkdir(parents=True)
    (root / "libraries/net/neoforged/neoforge/21.1.250").mkdir(parents=True)
    (root / "run.sh").write_text(
        "java @user_jvm_args.txt @libraries/net/neoforged/neoforge/21.1.200/unix_args.txt \"$@\"\n",
        encoding="utf-8",
    )

    info = service.detect()

    assert info.loader_version == "21.1.200"
    assert info.source == "start-script"


def test_new_neoforge_scheme_is_detected(tmp_path: Path) -> None:
    service, root = _service(tmp_path)
    (root / "libraries/net/neoforged/neoforge/26.1.2.120").mkdir(parents=True)

    info = service.detect()

    assert (info.loader, info.minecraft_version) == ("neoforge", "26.1.2")


def test_forge_is_detected_from_libraries_and_windows_script(tmp_path: Path) -> None:
    service, root = _service(tmp_path)
    (root / "libraries/net/minecraftforge/forge/1.20.1-47.3.0").mkdir(parents=True)
    (root / "run.bat").write_text(
        "java @user_jvm_args.txt @libraries\\net\\minecraftforge\\forge\\1.20.1-47.3.0\\win_args.txt %*\r\n",
        encoding="utf-8",
    )

    info = service.detect()

    assert (info.loader, info.loader_version, info.minecraft_version) == ("forge", "47.3.0", "1.20.1")
    assert info.label == "Minecraft 1.20.1 con Forge 47.3.0"


def test_legacy_forge_root_jar_is_detected(tmp_path: Path) -> None:
    service, root = _service(tmp_path)
    (root / "forge-1.16.5-36.2.39.jar").write_bytes(b"jar")

    info = service.detect()

    assert (info.loader, info.loader_version, info.minecraft_version) == ("forge", "36.2.39", "1.16.5")


def test_fabric_is_detected_from_libraries(tmp_path: Path) -> None:
    service, root = _service(tmp_path)
    (root / "fabric-server-launch.jar").write_bytes(b"jar")
    (root / "libraries/net/fabricmc/fabric-loader/0.16.5").mkdir(parents=True)
    (root / "libraries/net/fabricmc/intermediary/1.21.1").mkdir(parents=True)

    info = service.detect()

    assert (info.loader, info.loader_version, info.minecraft_version) == ("fabric", "0.16.5", "1.21.1")


def test_fabric_launcher_jar_name_carries_both_versions(tmp_path: Path) -> None:
    service, root = _service(tmp_path)
    (root / "fabric-server-mc.1.20.4-loader.0.15.11-launcher.1.0.1.jar").write_bytes(b"jar")

    info = service.detect()

    assert (info.loader, info.loader_version, info.minecraft_version) == ("fabric", "0.15.11", "1.20.4")


def test_fabric_without_intermediary_reads_the_vanilla_jar(tmp_path: Path) -> None:
    service, root = _service(tmp_path)
    (root / "fabric-server-launcher.properties").write_text("serverJarPath=server.jar\n", encoding="utf-8")
    _jar(root / "server.jar", {"version.json": json.dumps({"id": "26.1", "name": "26.1"})})

    info = service.detect()

    assert (info.loader, info.minecraft_version) == ("fabric", "26.1")
    assert info.label == "Minecraft 26.1 con Fabric"


def test_fabric_remapped_jars_folder_is_used(tmp_path: Path) -> None:
    service, root = _service(tmp_path)
    (root / ".fabric/remappedJars/minecraft-1.21.4-0.16.10").mkdir(parents=True)

    info = service.detect()

    assert (info.loader, info.loader_version, info.minecraft_version) == ("fabric", "0.16.10", "1.21.4")


def test_quilt_is_detected(tmp_path: Path) -> None:
    service, root = _service(tmp_path)
    (root / "quilt-server-launch.jar").write_bytes(b"jar")
    (root / "libraries/org/quiltmc/quilt-loader/0.26.4").mkdir(parents=True)
    (root / "versions/1.21.1").mkdir(parents=True)
    (root / "versions/1.21.1/server-1.21.1.jar").write_bytes(b"jar")

    info = service.detect()

    assert (info.loader, info.loader_version, info.minecraft_version) == ("quilt", "0.26.4", "1.21.1")


def test_vanilla_version_json_is_read(tmp_path: Path) -> None:
    service, root = _service(tmp_path)
    _jar(root / "server.jar", {"version.json": json.dumps({"id": "1.20.4", "java_version": 17})})

    info = service.detect()

    assert (info.loader, info.minecraft_version) == ("vanilla", "1.20.4")
    assert info.label == "Minecraft 1.20.4"


def test_vanilla_bundler_versions_list_is_read(tmp_path: Path) -> None:
    service, root = _service(tmp_path)
    _jar(root / "server.jar", {"META-INF/versions.list": "abc123\t1.21.1\t1.21.1/server-1.21.1.jar\n"})

    assert service.detect().minecraft_version == "1.21.1"


def test_vanilla_extracted_versions_folder_is_read(tmp_path: Path) -> None:
    service, root = _service(tmp_path)
    (root / "server.jar").write_bytes(b"not a zip")
    (root / "versions/1.21.4").mkdir(parents=True)
    (root / "versions/1.21.4/server-1.21.4.jar").write_bytes(b"jar")

    info = service.detect()

    assert (info.loader, info.minecraft_version) == ("vanilla", "1.21.4")


def test_unreadable_vanilla_jar_reports_loader_without_version(tmp_path: Path) -> None:
    service, root = _service(tmp_path)
    (root / "server.jar").write_bytes(b"not a zip")

    info = service.detect()

    assert (info.loader, info.minecraft_version) == ("vanilla", None)
    assert info.label is None


def test_config_override_wins_over_detection(tmp_path: Path) -> None:
    service, root = _service(tmp_path, minecraft_version="1.21.4", neoforge_version="21.4.1")
    (root / "libraries/net/neoforged/neoforge/21.1.250").mkdir(parents=True)

    info = service.detect()

    assert (info.minecraft_version, info.loader_version) == ("1.21.4", "21.4.1")


def test_detection_is_cached_until_the_tree_changes(tmp_path: Path, monkeypatch) -> None:
    service, root = _service(tmp_path)
    calls: list[Path] = []
    original = service._detect

    def counting(path: Path) -> ServerVersionInfo:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(service, "_detect", counting)
    service.detect()
    service.detect()
    assert len(calls) == 1

    (root / "libraries/net/neoforged/neoforge/21.1.250").mkdir(parents=True)
    assert service.detect().loader == "neoforge"
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("minecraft", "expected"),
    [
        ("1.16.5", {"pack_format": 6}),
        ("1.20.4", {"pack_format": 26}),
        ("1.21", {"pack_format": 48}),
        ("1.21.1", {"pack_format": 48}),
        ("1.21.4", {"pack_format": 61}),
    ],
)
def test_data_pack_format_follows_the_minecraft_version(minecraft: str, expected: dict[str, int]) -> None:
    assert data_pack_metadata(minecraft) == expected


@pytest.mark.parametrize("minecraft", ["1.21.10", "26.1", "26.3", None])
def test_newer_or_unknown_versions_get_an_open_format_range(minecraft: str | None) -> None:
    metadata = data_pack_metadata(minecraft)
    assert metadata["min_format"] <= metadata["max_format"]
    assert "pack_format" in metadata
