"""craftpanel.txt: parsing, round trips, validation and the core values (start script, Java, backups)."""

from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.services import server_settings_file as module
from app.services.server_settings_file import (
    DEFAULT_TEXT,
    GitignoreMatcher,
    KEYS,
    ServerSettingsFile,
    SettingsFileError,
    ValidationContext,
    parse_text,
)

WINDOWS = sys.platform == "win32"
SCRIPT = "start.cmd" if WINDOWS else "start.sh"
CONTEXT = ValidationContext()


def settings_for(tmp_path: Path) -> Settings:
    configured = Settings(project_root=tmp_path)
    assert configured.server_directory is not None
    configured.server_directory.mkdir(parents=True, exist_ok=True)
    return configured


def fake_java(tmp_path: Path) -> Path:
    java = tmp_path / "jdk" / "bin" / ("java.exe" if WINDOWS else "java")
    java.parent.mkdir(parents=True, exist_ok=True)
    java.write_bytes(b"")
    return java


def write_file(configured: Settings, text: str) -> Path:
    path = configured.server_directory / "craftpanel.txt"
    path.write_text(text, encoding="utf-8")
    return path


def rejects(key: str, value: str) -> bool:
    try:
        KEYS[key].parser(value, CONTEXT)
    except ValueError:
        return True
    return False


def rejects_item(section: str, value: str, context: ValidationContext = CONTEXT) -> bool:
    try:
        module.SECTIONS[section].parser(value, context)
    except ValueError:
        return True
    return False


# -- parsing and round trips ---------------------------------------------------


def test_default_text_parses_without_problems() -> None:
    parsed = parse_text(DEFAULT_TEXT)

    assert parsed.problems == ()
    assert parsed.start_script is None and parsed.java is None
    assert parsed.recognize == () and parsed.backup_exclude == ()
    assert parsed.effective("startup_timeout") == 300
    assert parsed.effective("restart_on_crash") is False


def test_every_key_and_section_is_documented_in_the_template() -> None:
    for key in module.KEYS:
        assert f"\n{key} =" in DEFAULT_TEXT, key
    for section in module.SECTIONS:
        assert f"\n[{section}]\n" in DEFAULT_TEXT, section


def test_parses_keys_lists_and_crlf() -> None:
    text = (
        "# comment\r\n"
        f"START_SCRIPT = {SCRIPT}\r\n"
        "[Detect]\r\n"
        "my-server.jar\r\n"
        "# not an item\r\n"
        "[backup-exclude]\r\n"
        "logs/\r\n"
        "*.tmp\r\n"
    )

    parsed = parse_text(text)

    assert parsed.problems == ()
    assert parsed.start_script == SCRIPT
    assert parsed.recognize == ("my-server.jar",)
    assert parsed.backup_exclude == ("logs/", "*.tmp")


