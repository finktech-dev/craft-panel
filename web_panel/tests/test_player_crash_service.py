"""Pruebas unitarias para el motor de análisis y clasificación de crashes y desconexiones."""

from __future__ import annotations

import pytest
from app.services.player_crash_service import PlayerCrashService, player_crash_service


@pytest.fixture
def service() -> PlayerCrashService:
    return PlayerCrashService()


def test_normal_disconnect_voluntary_leave(service: PlayerCrashService):
    lines = [
        "[22Sep2026 20:00:00.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: Disconnected",
    ]
    events = service._parse_lines(lines, "latest.log")
    assert len(events) == 1
    evt = events[0]
    assert evt.player == "SamplePlayer"
    assert evt.category == "NORMAL_DISCONNECT"
    assert evt.category_label == "Desconexión Normal"
    assert evt.severity == "info"
    assert evt.suspected_mod is None
    assert evt.suggestion is None


def test_normal_disconnect_quitting_and_left_the_game(service: PlayerCrashService):
    lines = [
        "[22Sep2026 20:01:00.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: ExamplePlayer lost connection: Quitting",
        "[22Sep2026 20:02:00.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: steve lost connection: left the game",
    ]
    events = service._parse_lines(lines, "latest.log")
    assert len(events) == 2
    for evt in events:
        assert evt.category == "NORMAL_DISCONNECT"
        assert evt.severity == "info"
        assert evt.suspected_mod is None


def test_normal_disconnect_never_classified_as_timeout_by_lag_warning(service: PlayerCrashService):
    lines = [
        "[22Sep2026 19:59:50.000] [Server thread/WARN] [minecraft/MinecraftServer]: Can't keep up! Is the server overloaded? Running 2500ms or 50 ticks behind",
        "[22Sep2026 20:00:00.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: Disconnected",
    ]
    events = service._parse_lines(lines, "latest.log")
    assert len(events) == 1
    evt = events[0]
    assert evt.category == "NORMAL_DISCONNECT"
    assert evt.severity == "info"
    assert evt.suspected_mod is None


def test_voicechat_disconnect_pattern_ignored(service: PlayerCrashService):
    lines = [
        "[22Sep2026 20:00:00.000] [VoiceChatServerThread/INFO] [voicechat]: Disconnecting client SamplePlayer",
        "[22Sep2026 20:00:00.100] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: Disconnected",
    ]
    events = service._parse_lines(lines, "latest.log")
    # VoiceChat line must not generate an extra event
    assert len(events) == 1
    assert events[0].player == "SamplePlayer"
    assert events[0].category == "NORMAL_DISCONNECT"


def test_team_creation_does_not_flag_create(service: PlayerCrashService):
    # Case 1: voluntary disconnect with team creation in context
    lines_voluntary = [
        "[22Sep2026 20:00:00.000] [Server thread/INFO] [minecraft/DedicatedServer]: [ExamplePlayer: Created team [ExampleTeam]]",
        "[22Sep2026 20:00:05.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: Disconnected",
    ]
    events_v = service._parse_lines(lines_voluntary, "latest.log")
    assert len(events_v) == 1
    assert events_v[0].suspected_mod is None
    assert events_v[0].category == "NORMAL_DISCONNECT"

    # Case 2: non-voluntary disconnect (e.g. timeout) with team creation in context
    lines_timeout = [
        "[22Sep2026 20:00:00.000] [Server thread/INFO] [minecraft/DedicatedServer]: [ExamplePlayer: Created team [ExampleTeam]]",
        "[22Sep2026 20:00:05.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: Timed out",
    ]
    events_t = service._parse_lines(lines_timeout, "latest.log")
    assert len(events_t) == 1
    assert events_t[0].suspected_mod is None
    assert events_t[0].category == "TIMEOUT"


def test_shutdown_process_does_not_flag_luckperms(service: PlayerCrashService):
    lines = [
        "[22Sep2026 20:00:00.000] [Server thread/INFO] [minecraft/MinecraftServer]: Stopping the server",
        "[22Sep2026 20:00:01.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: Server closed",
        "[22Sep2026 20:00:02.000] [Server thread/INFO] [luckperms/]: Starting shutdown process...",
        "[22Sep2026 20:00:03.000] [Server thread/INFO] [luckperms/]: Closing storage...",
        "[22Sep2026 20:00:04.000] [Server thread/INFO] [minecraft/MinecraftServer]: Goodbye!",
    ]
    events = service._parse_lines(lines, "latest.log")
    assert len(events) == 1
    evt = events[0]
    assert evt.suspected_mod is None
    assert evt.category == "NORMAL_DISCONNECT"


