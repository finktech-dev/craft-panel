"""Find out why each player left the server, and what was happening right before.

The server log is the only source: every "lost connection" line becomes one event, classified by
its reason and by what the log says about that player in the same session (kicks, bans, chat,
commands, deaths, lag warnings and errors). Connection addresses and the host's personal folders
are removed before anything is stored or shown.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.core.config import Settings, settings
from app.core.privacy import redact_ip_addresses, redact_personal_paths
from app.schemas.player_crashes import PlayerCrashEvent, PlayerCrashesListResponse, PlayerTimelineEntry

_STORAGE_VERSION = 2
_NAME = r"[A-Za-z0-9_]{3,16}"

# Disconnect lines. The voice chat mod's "Disconnecting client X" is left out on purpose: the game
# always logs its own "lost connection" line too, and counting both would duplicate the event.
_DISCONNECT_PATTERNS = [
    re.compile(rf"ServerGamePacketListenerImpl/\]:\s*({_NAME})\s+lost connection:\s*(.*)", re.I),
    re.compile(rf"name=({_NAME})[,\s].*lost connection:\s*(.*)", re.I),
    re.compile(rf"(?:^|\]:\s*)({_NAME})\s+\(/[^)]*\)\s+lost connection:\s*(.*)", re.I),
    re.compile(rf"(?:^|\]:\s*)({_NAME})\s+lost connection:\s*(.*)", re.I),
]

# key -> (label, severity). The label is what the "Qué pasó" filter shows.
_CATEGORIES: dict[str, tuple[str, str]] = {
    "NORMAL_DISCONNECT": ("Salió del juego", "info"),
    "TIMEOUT": ("Se cortó la conexión", "warning"),
    "CLIENT_CLOSED": ("Su juego se cerró de golpe", "warning"),
    "KICKED": ("Lo expulsaron", "warning"),
    "BANNED": ("Está bloqueado", "warning"),
    "NOT_WHITELISTED": ("No está en la lista de amigos", "warning"),
    "CLIENT_MISMATCH": ("Mods o versión distintos", "warning"),
    "MOD_ERROR": ("Problema con un mod", "error"),
    "INVALID_DATA": ("Datos del jugador dañados", "error"),
    "SERVER_CRASH": ("El servidor se cerró", "error"),
    "UNKNOWN": ("Motivo poco común", "warning"),
    "KICKED_BANNED": ("Lo sacaron del servidor", "warning"),
}

_NOT_WHITELISTED_RX = re.compile(r"not white-?listed", re.I)
_BANNED_RX = re.compile(r"\bbanned\b|\bbaneado\b", re.I)
_KICK_RX = re.compile(r"\bkicked\b|\bexpulsado\b|/kick\b", re.I)
# Kicks the server itself issues, without anyone typing /kick.
_AUTO_KICK_RX = re.compile(
    r"flying is not enabled|idle for too long|illegal characters in chat|disconnect\.spam|kicked for spamming"
    r"|invalid move player packet|multiplayer\.disconnect\.(?:idling|flying|illegal|spam|invalid)",
    re.I,
)
_TIMEOUT_RX = re.compile(r"\btimed\s*out\b|sockettimeoutexception", re.I)
# The other side closed the socket without saying goodbye: the game crashed, was force-closed,
# or the player's internet dropped at that instant.
_CLIENT_CLOSED_RX = re.compile(
    r"connection reset|forcibly closed by the remote host|broken pipe|end of stream|connection abort", re.I
)
_NORMAL_DISCONNECT_RX = re.compile(
    r"^(?:disconnected|quitting|left the game|server closed|you logged in from another location)\.?$", re.I
)
_PROTOCOL_RX = re.compile(
    r"network protocol error|decoderexception|encoderexception|payload may not be larger|larger than i expected"
    r"|failed to (?:de|en)code packet|error receiving packet|packet .{0,40}too (?:big|large)|unknown custom packet",
    re.I,
)
_MISMATCH_RX = re.compile(
    r"incompatible client|please use neoforge|version mismatch|missing mod|channels \[.*\] are not present"
    r"|mod rejections|mismatched mod channel|outdated (?:client|server)|incompatible fml"
    r"|missing required datapack registries|this server has mods that require",
    re.I,
)
_INVALID_DATA_RX = re.compile(r"invalid player data|\bnbt\b|corrupt|tag not found", re.I)
_SERVER_CRASH_RX = re.compile(
    r"crash report has been saved|encountered an unexpected exception\s+net\.minecraft|a single server tick took", re.I
)
_MOD_EXCEPTION_RX = re.compile(
    r"capability|illegalstateexception|nullpointerexception|mixin|modloadingexception|registry"
    r"|classnotfoundexception|nosuchmethoderror",
    re.I,
)

# Shutdown lines never point at a culprit.
_SHUTDOWN_LINE_RX = re.compile(
    r"stopping (?:the )?server|starting shutdown process|closing storage|goodbye!|saving (?:chunks|players|worlds|level)",
    re.I,
)
_SERVER_START_RX = re.compile(r"starting minecraft server version|loading properties", re.I)

# Error, exception, crash and stack trace lines.
_ERROR_LINE_RX = re.compile(
    r"/(?:ERROR|FATAL)\]"
    r"|\b(?:[a-zA-Z0-9_.]+(?:Exception|Error)|CrashReport|Crash)\b"
    r"|^\s*(?:at\s+[a-zA-Z0-9_$.]+|Caused by:)"
    r"|\bat\s+(?:net|com|org|dev|de|me|io)\.[a-zA-Z0-9_.]+",
    re.I,
)
_LOG_LEVEL_ERROR_RX = re.compile(r"/(?:ERROR|FATAL)\]")
_LAG_RX = re.compile(r"can't keep up!.*?running (\d+)ms or (\d+) ticks behind", re.I)

# Mods recognised by package, logger name or file name.
_KNOWN_MOD_PATTERNS: list[tuple[str, list[re.Pattern]]] = [
    ("Create", [re.compile(r"com\.simibubi\.create", re.I), re.compile(r"\[create(?:/[^\]]*)?\]", re.I), re.compile(r"\bcreate-[0-9.]+", re.I), re.compile(r"\bcreate\b", re.I)]),
    ("LuckPerms", [re.compile(r"(?:net|me)\.luck(?:o)?\.luckperms", re.I), re.compile(r"\[luckperms(?:/[^\]]*)?\]", re.I), re.compile(r"\bluckperms\b", re.I)]),
    ("Point Blank", [re.compile(r"com\.vicmatskiv\.pointblank", re.I), re.compile(r"\[pointblank(?:/[^\]]*)?\]", re.I), re.compile(r"\bpointblank\b", re.I)]),
    ("Balm", [re.compile(r"net\.blay09\.mods\.balm", re.I), re.compile(r"\[balm(?:/[^\]]*)?\]", re.I), re.compile(r"\bbalm\b", re.I)]),
    ("Voice Chat", [re.compile(r"de\.maxhenkel\.voicechat", re.I), re.compile(r"\[voicechat(?:/[^\]]*)?\]", re.I), re.compile(r"\bvoicechat\b", re.I)]),
    ("FTB Chunks", [re.compile(r"dev\.ftb\.mods\.ftbchunks", re.I), re.compile(r"\[ftbchunks(?:/[^\]]*)?\]", re.I), re.compile(r"\bftbchunks\b", re.I)]),
    ("FTB Quests", [re.compile(r"dev\.ftb\.mods\.ftbquests", re.I), re.compile(r"\[ftbquests(?:/[^\]]*)?\]", re.I), re.compile(r"\bftbquests\b", re.I)]),
    ("FTB Teams", [re.compile(r"dev\.ftb\.mods\.ftbteams", re.I), re.compile(r"\[ftbteams(?:/[^\]]*)?\]", re.I), re.compile(r"\bftbteams\b", re.I)]),
    ("Sophisticated Backpacks", [re.compile(r"net\.p3pp3rf1y\.sophisticatedbackpacks", re.I), re.compile(r"\[sophisticatedbackpacks(?:/[^\]]*)?\]", re.I), re.compile(r"\bsophisticatedbackpacks\b", re.I)]),
    ("Curios API", [re.compile(r"top\.theillusivec4\.curios", re.I), re.compile(r"\[curios(?:/[^\]]*)?\]", re.I), re.compile(r"\bcurios\b", re.I)]),
    ("Farmer's Delight", [re.compile(r"vectorwing\.farmersdelight", re.I), re.compile(r"\[farmersdelight(?:/[^\]]*)?\]", re.I), re.compile(r"\bfarmersdelight\b", re.I)]),
    ("JourneyMap", [re.compile(r"journeymap", re.I), re.compile(r"\[journeymap(?:/[^\]]*)?\]", re.I), re.compile(r"\bjourneymap\b", re.I)]),
]

_JAR_RX = re.compile(r"(?:~\[|\b)([a-zA-Z0-9_\-\.]+)\.jar", re.I)
_IGNORED_JARS = {
    "minecraft", "server", "client", "neoforge", "forge",
    "minecraftforge", "java", "rt", "fabric", "quilt",
    "main", "libraries", "bundler",
}
# Packet channels look like "namespace:path"; the namespace is usually the mod id.
_CHANNEL_RX = re.compile(r"\b([a-z][a-z0-9_.-]{1,63}):[a-z][a-z0-9_/.-]+")
_VANILLA_NAMESPACES = {"minecraft", "neoforge", "forge", "fabric", "c", "java", "http", "https", "brigadier"}

# Log line timestamps: NeoForge "[22Sep2026 20:00:00.000]", vanilla "[20:00:00]", or ISO.
_TS_NEOFORGE = re.compile(r"^\[(\d{1,2})([A-Za-zé]{3,5})\.?(\d{4}) (\d{2}):(\d{2}):(\d{2})")
_TS_ISO = re.compile(r"^\[(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})")
_TS_TIME = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\]")
_MONTHS = {
    "jan": 1, "ene": 1, "feb": 2, "mar": 3, "apr": 4, "abr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dec": 12, "dic": 12,
}
_FILE_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

_DEATH_RX = (
    r"(?:was |died|drowned|blew up|fell |hit the ground|burned|went up in flames|walked into|tried to swim"
    r"|starved|suffocated|froze|withered away|experienced kinetic|discovered the floor|didn't want to live"
    r"|left the confines|was killed)"
)
_TIMELINE_LIMIT = 15


def _message(line: str) -> str:
    """The text after the log prefix ("[time] [thread/LEVEL] [logger]: ")."""
    cut = line.find("]: ")
    return line[cut + 3:].strip() if cut != -1 else line.strip()


def _clean(text: str) -> str:
    return redact_ip_addresses(redact_personal_paths(text))


def _short(text: str, limit: int = 140) -> str:
    text = text.strip()
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


class PlayerCrashService:
    def __init__(self, configured_settings: Settings = settings) -> None:
        self._settings = configured_settings
        self._storage_file = Path(self._settings.panel_directory or ".") / ".player_crashes.json"
        self._events: dict[str, PlayerCrashEvent] = {}
        self._lock = asyncio.Lock()
        self._initialized = False
        self._latest_signature: tuple[float, int] | None = None

    @property
    def logs_dir(self) -> Path:
        assert self._settings.server_directory
        return self._settings.server_directory / "logs"

    # Storage

    def _load_storage(self) -> None:
        if not self._storage_file.is_file():
            return
        try:
            data = json.loads(self._storage_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        # Lists saved by older versions lack the session details; the logs are read again instead.
        if not isinstance(data, dict) or data.get("version") != _STORAGE_VERSION:
            return
        for raw in data.get("events", []):
            try:
                event = PlayerCrashEvent(**raw)
            except Exception:
                continue
            self._events[event.id] = event

    def _save_storage(self) -> None:
        try:
            items = [event.model_dump() for event in self._sorted_events()]
            payload = json.dumps({"version": _STORAGE_VERSION, "events": items}, indent=2, ensure_ascii=False)
            temporary = self._storage_file.with_name(f"{self._storage_file.name}.tmp")
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, self._storage_file)
        except OSError:
            pass

    def _sorted_events(self) -> list[PlayerCrashEvent]:
        return sorted(self._events.values(), key=lambda event: event.occurred_at or event.timestamp, reverse=True)

    # Scanning

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            await asyncio.to_thread(self._load_storage)
            await asyncio.to_thread(self._scan_logs_sync)
            self._initialized = True

    async def scan_logs(self) -> int:
        async with self._lock:
            return await asyncio.to_thread(self._scan_logs_sync)

    def _current_latest_signature(self) -> tuple[float, int] | None:
        try:
            stat = (self.logs_dir / "latest.log").stat()
        except OSError:
            return None
        return stat.st_mtime, stat.st_size

    def _scan_logs_sync(self, *, latest_only: bool = False) -> int:
        if not self.logs_dir.is_dir():
            return 0
        candidates: list[Path] = []
        latest = self.logs_dir / "latest.log"
        if latest.is_file():
            candidates.append(latest)
        if not latest_only:
            archived = sorted(self.logs_dir.glob("*.log.gz"), key=lambda path: path.stat().st_mtime, reverse=True)
            candidates.extend(archived[:10])
        self._latest_signature = self._current_latest_signature()

        new_events = 0
        for log_file in candidates:
            try:
                if log_file.suffix == ".gz":
                    lines = gzip.decompress(log_file.read_bytes()).decode("utf-8", "replace").splitlines()
                else:
                    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            except (OSError, EOFError, gzip.BadGzipFile):
                continue
            for event in self._parse_lines(lines, log_file.name, self._file_end_date(log_file)):
                if event.id not in self._events:
                    self._events[event.id] = event
                    new_events += 1
        if new_events:
            self._save_storage()
        return new_events

    @staticmethod
    def _file_end_date(log_file: Path) -> date | None:
        """The day the log ends: in the archive's name, or the day latest.log was last written."""
        named = _FILE_DATE.search(log_file.name)
        if named:
            try:
                return date(int(named.group(1)), int(named.group(2)), int(named.group(3)))
            except ValueError:
                return None
        try:
            return datetime.fromtimestamp(log_file.stat().st_mtime).date()
        except OSError:
            return None

    # Parsing

    @staticmethod
    def _line_times(lines: list[str], end_date: date | None) -> list[datetime | None]:
        """A datetime per line. Lines without their own timestamp (stack traces) inherit the previous one."""
        times: list[datetime | None] = []
        time_only: list[tuple[int, int, int] | None] = []
        last: datetime | None = None
        for line in lines:
            stamp: datetime | None = None
            clock: tuple[int, int, int] | None = None
            if line.startswith("["):
                match = _TS_NEOFORGE.match(line)
                if match:
                    month = _MONTHS.get(match.group(2)[:3].lower())
                    if month:
                        try:
                            stamp = datetime(int(match.group(3)), month, int(match.group(1)), int(match.group(4)), int(match.group(5)), int(match.group(6)))
                        except ValueError:
                            stamp = None
                elif (match := _TS_ISO.match(line)):
                    try:
                        stamp = datetime(*(int(match.group(index)) for index in range(1, 7)))
                    except ValueError:
                        stamp = None
                elif (match := _TS_TIME.match(line)):
                    clock = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            time_only.append(clock)
            if stamp is not None:
                last = stamp
            times.append(stamp if stamp is not None else (last if clock is None else None))

        # Vanilla logs only print the time: count midnights backwards from the day the file ends.
        if any(clock is not None for clock in time_only):
            day = end_date or datetime.now().date()
            previous: tuple[int, int, int] | None = None
            resolved: list[datetime | None] = [None] * len(lines)
            for index in range(len(lines) - 1, -1, -1):
                clock = time_only[index]
                if clock is None:
                    continue
                if previous is not None and clock > previous:
                    day -= timedelta(days=1)
                previous = clock
                resolved[index] = datetime(day.year, day.month, day.day, *clock)
            carried: datetime | None = None
            for index, value in enumerate(resolved):
                if value is not None:
                    carried = value
                    times[index] = value
                elif time_only[index] is None and times[index] is None:
                    times[index] = carried
        return times

    def _parse_lines(self, lines: list[str], filename: str, end_date: date | None = None) -> list[PlayerCrashEvent]:
        if end_date is None:
            named = _FILE_DATE.search(filename)
            if named:
                try:
                    end_date = date(int(named.group(1)), int(named.group(2)), int(named.group(3)))
                except ValueError:
                    end_date = None
        times = self._line_times(lines, end_date)
        events: list[PlayerCrashEvent] = []
        for index, line in enumerate(lines):
            if "lost connection" not in line:
                continue
            for pattern in _DISCONNECT_PATTERNS:
                match = pattern.search(line)
                if match:
                    events.append(self._build_event(lines, times, index, match.group(1).strip(), (match.group(2) or "").strip(), filename))
                    break
        return events

    def _build_event(
        self,
        lines: list[str],
        times: list[datetime | None],
        index: int,
        player: str,
        reason: str,
        filename: str,
    ) -> PlayerCrashEvent:
        context_block = lines[max(0, index - 35): min(len(lines), index + 10)]
        login_index = self._find_login(lines, index, player)
        # Without a join line (a refused login, or a log that starts mid-session) only the last few
        # lines belong to this player; older lag and errors would be someone else's story.
        session_start = login_index if login_index is not None else max(0, index - 5)
        kick = self._find_kick(lines[login_index if login_index is not None else max(0, index - 80):index + 1], player)
        category, suspected_mod = self._classify(reason, context_block, kick)
        label, severity = _CATEGORIES[category]

        occurred = times[index]
        joined = times[login_index] if login_index is not None else None
        session_seconds = int((occurred - joined).total_seconds()) if occurred and joined and occurred >= joined else None
        # Server lag hits everyone, so it is counted even when the join line is missing.
        lag_warnings = self._count_lag(lines, times, index, session_start if login_index is not None else max(0, index - 400))
        timeline = self._timeline(lines, times, session_start, index, player, reason, login_index is not None)
        joined_at = self._join_position(lines[login_index], player) if login_index is not None else None
        kicked_by = kick[1] if kick else ("el servidor" if _AUTO_KICK_RX.search(reason) else None)

        headline, advice = self._explain(category, player, suspected_mod, kicked_by, kick[2] if kick else None, reason, lag_warnings)
        raw_time = re.search(r"\[(\d{1,2}[A-Za-zé]{3,5}\.?\d{4}\s+\d{2}:\d{2}:\d{2}(?:\.\d{3})?|\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{3})?|\d{2}:\d{2}:\d{2})\]", line := lines[index])
        timestamp = (
            occurred.strftime("%Y-%m-%d %H:%M:%S") if occurred
            else raw_time.group(1) if raw_time
            else datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        )
        # Stable across log rotation: the same line keeps its id when latest.log becomes an archive.
        previous_line = lines[index - 1] if index else ""
        event_id = hashlib.sha256(f"{player}\n{line}\n{previous_line}\n{timestamp}".encode("utf-8")).hexdigest()[:12]

        return PlayerCrashEvent(
            id=event_id,
            player=player,
            avatar_url=f"https://mc-heads.net/avatar/{player}/64",
            category=category,
            category_label=label,
            severity=severity,
            summary=_clean(reason) or "El jugador perdió la conexión",
            timestamp=timestamp,
            file_source=filename,
            context_lines=[_clean(item) for item in context_block],
            suspected_mod=suspected_mod,
            suggestion=advice,
            headline=headline,
            advice=advice,
            occurred_at=occurred.isoformat(timespec="seconds") if occurred else None,
            session_seconds=session_seconds,
            joined_at=joined_at,
            kicked_by=kicked_by,
            lag_warnings=lag_warnings,
            timeline=timeline,
        )

    # Session details

    @staticmethod
    def _find_login(lines: list[str], index: int, player: str) -> int | None:
        login = re.compile(rf"(?:^|\]:\s*){re.escape(player)}\[/[^\]]*\] logged in with entity id|(?:^|\]:\s*){re.escape(player)} joined the game")
        for position in range(index - 1, max(-1, index - 20000), -1):
            line = lines[position]
            if player in line and login.search(line):
                # Prefer the "logged in" line, which carries the position, over "joined the game".
                if "joined the game" in line and position and "logged in" in lines[position - 1] and player in lines[position - 1]:
                    return position - 1
                return position
            if _SERVER_START_RX.search(line) or (player in line and "lost connection" in line):
                return None
        return None

    @staticmethod
    def _join_position(line: str, player: str) -> str | None:
        match = re.search(r"logged in with entity id \d+ at \((?:\[([^\]]+)\])?\s*([-\d.]+),\s*([-\d.]+),\s*([-\d.]+)\)", line)
        if not match:
            return None
        world = (match.group(1) or "").strip()
        coords = ", ".join(str(round(float(value))) for value in match.groups()[1:])
        return f"{coords} ({world})" if world else coords

    @staticmethod
    def _find_kick(session: list[str], player: str) -> tuple[str, str, str | None] | None:
        """("kick" | "ban", who did it, reason) when the log shows someone kicking or banning the player."""
        name = re.escape(player)
        by_player = re.compile(rf"\[({_NAME}): (Kicked|Banned(?: IP)?) {name}(?:: (.*?))?\]$", re.I)
        by_console = re.compile(rf"(?:^|\]:\s*)(Kicked|Banned(?: IP)?) {name}(?:: (.*))?$", re.I)
        for line in reversed(session[-80:]):
            if player not in line:
                continue
            message = _message(line)
            match = by_player.search(message)
            if match:
                action = "ban" if match.group(2).lower().startswith("banned") else "kick"
                return action, match.group(1), match.group(3)
            match = by_console.search(message)
            if match:
                action = "ban" if match.group(1).lower().startswith("banned") else "kick"
                return action, "la consola", match.group(2)
        return None

    @staticmethod
    def _count_lag(lines: list[str], times: list[datetime | None], index: int, start: int) -> int:
        """Lag warnings in the two minutes before the disconnect (or the last 80 lines without timestamps)."""
        end_time = times[index]
        count = 0
        for position in range(index - 1, max(start, index - 400) - 1, -1):
            stamp = times[position]
            if end_time and stamp and (end_time - stamp).total_seconds() > 120:
                break
            if not end_time and index - position > 80:
                break
            if _LAG_RX.search(lines[position]):
                count += 1
        return count

    def _timeline(
        self,
        lines: list[str],
        times: list[datetime | None],
        start: int,
        index: int,
        player: str,
        reason: str,
        has_login: bool,
    ) -> list[PlayerTimelineEntry]:
        name = re.escape(player)
        rules: list[tuple[re.Pattern, str, callable]] = [
            (re.compile(rf"^{name}\[/[^\]]*\] logged in"), "join", lambda m, line: "Entró al servidor" + (f" en {pos}" if (pos := self._join_position(line, player)) else "")),
            (re.compile(rf"^(?:\[Not Secure\] )?<{name}> (.*)$"), "chat", lambda m, line: f"Escribió: «{_short(m.group(1), 100)}»"),
            (re.compile(rf"^{name} issued server command: (.*)$"), "command", lambda m, line: f"Usó el comando {_short(m.group(1), 80)}"),
            (re.compile(rf"^\[{name}: (.*)\]$"), "admin", lambda m, line: f"Usó un comando: {_short(m.group(1), 100)}"),
            (re.compile(rf"^\[({_NAME}): ((?:Kicked|Banned(?: IP)?) {name}.*)\]$", re.I), "kick", lambda m, line: f"{m.group(1)}: {_short(m.group(2), 100)}"),
            (re.compile(rf"^((?:Kicked|Banned(?: IP)?) {name}.*)$", re.I), "kick", lambda m, line: f"Desde la consola: {_short(m.group(1), 100)}"),
            (re.compile(rf"^{name} has (?:made the advancement|completed the challenge|reached the goal) \[(.*)\]$"), "advancement", lambda m, line: f"Logró «{_short(m.group(1), 60)}»"),
            (re.compile(rf"^{name} moved (?:too quickly|wrongly)"), "lag", lambda m, line: "El servidor lo frenó por moverse raro (suele ser lag)"),
            (re.compile(rf"^{name} {_DEATH_RX}"), "death", lambda m, line: f"Murió: {_short(_message(line), 100)}"),
        ]
        entries: list[PlayerTimelineEntry] = []
        lag_entries = 0
        for position in range(start, index):
            line = lines[position]
            message = _message(line)
            stamp = times[position].strftime("%H:%M:%S") if times[position] else None
            if player in line:
                for pattern, kind, describe in rules:
                    match = pattern.search(message)
                    if match:
                        if kind == "join" and not has_login:
                            break
                        entries.append(PlayerTimelineEntry(time=stamp, kind=kind, text=_clean(describe(match, message))))
                        break
                continue
            lag = _LAG_RX.search(message)
            if lag:
                lag_entries += 1
                seconds = int(lag.group(1)) / 1000
                entries.append(PlayerTimelineEntry(time=stamp, kind="lag", text=f"El servidor iba atrasado ({seconds:.1f} s de retraso)"))
            elif index - position <= 60 and _LOG_LEVEL_ERROR_RX.search(line) and not _SHUTDOWN_LINE_RX.search(line):
                entries.append(PlayerTimelineEntry(time=stamp, kind="error", text=_clean(f"Error: {_short(message, 140)}")))

        # Keep the join, the last lag warnings and errors, and the most recent player actions.
        join = [entry for entry in entries if entry.kind == "join"][:1]
        others = [entry for entry in entries if entry.kind != "join"]
        if lag_entries > 2:
            lag_seen = 0
            trimmed: list[PlayerTimelineEntry] = []
            for entry in reversed(others):
                if entry.kind == "lag" and entry.text.startswith("El servidor iba"):
                    lag_seen += 1
                    if lag_seen > 2:
                        continue
                trimmed.append(entry)
            others = list(reversed(trimmed))
        others = others[-(_TIMELINE_LIMIT - 1 - len(join)):]
        leave_time = times[index].strftime("%H:%M:%S") if times[index] else None
        leave = PlayerTimelineEntry(time=leave_time, kind="leave", text=_clean(f"Se desconectó: {_short(reason, 140) or 'sin motivo'}"))
        return [*join, *others, leave]

    # Classification

    def _find_suspected_mod(self, reason_detail: str, context_block: list[str]) -> str | None:
        candidate_lines: list[str] = []
        if reason_detail and not _SHUTDOWN_LINE_RX.search(reason_detail):
            candidate_lines.append(reason_detail)
        candidate_lines.extend(context_block)
        valid_lines = [line for line in candidate_lines if not _SHUTDOWN_LINE_RX.search(line)]

        # Only an exception, error or crash can point at a mod.
        error_lines = [line for line in valid_lines if _ERROR_LINE_RX.search(line)]
        if not error_lines:
            return None
        for mod_name, patterns in _KNOWN_MOD_PATTERNS:
            for pattern in patterns:
                if any(pattern.search(line) for line in error_lines):
                    return mod_name
        for line in error_lines:
            for jar in _JAR_RX.findall(line):
                lowered = jar.lower()
                if lowered not in _IGNORED_JARS and not lowered.startswith(("minecraft", "neoforge", "forge-", "server")):
                    return jar
        for line in error_lines:
            match = re.search(r"^\s*at\s+([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)", line)
            if match:
                first, second, third = (group.lower() for group in match.groups())
                if first in ("com", "net", "org", "dev", "de", "me", "io") and second not in (
                    "minecraft", "mojang", "google", "apache", "netty", "sun", "java", "neoforged"
                ):
                    return third.capitalize() if second in ("github", "gitlab") else second.capitalize()
        return None

    @staticmethod
    def _mod_from_channel(text: str) -> str | None:
        for namespace in _CHANNEL_RX.findall(text):
            if namespace not in _VANILLA_NAMESPACES and not namespace.startswith(("java.", "net.", "com.", "io.")):
                return namespace
        return None

    def _classify(
        self,
        reason: str,
        context_block: list[str],
        kick: tuple[str, str, str | None] | None,
    ) -> tuple[str, str | None]:
        reason = reason.strip()
        if _NOT_WHITELISTED_RX.search(reason):
            return "NOT_WHITELISTED", None
        if (kick and kick[0] == "ban") or _BANNED_RX.search(reason):
            return "BANNED", None
        if kick or _KICK_RX.search(reason) or _AUTO_KICK_RX.search(reason):
            return "KICKED", None
        if _TIMEOUT_RX.search(reason):
            return "TIMEOUT", None
        if _CLIENT_CLOSED_RX.search(reason):
            return "CLIENT_CLOSED", None
        if _NORMAL_DISCONNECT_RX.search(reason) or (
            re.match(r"^(?:disconnected|quitting|left the game|server closed)\b", reason, re.I)
            and not re.search(r"exception|error|crash|fatal", reason, re.I)
        ):
            return "NORMAL_DISCONNECT", None
        if _MISMATCH_RX.search(reason):
            return "CLIENT_MISMATCH", None

        clean_context = [line for line in context_block if not _SHUTDOWN_LINE_RX.search(line)]
        evidence = f"{reason}\n" + "\n".join(clean_context)
        suspected = self._find_suspected_mod(reason, clean_context)

        if _PROTOCOL_RX.search(reason):
            # A packet the game could not read or write: almost always a mod's network message.
            return "MOD_ERROR", suspected or self._mod_from_channel(evidence)
        if _INVALID_DATA_RX.search(evidence):
            return "INVALID_DATA", suspected
        if _MISMATCH_RX.search(evidence):
            return "CLIENT_MISMATCH", None
        if _SERVER_CRASH_RX.search(evidence):
            return "SERVER_CRASH", suspected
        if _MOD_EXCEPTION_RX.search(evidence) or suspected or re.search(r"exception|fatal", evidence, re.I):
            return "MOD_ERROR", suspected
        if _TIMEOUT_RX.search(evidence):
            return "TIMEOUT", None
        return "UNKNOWN", None

    @staticmethod
    def _explain(
        category: str,
        player: str,
        mod: str | None,
        kicked_by: str | None,
        kick_reason: str | None,
        reason: str,
        lag_warnings: int,
    ) -> tuple[str, str | None]:
        lag_note = (
            f" Justo antes el servidor avisó {lag_warnings} {'vez' if lag_warnings == 1 else 'veces'} que iba atrasado, así que el lag pudo influir."
            if lag_warnings else ""
        )
        if category == "NORMAL_DISCONNECT":
            if "another location" in reason.lower():
                return f"{player} entró desde otra computadora y se cerró la sesión anterior.", None
            return f"{player} salió del juego.", None
        if category == "TIMEOUT":
            return (
                f"A {player} se le cortó la conexión.",
                "El servidor dejó de recibir noticias de su juego. Suele ser su internet o el de tu casa."
                + (lag_note or " Si le pasa seguido, que pruebe con cable o cerca del router."),
            )
        if category == "CLIENT_CLOSED":
            return (
                f"El juego de {player} se cerró de golpe.",
                "Puede ser que su Minecraft se haya trabado y cerrado (crash), que lo cerró a la fuerza o que se le cortó internet en ese instante. "
                "Si fue un crash, el informe está en su compu, en la carpeta crash-reports de su Minecraft." + lag_note,
            )
        if category == "KICKED":
            who = f" ({kicked_by})" if kicked_by else ""
            why = f" Motivo: «{_short(kick_reason or reason, 120)}»." if (kick_reason or reason) else ""
            if kicked_by == "el servidor":
                return f"El servidor sacó a {player} automáticamente.", f"Pasa por cosas como volar sin permiso o estar quieto mucho tiempo.{why}"
            return f"Expulsaron a {player}{who}.", f"Puede volver a entrar cuando quiera.{why}"
        if category == "BANNED":
            who = f" ({kicked_by})" if kicked_by else ""
            return f"{player} está bloqueado{who}.", "No puede entrar hasta que lo desbloquees en Jugadores."
        if category == "NOT_WHITELISTED":
            return f"{player} intentó entrar pero no está en la lista de amigos.", "Si lo conocés, agregalo en Jugadores y que vuelva a intentar."
        if category == "CLIENT_MISMATCH":
            return (
                f"{player} no pudo jugar porque su juego no coincide con el del servidor.",
                "Necesita la misma versión de Minecraft y los mismos mods. Pasale el paquete para amigos desde la página Mods.",
            )
        if category == "INVALID_DATA":
            return (
                f"{player} se desconectó porque sus datos de jugador están dañados.",
                "Puede ser un objeto con error en su inventario. Antes de tocar nada, hacé una copia del mundo.",
            )
        if category == "SERVER_CRASH":
            return (
                f"El servidor se cerró por un problema con el mod {mod}." if mod else f"El servidor se cerró de golpe mientras {player} jugaba.",
                "Volvé a encenderlo desde el inicio. Si se repite, buscá una actualización del mod o apagalo un rato.",
            )
        if category == "MOD_ERROR":
            return (
                f"{player} se desconectó por un problema con el mod {mod}." if mod else f"{player} se desconectó por un problema con un mod.",
                (f"Fijate en la página Mods si hay una actualización de {mod} y que tu amigo tenga la misma versión. Si sigue pasando, probá apagarlo."
                 if mod else "Fijate en la página Mods si hay actualizaciones y que tu amigo tenga los mismos mods. Si sigue pasando, probá apagar el último mod que agregaste.")
                + lag_note,
            )
        return f"{player} se desconectó por un motivo poco común.", "Mirá lo que estaba pasando y el registro completo para saber más." + lag_note

    # Queries

    async def list_events(
        self,
        player: str | None = None,
        category: str | None = None,
        search: str | None = None,
        limit: int = 100,
    ) -> PlayerCrashesListResponse:
        await self.initialize()
        # Pick up new disconnects from the running server without a manual scan.
        if self._current_latest_signature() != self._latest_signature:
            async with self._lock:
                await asyncio.to_thread(self._scan_logs_sync, latest_only=True)

        all_events = self._sorted_events()
        unique_players = sorted({event.player for event in all_events})
        filtered = []
        for event in all_events:
            if player and event.player.lower() != player.lower():
                continue
            if category and event.category != category:
                continue
            if search:
                needle = search.lower()
                haystack = [event.player, event.summary, event.category_label, event.suspected_mod or "", event.headline or ""]
                if not any(needle in value.lower() for value in haystack) and not any(needle in line.lower() for line in event.context_lines):
                    continue
            filtered.append(event)
            if len(filtered) >= limit:
                break

        categories_list = [{"key": key, "label": label} for key, (label, _) in _CATEGORIES.items() if key != "KICKED_BANNED"]
        return PlayerCrashesListResponse(
            total_events=len(all_events),
            players_count=len(unique_players),
            critical_count=sum(1 for event in all_events if event.severity == "error"),
            unique_players=unique_players,
            categories=categories_list,
            events=filtered,
        )

    async def get_event(self, event_id: str) -> PlayerCrashEvent | None:
        await self.initialize()
        return self._events.get(event_id)

    async def clear_events(self) -> None:
        async with self._lock:
            self._events.clear()
            if self._storage_file.is_file():
                self._storage_file.unlink()


player_crash_service = PlayerCrashService()
