"""Unit tests for the player disconnect analyzer."""

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
    assert evt.category_label == "Salió del juego"
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
        "Internal Exception: java.net.SocketTimeoutException: Read timed out",
    ]
    for reason in test_cases:
        lines = [f"[22Sep2026 20:00:00.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: {reason}"]
        events = service._parse_lines(lines, "latest.log")
        assert len(events) == 1, f"Failed for reason: {reason}"
        assert events[0].category == "TIMEOUT", f"Failed for reason: {reason}"
        assert events[0].severity == "warning"
        assert events[0].suspected_mod is None


def test_kicked_banned_and_whitelist_reasons(service: PlayerCrashService):
    test_cases = {
        "Kicked by an operator": "KICKED",
        "Kicked: Flying is not enabled on this server": "KICKED",
        "Flying is not enabled on this server": "KICKED",
        "/kick SamplePlayer Por spam": "KICKED",
        "You have been banned from this server": "BANNED",
        "You are not whitelisted on this server!": "NOT_WHITELISTED",
        "You are not white-listed on this server!": "NOT_WHITELISTED",
    }
    for reason, expected in test_cases.items():
        lines = [f"[22Sep2026 20:00:00.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: {reason}"]
        events = service._parse_lines(lines, "latest.log")
        assert len(events) == 1, f"Failed for reason: {reason}"
        assert events[0].category == expected, f"Failed for reason: {reason}"
        assert events[0].severity == "warning"
        assert events[0].suspected_mod is None


def test_custom_kick_message_is_attributed_to_who_kicked(service: PlayerCrashService):
    lines = [
        "[22Sep2026 20:00:00.000] [Server thread/INFO] [minecraft/MinecraftServer]: [Admin: Kicked SamplePlayer: andá a dormir]",
        "[22Sep2026 20:00:00.100] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: andá a dormir",
    ]
    evt = service._parse_lines(lines, "latest.log")[0]
    assert evt.category == "KICKED"
    assert evt.kicked_by == "Admin"
    assert "Admin" in evt.headline


def test_ban_from_console(service: PlayerCrashService):
    lines = [
        "[22Sep2026 20:00:00.000] [Server thread/INFO] [minecraft/MinecraftServer]: Banned SamplePlayer: Griefing",
        "[22Sep2026 20:00:00.100] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: Griefing",
    ]
    evt = service._parse_lines(lines, "latest.log")[0]
    assert evt.category == "BANNED"
    assert evt.kicked_by == "la consola"


def test_someone_else_being_kicked_does_not_blame_the_player(service: PlayerCrashService):
    lines = [
        "[22Sep2026 20:00:00.000] [Server thread/INFO] [minecraft/MinecraftServer]: [Admin: Kicked OtherPlayer: spam]",
        "[22Sep2026 20:00:05.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: Disconnected",
    ]
    assert service._parse_lines(lines, "latest.log")[0].category == "NORMAL_DISCONNECT"


def test_game_closed_abruptly(service: PlayerCrashService):
    for reason in (
        "Connection reset",
        "Internal Exception: java.io.IOException: Connection reset by peer",
        "Internal Exception: java.io.IOException: An existing connection was forcibly closed by the remote host",
    ):
        lines = [f"[22Sep2026 20:00:00.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: {reason}"]
        evt = service._parse_lines(lines, "latest.log")[0]
        assert evt.category == "CLIENT_CLOSED", reason
        assert "crash" in evt.advice


def test_packet_error_points_at_the_mod_channel(service: PlayerCrashService):
    lines = [
        "[22Sep2026 20:00:00.000] [Netty Server IO #3/ERROR] [minecraft/Connection]: Failed to decode packet 'serverbound/minecraft:custom_payload' for waystones:sync_config",
        "[22Sep2026 20:00:00.100] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: Network Protocol Error",
    ]
    evt = service._parse_lines(lines, "latest.log")[0]
    assert evt.category == "MOD_ERROR"
    assert evt.suspected_mod == "waystones"