def test_unknown_keys_and_sections_survive_a_structured_save(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    original = (
        "# Mine, keep this comment\n"
        "color = green\n"
        "start_script =\n"
        "\n"
        "[future]\n"
        "anything goes = here\n"
        "\n"
        "[detect]\n"
        "# hints below\n"
        "old-hint\n"
        "\n"
        "[backup_exclude]\n"
        "# patterns\n"
    )
    path = write_file(configured, original)

    ServerSettingsFile().save_fields(configured, lists={"detect": ["new-hint", "other-hint"], "backup_exclude": ["logs/"]})

    saved = path.read_text(encoding="utf-8")
    assert "# Mine, keep this comment\ncolor = green\nstart_script =\n" in saved
    assert "[future]\nanything goes = here\n" in saved
    assert "[detect]\n# hints below\nnew-hint\nother-hint\n\n[backup_exclude]\n# patterns\nlogs/\n" in saved
    assert "old-hint" not in saved


def test_only_given_values_change(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    path = write_file(configured, f"start_script   =   {SCRIPT}\njava=\n[detect]\n  spaced-hint  \n")

    ServerSettingsFile().save_fields(configured, values={"server_name": "Friends"})

    saved = path.read_text(encoding="utf-8")
    assert saved.startswith(f"start_script   =   {SCRIPT}\njava=\n")
    assert "server_name = Friends\n" in saved
    assert "\n[detect]\n  spaced-hint  \n" in saved


def test_crlf_files_stay_crlf(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    path = configured.server_directory / "craftpanel.txt"
    path.write_bytes(b"# hi\r\nstart_script =\r\n")

    ServerSettingsFile().save_fields(configured, values={"start_script": SCRIPT})

    data = path.read_bytes()
    assert f"start_script = {SCRIPT}\r\n".encode() in data
    assert b"\n" not in data.replace(b"\r\n", b"")


def test_missing_file_gives_defaults_and_is_not_created(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)

    loaded = ServerSettingsFile().load(configured)

    assert loaded.exists is False
    assert loaded.raw == DEFAULT_TEXT
    assert configured.server_start_script.name == ("run.bat" if WINDOWS else "run.sh")
    assert list(configured.server_directory.iterdir()) == []


def test_first_save_writes_the_documented_template(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)

    ServerSettingsFile().save_fields(configured, lists={"detect": ["my-server"]})

    saved = (configured.server_directory / "craftpanel.txt").read_text(encoding="utf-8")
    assert saved.startswith("# Craft Panel · ajustes de este servidor")
    assert parse_text(saved).recognize == ("my-server",)
    assert not [path for path in configured.server_directory.iterdir() if path.name.endswith(".tmp")]


def test_load_is_cached_until_the_file_changes(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)
    path = write_file(configured, "[detect]\nfirst-hint\n")
    service = ServerSettingsFile()

    assert service.load(configured).recognize == ("first-hint",)
    path.write_text("[detect]\nsecond-hint-longer\n", encoding="utf-8")
    assert service.load(configured).recognize == ("second-hint-longer",)


# -- validation --------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["..\\run.bat", "../run.bat", "sub/run.bat", "run.bat:stream", "con.bat", "my server.bat", "a&calc.bat", "run.exe"],
)
def test_start_script_rejects_traversal_streams_and_odd_names(value: str) -> None:
    assert rejects("start_script", value)


def test_start_script_accepts_plain_names() -> None:
    assert not rejects("start_script", SCRIPT)


def test_java_must_be_an_existing_absolute_java(tmp_path: Path) -> None:
    java = fake_java(tmp_path)
    other = tmp_path / ("notjava.exe" if WINDOWS else "notjava")
    other.write_bytes(b"")

    assert not rejects("java", str(java))
    assert not rejects("java", f'"{java}"')
    assert rejects("java", str(other))
    assert rejects("java", "java.exe")
    assert rejects("java", str(tmp_path / "missing" / "java.exe"))
    assert rejects("java", "\\\\host\\share\\bin\\java.exe")


@pytest.mark.parametrize(
    ("key", "good", "bad"),
    [
        ("start_with_panel", ["true", "FALSE"], ["yes", "1"]),
        ("startup_timeout", ["90s", "5m", "1h"], ["10s", "2h", "5", "5 minutes"]),
        ("restart_warning", ["60s", "2m"], ["5s", "1h"]),
        ("max_crash_restarts", ["1", "3", "20"], ["0", "21", "-1", "x"]),
        ("daily_restart", ["05:30", "23:59", "0:00"], ["24:00", "5.30", "05:60"]),
        ("backup_interval", ["1h", "90m", "2d"], ["30m", "8d"]),
        ("backup_keep", ["1", "100"], ["0", "101"]),
        ("backup_max_size", ["1GB", "512GB", "2TB"], ["512MB", "20000GB", "15"]),
        ("server_name", ["Friends server"], ["x" * 81]),
        ("public_address", ["play.example.com", "play.example.com:25565", "192.0.2.10:25570"], ["bad host", "host:0", "-x.com", "a:b:c"]),
    ],
)
def test_typed_values(key: str, good: list[str], bad: list[str]) -> None:
    for value in good:
        assert not rejects(key, value), value
    for value in bad:
        assert rejects(key, value), value


def test_durations_and_sizes_parse_to_seconds_and_gigabytes() -> None:
    parsed = parse_text("startup_timeout = 10m\nbackup_interval = 2d\nbackup_max_size = 2TB\ndaily_restart = 05:30\n")

    assert parsed.value("startup_timeout") == 600
    assert parsed.value("backup_interval") == 172800
    assert parsed.value("backup_max_size") == 2048
    assert parsed.value("daily_restart") == (5, 30)


@pytest.mark.parametrize("pattern", ["*", "**", "/", "*/", "**/*", "level.dat", "*.dat", "level.*", "region/", "**/region"])
def test_dangerous_exclude_patterns_are_rejected(pattern: str) -> None:
    assert rejects_item("backup_exclude", pattern)


@pytest.mark.parametrize("pattern", ["logs/", "*.tmp", "**/cache/", "data/raids*", "!keep.tmp", "DIM1/data/*.dat"])
def test_reasonable_exclude_patterns_are_accepted(pattern: str) -> None:
    assert not rejects_item("backup_exclude", pattern)


def test_patterns_reject_traversal_and_backslashes() -> None:
    assert rejects_item("backup_exclude", "../outside")
    assert rejects_item("backup_exclude", "logs\\old")


def test_too_many_lines_are_reported_with_their_line_number() -> None:
    text = "[detect]\n" + "".join(f"hint-{index}\n" for index in range(25))

    parsed = parse_text(text)

    assert len(parsed.recognize) == 20
    assert parsed.problems[0].line == 22


def test_short_hints_are_rejected() -> None:
    parsed = parse_text("[detect]\nab\n")

    assert parsed.recognize == ()
    assert parsed.problems[0].line == 2


def test_duplicate_keys_are_reported() -> None:
    parsed = parse_text("backup_keep = 3\nbackup_keep = 5\n")

    assert parsed.problems[0].line == 2
    assert parsed.value("backup_keep") == 3


def test_raw_save_reports_errors_with_line_numbers(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)

    with pytest.raises(SettingsFileError) as error:
        ServerSettingsFile().save_raw(configured, "# ok\nthis is not a setting\n[backup_exclude]\nlogs/\n*\n")

    assert [problem.line for problem in error.value.errors] == [2, 5]
    assert "Línea 2:" in str(error.value) and "Línea 5:" in str(error.value)
    assert not (configured.server_directory / "craftpanel.txt").exists()


def test_structured_save_rejects_bad_values_without_writing(tmp_path: Path) -> None:
    configured = settings_for(tmp_path)

    with pytest.raises(SettingsFileError) as error:
        ServerSettingsFile().save_fields(
            configured,
            values={"start_script": "../evil.bat", "java": "java.exe", "nope": "1"},
            lists={"backup_exclude": ["logs/", "**"]},
        )

    assert {problem.field for problem in error.value.errors} == {"start_script", "java", "nope", "backup_exclude"}
    assert not (configured.server_directory / "craftpanel.txt").exists()


# -- how the values are used ---------------------------------------------------


def test_start_script_override_changes_the_start_command(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.sys.platform", "win32")
    configured = settings_for(tmp_path)
    write_file(configured, "start_script = start.cmd\n")

    assert configured.server_start_script == configured.server_directory / "start.cmd"
    assert configured.server_start_command == ("cmd.exe", "/d", "/s", "/c", "call .\\start.cmd nogui")


def test_invalid_start_script_never_reaches_the_command(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.sys.platform", "win32")
    configured = settings_for(tmp_path)
    write_file(configured, "start_script = a&calc.bat\n")

    assert configured.server_start_command == ("cmd.exe", "/d", "/s", "/c", "call .\\run.bat nogui")
    assert "Revisá craftpanel.txt" in (module.read_server_settings(configured).launch_problem or "")


def test_chosen_java_goes_first_on_path(tmp_path: Path) -> None:
    from app.services.server_process import server_environment

    configured = settings_for(tmp_path)
    java = fake_java(tmp_path)
    write_file(configured, f'java = "{java}"\n')

    environment = server_environment(configured)

    assert environment["PATH"].split(os.pathsep)[0] == str(java.parent)
    assert configured.server_java_executable == java


def test_chosen_java_is_the_one_checked_for_versions(tmp_path: Path) -> None:
    from app.services.runtime_discovery import RuntimeDiscoveryService

    configured = settings_for(tmp_path)
    java = fake_java(tmp_path)
    write_file(configured, f"java = {java}\n")

    service = RuntimeDiscoveryService(configured, environ={"JAVA_HOME": str(tmp_path / "other")}, which=lambda _: "x")

    assert service._java_candidates() == (java,)


@pytest.mark.asyncio
async def test_start_is_refused_when_the_chosen_java_is_missing(tmp_path: Path) -> None:
    from app.services.server_process import MinecraftServerManager, ServerSettingsFileError

    configured = settings_for(tmp_path)
    configured.server_start_script.write_text("echo never runs\n", encoding="utf-8")
    write_file(configured, f"java = {tmp_path / 'gone' / ('java.exe' if WINDOWS else 'java')}\n")
    manager = object.__new__(MinecraftServerManager)
    manager.__init__(configured_settings=configured)

    with pytest.raises(ServerSettingsFileError) as error:
        await manager.start()

    assert "craftpanel.txt" in str(error.value)
    assert not manager.is_running


def test_gitignore_matcher_follows_git_rules() -> None:
    ignore = GitignoreMatcher(["logs/", "*.tmp", "!keep.tmp", "**/cache/", "data/raids*"])

    assert ignore.matches("logs/latest.txt")
    assert ignore.matches("a.tmp")
    assert not ignore.matches("keep.tmp")
    # A file inside an excluded folder cannot be brought back, like in git.
    assert ignore.matches("logs/keep.tmp")
    assert ignore.matches("DIM1/cache/x.bin")
    assert ignore.matches("data/raids.dat")
    assert not ignore.matches("data/other.dat")
    assert not ignore.matches("level.dat")
    # Only folders match a trailing slash.
    assert not GitignoreMatcher(["logs/"]).matches("logs", is_directory=False)


def backup_service_for(configured: Settings, monkeypatch):
    from app.services import server_properties_service as properties_module
    from app.services.backup_service import BackupService

    class _Stopped:
        is_running = False

    monkeypatch.setattr(properties_module.server_properties_service, "read_properties", lambda: {"level-name": "world"})
    return BackupService(configured_settings=configured, manager=_Stopped())


def make_world(configured: Settings) -> Path:
    world = configured.server_directory / "world"
    for relative in [
        "level.dat",
        "region/r.0.0.mca",
        "logs/old.txt",
        "scratch.tmp2",
        "keep.tmp2",
        "DIM1/cache/blob.bin",
        "data/raids.dat",
        "session.lock",
    ]:
        path = world / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"data")
    return world


def test_backup_zip_and_fingerprint_skip_excluded_files(tmp_path: Path, monkeypatch) -> None:
    configured = settings_for(tmp_path)
    world = make_world(configured)
    write_file(configured, "[backup_exclude]\nlogs/\n*.tmp2\n!keep.tmp2\n**/cache/\ndata/raids*\n")
    service = backup_service_for(configured, monkeypatch)
    archive = tmp_path / "copy.zip"

    service._create_archive_sync(archive)

    with zipfile.ZipFile(archive) as contents:
        names = sorted(contents.namelist())
    assert names == ["world/keep.tmp2", "world/level.dat", "world/region/r.0.0.mca"]

    before = service._world_fingerprint_sync()
    (world / "logs" / "old.txt").write_bytes(b"much longer content than before")
    (world / "DIM1" / "cache" / "new.bin").write_bytes(b"new")
    assert service._world_fingerprint_sync() == before
    (world / "region" / "r.0.0.mca").write_bytes(b"changed chunk data")
    assert service._world_fingerprint_sync() != before


def test_backup_without_settings_file_copies_everything_but_locks(tmp_path: Path, monkeypatch) -> None:
    configured = settings_for(tmp_path)
    make_world(configured)
    service = backup_service_for(configured, monkeypatch)
    archive = tmp_path / "copy.zip"

    service._create_archive_sync(archive)

    with zipfile.ZipFile(archive) as contents:
        names = set(contents.namelist())
    assert "world/logs/old.txt" in names and "world/DIM1/cache/blob.bin" in names
    assert "world/session.lock" not in names


# -- API -----------------------------------------------------------------------


class FakeManager:
    def __init__(self, running: bool) -> None:
        self.is_running = running
        self.lifecycle_operation = None
        self.process_pid = None


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    from app.api import endpoints_server_file

    configured = settings_for(tmp_path)
    monkeypatch.setattr(endpoints_server_file, "settings", configured)
    monkeypatch.setattr(endpoints_server_file, "server_settings_file", ServerSettingsFile())
    monkeypatch.setattr(endpoints_server_file, "server_manager", FakeManager(running=False))

    async def no_side_effects() -> None:
        return None

    monkeypatch.setattr(endpoints_server_file, "_after_save", no_side_effects)
    return endpoints_server_file, configured


@pytest.mark.asyncio
async def test_get_returns_defaults_without_creating_the_file(api) -> None:
    endpoints, configured = api

    info = await endpoints.get_settings_file()

    assert info.exists is False
    assert info.raw == DEFAULT_TEXT
    assert info.values["start_script"] == "" and info.values["startup_timeout"] == "5m"
    assert info.lists["detect"] == []
    assert set(info.stopped_only) == {"start_script", "java"}
    assert not (configured.server_directory / "craftpanel.txt").exists()


@pytest.mark.asyncio
async def test_launch_values_cannot_change_while_running(api, monkeypatch) -> None:
    endpoints, configured = api
    monkeypatch.setattr(endpoints, "server_manager", FakeManager(running=True))
    java = fake_java(configured.project_root)

    for values in ({"start_script": SCRIPT}, {"java": str(java)}):
        with pytest.raises(HTTPException) as error:
            await endpoints.update_settings_file(endpoints.SettingsFileUpdate(values=values))
        assert error.value.status_code == 409
        assert "Apagá el servidor para cambiar esto" in error.value.detail

    with pytest.raises(HTTPException) as error:
        await endpoints.update_settings_file_raw(endpoints.SettingsFileRaw(raw=f"start_script = {SCRIPT}\n"))
    assert error.value.status_code == 409

    # Everything else can change at any time.
    info = await endpoints.update_settings_file(
        endpoints.SettingsFileUpdate(values={"server_name": "Friends"}, lists={"detect": ["my-server"], "backup_exclude": ["logs/"]})
    )
    assert info.exists and info.lists["detect"] == ["my-server"] and info.values["server_name"] == "Friends"
    assert info.server_running is True


@pytest.mark.asyncio
async def test_raw_save_errors_carry_line_numbers(api) -> None:
    endpoints, _ = api

    with pytest.raises(HTTPException) as error:
        await endpoints.update_settings_file_raw(endpoints.SettingsFileRaw(raw="[backup_exclude]\n**\n"))

    assert error.value.status_code == 422
    assert error.value.detail["errors"][0]["line"] == 2
    assert error.value.detail["message"].startswith("Línea 2:")


@pytest.mark.asyncio
async def test_raw_save_with_server_off_round_trips(api) -> None:
    endpoints, configured = api
    raw = f"# mine\nstart_script = {SCRIPT}\n[something_else]\nfree text\n"

    info = await endpoints.update_settings_file_raw(endpoints.SettingsFileRaw(raw=raw))

    assert info.values["start_script"] == SCRIPT
    assert (configured.server_directory / "craftpanel.txt").read_text(encoding="utf-8").replace("\r\n", "\n") == raw


@pytest.mark.asyncio
async def test_start_endpoint_refuses_a_broken_settings_file(tmp_path: Path, monkeypatch) -> None:
    from app.api import endpoints_server

    configured = settings_for(tmp_path)
    write_file(configured, "java = nope.exe\n")
    monkeypatch.setattr(endpoints_server, "settings", configured)
    monkeypatch.setattr(endpoints_server, "server_manager", FakeManager(running=False))
    monkeypatch.setattr(endpoints_server, "start_job", lambda *a, **k: pytest.fail("no job may start"))

    with pytest.raises(HTTPException) as error:
        await endpoints_server.start_server()

    assert error.value.status_code == 409
    assert "craftpanel.txt" in error.value.detail


def test_settings_file_endpoints_are_admin_only() -> None:
    from starlette.testclient import TestClient

    from main import app

    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.get("/api/server/settings-file").status_code in {401, 403}
    assert client.put("/api/server/settings-file", json={}).status_code in {401, 403}