def test_real_crash_with_stacktrace_identifies_create(service: PlayerCrashService):
    lines = [
        "[22Sep2026 20:00:00.000] [Server thread/ERROR] [minecraft/MinecraftServer]: Encountered an unexpected exception",
        "java.lang.NullPointerException: Cannot invoke method on contraption",
        "\tat com.simibubi.create.content.contraptions.Contraption.tick(Contraption.java:45)",
        "\tat net.minecraft.world.level.Level.tick(Level.java:120)",
        "[22Sep2026 20:00:01.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: Internal Exception: java.lang.NullPointerException",
    ]
    events = service._parse_lines(lines, "latest.log")
    assert len(events) == 1
    evt = events[0]
    assert evt.category == "MOD_ERROR"
    assert evt.severity == "error"
    assert evt.suspected_mod == "Create"
    assert evt.suggestion is not None
    assert "Create" in evt.suggestion


def test_real_crash_with_stacktrace_identifies_pointblank(service: PlayerCrashService):
    lines = [
        "[22Sep2026 20:00:00.000] [Server thread/ERROR] [minecraft/MinecraftServer]: Encountered an unexpected exception",
        "java.lang.IllegalStateException: Gun fire failed",
        "\tat com.vicmatskiv.pointblank.weapon.WeaponItem.use(WeaponItem.java:88)",
        "[22Sep2026 20:00:01.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: Internal Exception: java.lang.IllegalStateException",
    ]
    events = service._parse_lines(lines, "latest.log")
    assert len(events) == 1
    evt = events[0]
    assert evt.category == "MOD_ERROR"
    assert evt.severity == "error"
    assert evt.suspected_mod == "Point Blank"


def test_real_crash_with_stacktrace_identifies_balm(service: PlayerCrashService):
    lines = [
        "[22Sep2026 20:00:00.000] [Server thread/ERROR] [minecraft/MinecraftServer]: Encountered an unexpected exception",
        "java.lang.NullPointerException: Balm capability error",
        "\tat net.blay09.mods.balm.api.Balm.getHooks(Balm.java:30)",
        "[22Sep2026 20:00:01.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: Internal Exception: java.lang.NullPointerException",
    ]
    events = service._parse_lines(lines, "latest.log")
    assert len(events) == 1
    evt = events[0]
    assert evt.category == "MOD_ERROR"
    assert evt.severity == "error"
    assert evt.suspected_mod == "Balm"


def test_real_crash_with_custom_jar_in_stacktrace(service: PlayerCrashService):
    lines = [
        "[22Sep2026 20:00:00.000] [Server thread/ERROR] [minecraft/MinecraftServer]: Encountered an unexpected exception",
        "java.lang.NullPointerException: Chest tick failed",
        "\tat net.ironchest.IronChests.tick(IronChests.java:45) ~[ironchest-1.20.1-14.4.4.jar:14.4.4]",
        "[22Sep2026 20:00:01.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: Internal Exception: java.lang.NullPointerException",
    ]
    events = service._parse_lines(lines, "latest.log")
    assert len(events) == 1
    evt = events[0]
    assert evt.category == "MOD_ERROR"
    assert evt.suspected_mod == "ironchest-1.20.1-14.4.4"


def test_timeout_reasons(service: PlayerCrashService):
    test_cases = [
        "Timed out",
        "Read timed out",
        "Connection reset",
        "Internal Exception: java.net.SocketTimeoutException: Read timed out",
        "Internal Exception: java.io.IOException: Connection reset by peer",
    ]
    for reason in test_cases:
        lines = [f"[22Sep2026 20:00:00.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: {reason}"]
        events = service._parse_lines(lines, "latest.log")
        assert len(events) == 1, f"Failed for reason: {reason}"
        assert events[0].category == "TIMEOUT", f"Failed for reason: {reason}"
        assert events[0].severity == "warning"
        assert events[0].suspected_mod is None


def test_kicked_and_banned_reasons(service: PlayerCrashService):
    test_cases = [
        "Kicked by an operator",
        "Kicked: Flying is not enabled on this server",
        "You are not whitelisted on this server!",
        "You have been banned from this server",
        "/kick SamplePlayer Por spam",
    ]
    for reason in test_cases:
        lines = [f"[22Sep2026 20:00:00.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: {reason}"]
        events = service._parse_lines(lines, "latest.log")
        assert len(events) == 1, f"Failed for reason: {reason}"
        assert events[0].category == "KICKED_BANNED", f"Failed for reason: {reason}"
        assert events[0].severity == "warning"
        assert events[0].suspected_mod is None
