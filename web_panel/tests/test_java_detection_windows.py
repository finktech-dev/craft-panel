"""Java detection on Windows 10/11 with fakes for the registry, the disk and ``java -version``."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services import server_process
from app.services.runtime_discovery import RuntimeDiscoveryService, describe_java, java_vendor

# Real ``java -version`` output (it goes to stderr), one per vendor.
ADOPTIUM_21 = (
    'openjdk version "21.0.4" 2024-07-16 LTS\n'
    "OpenJDK Runtime Environment Temurin-21.0.4+7 (build 21.0.4+7-LTS)\n"
    "OpenJDK 64-Bit Server VM Temurin-21.0.4+7 (build 21.0.4+7-LTS, mixed mode, sharing)\n"
)
ADOPTIUM_17 = (
    'openjdk version "17.0.12" 2024-07-16\n'
    "OpenJDK Runtime Environment Temurin-17.0.12+7 (build 17.0.12+7)\n"
    "OpenJDK 64-Bit Server VM Temurin-17.0.12+7 (build 17.0.12+7, mixed mode, sharing)\n"
)
MICROSOFT_21 = (
    'openjdk version "21.0.3" 2024-04-16 LTS\n'
    "OpenJDK Runtime Environment Microsoft-9388422 (build 21.0.3+9-LTS)\n"
    "OpenJDK 64-Bit Server VM Microsoft-9388422 (build 21.0.3+9-LTS, mixed mode, sharing)\n"
)
ZULU_17 = (
    'openjdk version "17.0.10" 2024-01-16 LTS\n'
    "OpenJDK Runtime Environment Zulu17.48+15-CA (build 17.0.10+7-LTS)\n"
    "OpenJDK 64-Bit Server VM Zulu17.48+15-CA (build 17.0.10+7-LTS, mixed mode, sharing)\n"
)
ORACLE_8 = (
    'java version "1.8.0_421"\n'
    "Java(TM) SE Runtime Environment (build 1.8.0_421-b09)\n"
    "Java HotSpot(TM) 64-Bit Server VM (build 25.421-b09, mixed mode)\n"
)
# The Minecraft Launcher bundles Microsoft's build of OpenJDK ("java-runtime-delta").
MINECRAFT_RUNTIME_21 = MICROSOFT_21
FAKE_USER = "PlayerOne"


class FakeRegistry:
    """Just enough of ``winreg`` for HKLM reads: keys are backslash paths, values a dict."""

    HKEY_LOCAL_MACHINE = "HKLM"
    KEY_READ = 0x20019
    KEY_WOW64_64KEY = 0x0100

    def __init__(self, values: dict[str, dict[str, str]]) -> None:
        self._values = {key.casefold(): value for key, value in values.items()}
        self._keys: dict[str, set[str]] = {}
        for key in values:
            parts = key.split("\\")
            for depth in range(1, len(parts) + 1):
                parent = "\\".join(parts[:depth]).casefold()
                children = self._keys.setdefault(parent, set())
                if depth < len(parts):
                    children.add(parts[depth])
        self.opened: list[str] = []

    def OpenKey(self, root, path, reserved=0, access=0):  # noqa: N802 - winreg API
        assert root == self.HKEY_LOCAL_MACHINE and access & self.KEY_READ
        if path.casefold() not in self._keys:
            raise FileNotFoundError(path)
        self.opened.append(path)
        return path

    def EnumKey(self, key, index):  # noqa: N802
        children = sorted(self._keys[key.casefold()])
        if index >= len(children):
            raise OSError("no more keys")
        return children[index]

    def QueryValueEx(self, key, name):  # noqa: N802
        try:
            return self._values[key.casefold()][name], 1
        except KeyError:
            raise FileNotFoundError(name) from None

    def CloseKey(self, key):  # noqa: N802
        pass


def _java(folder: Path) -> Path:
    executable = folder / "bin" / "java.exe"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"MZ")
    return executable


class Runner:
    """Answers ``java -version`` by path and records the calls."""

    def __init__(self, outputs: dict[Path, str]) -> None:
        self._outputs = {str(path): text for path, text in outputs.items()}
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        assert args[1] == "-version"
        output = self._outputs.get(args[0])
        if output is None:
            raise FileNotFoundError(args[0])
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr=output)


@pytest.fixture
def host(tmp_path: Path):
    """A fake Windows profile: Program Files folders and LOCALAPPDATA under tmp_path."""
    root = tmp_path / "host"
    environ = {
        "ProgramFiles": str(root / "Program Files"),
        "ProgramW6432": str(root / "Program Files"),
        "ProgramFiles(x86)": str(root / "Program Files (x86)"),
        "LOCALAPPDATA": str(root / "Users" / FAKE_USER / "AppData" / "Local"),
    }
    configured = Settings(project_root=tmp_path / "panel")
    return configured, environ, root


def _service(configured, environ, runner, registry=None, which=lambda _name: None):
    return RuntimeDiscoveryService(
        configured, system_name="Windows", environ=environ, which=which, command_runner=runner, registry=registry
    )


def test_lowest_compatible_java_wins_across_every_place(host) -> None:
    configured, environ, root = host
    assert configured.tools_directory is not None
    tools = _java(configured.tools_directory / "java")
    adoptium_home = root / "Program Files" / "Eclipse Adoptium" / "jdk-17.0.12.7-hotspot"
    adoptium = _java(adoptium_home)
    microsoft = _java(root / "Program Files" / "Microsoft" / "jdk-21.0.3.9-hotspot")
    registry = FakeRegistry(
        {r"SOFTWARE\Eclipse Adoptium\JDK\17.0.12.7\hotspot\MSI": {"Path": str(adoptium_home) + "\\"}}
    )
    runner = Runner({tools: ADOPTIUM_21, adoptium: ADOPTIUM_17, microsoft: MICROSOFT_21})

    status = _service(configured, environ, runner, registry).java_status("1.20.4")

    assert status.state == "available"
    assert status.major_version == 17 and status.vendor == "Adoptium" and status.source == "system"
    assert Path(status.executable) == adoptium
    assert status.message == "Encontramos Java 17 de Adoptium en tu computadora. Sirve para Minecraft 1.20.4."
    # Each Java was really run, once, without a console window flashing.
    probed = [call[0][0] for call in runner.calls]
    assert len(probed) == len(set(probed)) == 3
    assert all(call[1].get("errors") == "replace" for call in runner.calls)
    assert all("creationflags" in call[1] for call in runner.calls) or not hasattr(subprocess, "CREATE_NO_WINDOW")


def test_tools_java_wins_a_tie_because_it_is_checked_first(host) -> None:
    configured, environ, root = host
    assert configured.tools_directory is not None
    tools = _java(configured.tools_directory / "java")
    microsoft = _java(root / "Program Files" / "Microsoft" / "jdk-21.0.3.9-hotspot")
    runner = Runner({tools: ADOPTIUM_21, microsoft: MICROSOFT_21})

    status = _service(configured, environ, runner).java_status("1.21.1")

    assert status.source == "tools/java"
    assert status.message == "Encontramos Java 21 de Adoptium en la carpeta tools/java del panel. Sirve para Minecraft 1.21.1."


def test_order_is_tools_java_home_path_registry_folders_launcher(host) -> None:
    configured, environ, root = host
    assert configured.tools_directory is not None
    tools = _java(configured.tools_directory / "java")
    java_home = _java(root / "jdks" / "home")
    on_path = _java(root / "jdks" / "path")
    registry_home = root / "jdks" / "registry"
    from_registry = _java(registry_home)
    folder = _java(root / "Program Files" / "Zulu" / "zulu-17")
    launcher = _java(
        Path(environ["LOCALAPPDATA"]) / "Packages" / "Microsoft.4297127D64EC6_8wekyb3d8bbwe" / "LocalCache" / "Local"
        / "runtime" / "java-runtime-delta" / "windows-x64" / "java-runtime-delta"
    )
    environ["JAVA_HOME"] = str(java_home.parents[1])
    registry = FakeRegistry({r"SOFTWARE\WOW6432Node\JavaSoft\JDK\17": {"JavaHome": str(registry_home)}})
    service = _service(configured, environ, Runner({}), registry, which=lambda _name: str(on_path))

    candidates = service._java_candidates()

    assert [candidate.path for candidate in candidates] == [tools, java_home, on_path, from_registry, folder, launcher]
    assert [candidate.source for candidate in candidates] == ["tools/java", "system", "system", "system", "system", "minecraft_launcher"]


def test_minecraft_launcher_runtime_is_used_when_nothing_else_exists(host) -> None:
    configured, environ, root = host
    store = _java(
        Path(environ["LOCALAPPDATA"]) / "Packages" / "Microsoft.4297127D64EC6_8wekyb3d8bbwe" / "LocalCache" / "Local"
        / "runtime" / "java-runtime-delta" / "windows-x64" / "java-runtime-delta"
    )
    classic = _java(
        root / "Program Files (x86)" / "Minecraft Launcher" / "runtime" / "jre-legacy" / "windows-x64" / "jre-legacy"
    )

    status = _service(configured, environ, Runner({store: MINECRAFT_RUNTIME_21, classic: ORACLE_8})).java_status("1.21.1")

    assert status.state == "available" and status.source == "minecraft_launcher"
    assert Path(status.executable) == store
    assert status.message == (
        "Encontramos Java 21 de Microsoft, el que trae el launcher de Minecraft. Sirve para Minecraft 1.21.1."
    )


def test_old_oracle_java_from_the_registry_serves_old_minecraft(host) -> None:
    configured, environ, root = host
    home = root / "Program Files" / "Java" / "jre1.8.0_421"
    java = _java(home)
    registry = FakeRegistry({r"SOFTWARE\JavaSoft\Java Runtime Environment\1.8": {"JavaHome": str(home)}})

    old = _service(configured, environ, Runner({java: ORACLE_8}), registry).java_status("1.16.5")
    new = _service(configured, environ, Runner({java: ORACLE_8}), registry).java_status("1.21.1")

    assert old.state == "available" and old.major_version == 8 and old.vendor == "Oracle"
    assert old.message == "Encontramos Java 8 de Oracle en tu computadora. Sirve para Minecraft 1.16.5."
    assert new.state == "unusable"
    assert new.message == "Encontramos Java 8 de Oracle en tu computadora, pero Minecraft 1.21.1 necesita Java 21 o más nuevo."


def test_azul_zulu_in_its_default_folder_is_found(host) -> None:
    configured, environ, root = host
    zulu = _java(root / "Program Files" / "Zulu" / "zulu-17")

    status = _service(configured, environ, Runner({zulu: ZULU_17})).java_status("1.20.1")

    assert status.state == "available" and status.vendor == "Azul Zulu"


def test_with_no_version_picked_yet_the_newest_java_is_reported(host) -> None:
    configured, environ, root = host
    old = _java(root / "Program Files" / "Zulu" / "zulu-17")
    new = _java(root / "Program Files" / "Microsoft" / "jdk-21.0.3.9-hotspot")

    status = _service(configured, environ, Runner({old: ZULU_17, new: MICROSOFT_21})).java_status(None)

    assert status.major_version == 21
    assert status.message == "Encontramos Java 21 de Microsoft en tu computadora."


def test_no_java_anywhere_offers_the_download(host) -> None:
    configured, environ, _root = host

    status = _service(configured, environ, Runner({}), FakeRegistry({})).java_status("1.21.1")

    assert status.state == "missing"
    assert "Descargar Java" in status.message


def test_java_chosen_in_craftpanel_txt_is_the_only_one_checked(host) -> None:
    configured, environ, root = host
    assert configured.server_directory is not None
    chosen = _java(root / "custom" / "jdk")
    other = _java(root / "Program Files" / "Microsoft" / "jdk-21.0.3.9-hotspot")
    configured.server_directory.mkdir(parents=True, exist_ok=True)
    (configured.server_directory / "craftpanel.txt").write_text(f"java = {chosen}\n", encoding="utf-8")
    runner = Runner({chosen: ADOPTIUM_17, other: MICROSOFT_21})

    status = _service(configured, environ, runner).java_status("1.20.4")

    assert status.source == "craftpanel.txt"
    assert [call[0][0] for call in runner.calls] == [str(chosen)]


@pytest.mark.parametrize(
    ("output", "vendor"),
    [
        (ADOPTIUM_21, "Adoptium"),
        (MICROSOFT_21, "Microsoft"),
        (ZULU_17, "Azul Zulu"),
        (ORACLE_8, "Oracle"),
        ("Picked up JAVA_TOOL_OPTIONS: -Dfile.encoding=UTF-8\n" + ADOPTIUM_17, "Adoptium"),
        ('openjdk version "21.0.2" 2024-01-16\nOpenJDK Runtime Environment (build 21.0.2+13-58)\n', None),
    ],
)
def test_vendor_and_version_come_from_java_version_output(output: str, vendor: str | None) -> None:
    assert java_vendor(output) == vendor
    assert RuntimeDiscoveryService._parse_java_version(output) is not None


def test_description_never_contains_a_path() -> None:
    assert describe_java(21, "Adoptium", "system") == "Encontramos Java 21 de Adoptium en tu computadora."
    assert describe_java(17, None, "craftpanel.txt") == "Encontramos Java 17, el que elegiste en craftpanel.txt."


def test_discovery_response_has_no_paths_or_user_names(host) -> None:
    configured, environ, root = host
    assert configured.server_directory is not None
    store = _java(
        Path(environ["LOCALAPPDATA"]) / "Packages" / "Microsoft.4297127D64EC6_8wekyb3d8bbwe" / "LocalCache" / "Local"
        / "runtime" / "java-runtime-delta" / "windows-x64" / "java-runtime-delta"
    )
    (configured.server_directory / "run.bat").parent.mkdir(parents=True, exist_ok=True)
    (configured.server_directory / "run.bat").write_text("@echo off\r\n", encoding="utf-8")
    (configured.server_directory / "server.jar").write_bytes(b"")

    result = _service(configured, environ, Runner({store: MINECRAFT_RUNTIME_21})).discover("1.21.1")
    body = result.model_dump_json()

    assert result.java.state == "available" and result.minecraft.start_script_name == "run.bat"
    assert FAKE_USER not in body and str(root) not in body and str(configured.project_root) not in body
    assert ":\\\\" not in body and "executable" not in body and '"root"' not in body


def test_server_runs_with_the_detected_java_even_when_it_is_not_on_path(host, monkeypatch) -> None:
    configured, environ, root = host
    java = _java(root / "Program Files" / "Eclipse Adoptium" / "jdk-21.0.4.7-hotspot")
    original = RuntimeDiscoveryService.__init__

    def patched(self, settings_arg, **_kwargs):
        original(self, settings_arg, system_name="Windows", environ=environ, which=lambda _n: None,
                 command_runner=Runner({java: ADOPTIUM_21}), registry=FakeRegistry({}))

    monkeypatch.setattr(RuntimeDiscoveryService, "__init__", patched)
    monkeypatch.setenv("PATH", "C:\\Windows")

    environment = server_process.server_environment(configured)

    assert environment["PATH"].split(";")[0] == str(java.parent)