def test_session_timeline_tells_what_was_happening(service: PlayerCrashService):
    lines = [
        "[22Sep2026 19:30:00.000] [Server thread/INFO] [minecraft/PlayerList]: SamplePlayer[/203.0.113.7:51234] logged in with entity id 42 at (12.5, 64.0, -30.2)",
        "[22Sep2026 19:30:00.100] [Server thread/INFO] [minecraft/MinecraftServer]: SamplePlayer joined the game",
        "[22Sep2026 19:40:00.000] [Server thread/INFO] [minecraft/MinecraftServer]: <SamplePlayer> voy a la base",
        "[22Sep2026 19:45:00.000] [Server thread/INFO] [minecraft/MinecraftServer]: SamplePlayer was slain by Zombie",
        "[22Sep2026 19:59:30.000] [Server thread/WARN] [minecraft/MinecraftServer]: Can't keep up! Is the server overloaded? Running 5000ms or 100 ticks behind",
        "[22Sep2026 20:00:00.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: Timed out",
    ]
    evt = service._parse_lines(lines, "latest.log")[0]
    assert evt.category == "TIMEOUT"
    assert evt.session_seconds == 30 * 60
    assert evt.joined_at == "12, 64, -30"
    assert evt.lag_warnings == 1
    assert "lag" in evt.advice
    kinds = [entry.kind for entry in evt.timeline]
    assert kinds == ["join", "chat", "death", "lag", "leave"]
    assert evt.occurred_at == "2026-09-22T20:00:00"


def test_player_addresses_never_reach_the_panel(service: PlayerCrashService):
    lines = [
        "[22Sep2026 19:30:00.000] [Server thread/INFO] [minecraft/PlayerList]: SamplePlayer[/203.0.113.7:51234] logged in with entity id 42 at (1.0, 64.0, 1.0)",
        "[22Sep2026 20:00:00.000] [Server thread/INFO] [minecraft/ServerLoginPacketListenerImpl]: SamplePlayer (/203.0.113.7:51234) lost connection: You are not white-listed on this server!",
    ]
    evt = service._parse_lines(lines, "latest.log")[0]
    assert evt.category == "NOT_WHITELISTED"
    dumped = evt.model_dump_json()
    assert "203.0.113.7" not in dumped


def test_refused_login_does_not_borrow_other_players_events(service: PlayerCrashService):
    lines = [
        "[22Sep2026 19:00:00.000] [Netty Server IO #3/ERROR] [minecraft/Connection]: Failed to decode packet for waystones:sync",
        "[22Sep2026 19:00:01.000] [Server thread/INFO] [minecraft/MinecraftServer]: <OtherPlayer> hola",
        *[f"[22Sep2026 19:0{n}:00.000] [Server thread/INFO] [minecraft/MinecraftServer]: tick {n}" for n in range(2, 9)],
        "[22Sep2026 19:09:00.000] [Server thread/INFO] [minecraft/ServerLoginPacketListenerImpl]: Stranger (/192.0.2.50:4444) lost connection: You are not white-listed on this server!",
    ]
    evt = service._parse_lines(lines, "latest.log")[0]
    assert evt.category == "NOT_WHITELISTED"
    assert [entry.kind for entry in evt.timeline] == ["leave"]


def test_vanilla_time_only_logs_get_the_file_date(service: PlayerCrashService):
    lines = [
        "[23:59:50] [Server thread/INFO]: SamplePlayer[/198.51.100.2:5000] logged in with entity id 1 at (0.0, 70.0, 0.0)",
        "[00:00:10] [Server thread/INFO]: SamplePlayer lost connection: Disconnected",
    ]
    evt = service._parse_lines(lines, "2026-10-20-1.log.gz")[0]
    assert evt.occurred_at == "2026-10-20T00:00:10"
    assert evt.session_seconds == 20


def test_event_id_survives_log_rotation(service: PlayerCrashService):
    lines = [
        "[22Sep2026 20:00:00.000] [Server thread/INFO] [minecraft/ServerGamePacketListenerImpl]: SamplePlayer lost connection: Disconnected",
    ]
    assert service._parse_lines(lines, "latest.log")[0].id == service._parse_lines(lines, "2026-09-22-1.log.gz")[0].id
