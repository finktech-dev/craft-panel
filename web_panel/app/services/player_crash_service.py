"""Servicio para registrar, clasificar y analizar desconexiones y crashes de jugadores."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings, settings
from app.schemas.player_crashes import PlayerCrashEvent, PlayerCrashesListResponse

# Patrones para detectar desconexiones en logs de Minecraft.
# NOTA: Se eliminó el patrón de VoiceChat ("Disconnecting client ...") para evitar falsos positivos y duplicados.
_DISCONNECT_PATTERNS = [
    re.compile(r"ServerGamePacketListenerImpl/\]:\s*([a-zA-Z0-9_]{3,16})\s+lost connection:\s*(.*)", re.I),
    re.compile(r"name=([a-zA-Z0-9_]{3,16})[,\s].*lost connection:\s*(.*)", re.I),
    re.compile(r"(?:^|\]:\s*)([a-zA-Z0-9_]{3,16})\s+lost connection:\s*(.*)", re.I),
]

_CATEGORY_MAP = [
    ("NORMAL_DISCONNECT", "Desconexión Normal", "info", re.compile(r"^(?:disconnected|quitting|left the game|server closed)\.?$", re.I)),
    ("TIMEOUT", "Tiempo de Espera Agotado", "warning", re.compile(r"\b(?:timed\s*out|read timed out|connection reset)\b", re.I)),
    ("KICKED_BANNED", "Expulsión o Baneo", "warning", re.compile(r"\b(?:kicked|banned|not whitelisted|expulsado|baneado)\b|/kick", re.I)),
    ("INVALID_DATA", "Datos Inválidos / Corrupción", "error", re.compile(r"invalid player data|nbt|corrupt|tag not found", re.I)),
    ("CLIENT_MISMATCH", "Cliente Incompatible / Versión", "warning", re.compile(r"incompatible client|please use neoforge|version mismatch|missing mod|channels \[.*\] are not present", re.I)),
    ("MOD_ERROR", "Error de Mod / Capacidad", "error", re.compile(r"capability|illegalstateexception|nullpointerexception|mixin|modloadingexception|registry|classnotfoundexception|nosuchmethoderror", re.I)),
    ("SERVER_CRASH", "Caída del Servidor", "error", re.compile(r"crash report has been saved|encountered an unexpected exception\s+net\.minecraft|a single server tick took", re.I)),
]

# Expresiones para clasificación precisa de la causa en reason_detail
_KICK_RX = re.compile(r"\b(?:kicked|banned|not whitelisted|expulsado|baneado)\b|/kick", re.I)
_TIMEOUT_RX = re.compile(r"\b(?:timed\s*out|read timed out|connection reset)\b", re.I)
_NORMAL_DISCONNECT_RX = re.compile(r"^(?:disconnected|quitting|left the game|server closed)\.?$", re.I)

# Patrones de apagado para ignorar en la detección de causas y mods sospechosos
_SHUTDOWN_LINE_RX = re.compile(
    r"stopping (?:the )?server|starting shutdown process|closing storage|goodbye!|saving (?:chunks|players|worlds|level)",
    re.I,
)

# Patrones para identificar líneas de error / excepción / crash / stacktrace
_ERROR_LINE_RX = re.compile(
    r"/(?:ERROR|FATAL)\]"
    r"|\b(?:[a-zA-Z0-9_.]+(?:Exception|Error)|CrashReport|Crash)\b"
    r"|^\s*(?:at\s+[a-zA-Z0-9_$.]+|Caused by:)"
    r"|\bat\s+(?:net|com|org|dev|de|me|io)\.[a-zA-Z0-9_.]+",
    re.I,
)

# Patrones estrictos para mods conocidos (delimitados por palabra o logger/paquete exacto)
_KNOWN_MOD_PATTERNS: list[tuple[str, list[re.Pattern]]] = [
    (
        "Create",
        [
            re.compile(r"com\.simibubi\.create", re.I),
            re.compile(r"\[create(?:/[^\]]*)?\]", re.I),
            re.compile(r"\bcreate-[0-9.]+", re.I),
            re.compile(r"\bcreate\b", re.I),
        ],
    ),
    (
        "LuckPerms",
        [
            re.compile(r"(?:net|me)\.luck(?:o)?\.luckperms", re.I),
            re.compile(r"\[luckperms(?:/[^\]]*)?\]", re.I),
            re.compile(r"\bluckperms\b", re.I),
        ],
    ),
    (
        "Point Blank",
        [
            re.compile(r"com\.vicmatskiv\.pointblank", re.I),
            re.compile(r"\[pointblank(?:/[^\]]*)?\]", re.I),
            re.compile(r"\bpointblank\b", re.I),
        ],
    ),
    (
        "Balm",
        [
            re.compile(r"net\.blay09\.mods\.balm", re.I),
            re.compile(r"\[balm(?:/[^\]]*)?\]", re.I),
            re.compile(r"\bbalm\b", re.I),
        ],
    ),
    (
        "Voice Chat",
        [
            re.compile(r"de\.maxhenkel\.voicechat", re.I),
            re.compile(r"\[voicechat(?:/[^\]]*)?\]", re.I),
            re.compile(r"\bvoicechat\b", re.I),
        ],
    ),
    (
        "FTB Chunks",
        [
            re.compile(r"dev\.ftb\.mods\.ftbchunks", re.I),
            re.compile(r"\[ftbchunks(?:/[^\]]*)?\]", re.I),
            re.compile(r"\bftbchunks\b", re.I),
        ],
    ),
    (
        "FTB Quests",
        [
            re.compile(r"dev\.ftb\.mods\.ftbquests", re.I),
            re.compile(r"\[ftbquests(?:/[^\]]*)?\]", re.I),
            re.compile(r"\bftbquests\b", re.I),
        ],
    ),
    (
        "FTB Teams",
        [
            re.compile(r"dev\.ftb\.mods\.ftbteams", re.I),
            re.compile(r"\[ftbteams(?:/[^\]]*)?\]", re.I),
            re.compile(r"\bftbteams\b", re.I),
        ],
    ),
    (
        "Sophisticated Backpacks",
        [
            re.compile(r"net\.p3pp3rf1y\.sophisticatedbackpacks", re.I),
            re.compile(r"\[sophisticatedbackpacks(?:/[^\]]*)?\]", re.I),
            re.compile(r"\bsophisticatedbackpacks\b", re.I),
        ],
    ),
    (
        "Curios API",
        [
            re.compile(r"top\.theillusivec4\.curios", re.I),
            re.compile(r"\[curios(?:/[^\]]*)?\]", re.I),
            re.compile(r"\bcurios\b", re.I),
        ],
    ),
    (
        "Farmer's Delight",
        [
            re.compile(r"vectorwing\.farmersdelight", re.I),
            re.compile(r"\[farmersdelight(?:/[^\]]*)?\]", re.I),
            re.compile(r"\bfarmersdelight\b", re.I),
        ],
    ),
    (
        "JourneyMap",
        [
            re.compile(r"journeymap", re.I),
            re.compile(r"\[journeymap(?:/[^\]]*)?\]", re.I),
            re.compile(r"\bjourneymap\b", re.I),
        ],
    ),
]

_JAR_RX = re.compile(r"(?:~\[|\b)([a-zA-Z0-9_\-\.]+)\.jar", re.I)
_IGNORED_JARS = {
    "minecraft", "server", "client", "neoforge", "forge",
    "minecraftforge", "java", "rt", "fabric", "quilt",
    "main", "libraries", "bundler",
}


class PlayerCrashService:
    def __init__(self, configured_settings: Settings = settings) -> None:
        self._settings = configured_settings
        self._storage_file = Path(self._settings.panel_directory or ".") / ".player_crashes.json"
        self._events: dict[str, PlayerCrashEvent] = {}
        self._lock = asyncio.Lock()
        self._initialized = False

    @property
    def logs_dir(self) -> Path:
        assert self._settings.server_directory
        return self._settings.server_directory / "logs"

    def _load_storage(self) -> None:
        if self._storage_file.is_file():
            try:
                data = json.loads(self._storage_file.read_text(encoding="utf-8"))
                for raw in data:
                    evt = PlayerCrashEvent(**raw)
                    self._events[evt.id] = evt
            except Exception:
                pass

    def _save_storage(self) -> None:
        try:
            items = [evt.model_dump() for evt in sorted(self._events.values(), key=lambda e: e.timestamp, reverse=True)]
            self._storage_file.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

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
            new_count = await asyncio.to_thread(self._scan_logs_sync)
            return new_count

    def _scan_logs_sync(self) -> int:
        if not self.logs_dir.is_dir():
            return 0

        # Escanear latest.log y los últimos 10 archivos comprimidos .log.gz
        candidates = []
        latest = self.logs_dir / "latest.log"
        if latest.is_file():
            candidates.append(latest)
        gz_files = sorted(self.logs_dir.glob("*.log.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
        candidates.extend(gz_files[:10])

        new_events = 0
        for log_file in candidates:
            try:
                if log_file.suffix == ".gz":
                    lines = gzip.decompress(log_file.read_bytes()).decode("utf-8", "replace").splitlines()
                else:
                    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                
                events_found = self._parse_lines(lines, log_file.name)
                for evt in events_found:
                    if evt.id not in self._events:
                        self._events[evt.id] = evt
                        new_events += 1
            except Exception:
                continue

        if new_events > 0:
            self._save_storage()
        return new_events

    def _find_suspected_mod(self, reason_detail: str, context_block: list[str]) -> str | None:
        candidate_lines: list[str] = []
        if reason_detail and not _SHUTDOWN_LINE_RX.search(reason_detail):
            candidate_lines.append(reason_detail)
        candidate_lines.extend(context_block)

        # 1. Ignorar completamente líneas de apagado del servidor
        valid_lines = [line for line in candidate_lines if not _SHUTDOWN_LINE_RX.search(line)]

        # 2. Solo marcar si hay una excepción, error o crash
        error_lines = [line for line in valid_lines if _ERROR_LINE_RX.search(line)]
        if not error_lines:
            return None

        # 3. Buscar en mods conocidos con patrones rigurosos
        for mod_name, patterns in _KNOWN_MOD_PATTERNS:
            for pat in patterns:
                for line in error_lines:
                    if pat.search(line):
                        return mod_name

        # 4. Buscar mención a archivos .jar en las líneas de error/stacktrace
        for line in error_lines:
            jar_matches = _JAR_RX.findall(line)
            for jar in jar_matches:
                j_lower = jar.lower()
                if j_lower not in _IGNORED_JARS and not j_lower.startswith(("minecraft", "neoforge", "forge-", "server")):
                    return jar

        # 5. Buscar paquete en stacktrace (ej. at com.author.modname.Class...)
        for line in error_lines:
            m = re.search(r"^\s*at\s+([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)", line)
            if m:
                g1, g2, g3 = m.group(1).lower(), m.group(2).lower(), m.group(3).lower()
                if g1 in ("com", "net", "org", "dev", "de", "me", "io"):
                    if g2 not in ("minecraft", "mojang", "google", "apache", "netty", "sun", "java", "neoforged"):
                        return g3.capitalize() if g2 in ("github", "gitlab") else g2.capitalize()

        return None

    def _classify_event(
        self,
        reason_detail: str,
        context_block: list[str],
    ) -> tuple[str, str, str, str | None, str | None]:
        reason_clean = (reason_detail or "").strip()

        # 1. Kicked / Banned explícito
        if _KICK_RX.search(reason_clean):
            return (
                "KICKED_BANNED",
                "Expulsión o Baneo",
                "warning",
                None,
                "El jugador fue expulsado o baneado por un operador o moderador.",
            )

        # 2. Timeout explícito
        if _TIMEOUT_RX.search(reason_clean):
            return (
                "TIMEOUT",
                "Tiempo de Espera Agotado",
                "warning",
                None,
                "El jugador perdió conexión por lag o caída de paquetes de red.",
            )

        # 3. Desconexión normal o voluntaria explícita
        if _NORMAL_DISCONNECT_RX.search(reason_clean) or (
            re.match(r"^(?:disconnected|quitting|left the game|server closed)\b", reason_clean, re.I)
            and not re.search(r"exception|error|crash|fatal", reason_clean, re.I)
        ):
            return (
                "NORMAL_DISCONNECT",
                "Desconexión Normal",
                "info",
                None,
                None,
            )

        # 4. Si la desconexión no fue voluntaria ni timeout explícito, evaluar contexto
        clean_context = [line for line in context_block if not _SHUTDOWN_LINE_RX.search(line)]
        combined_evidence = f"{reason_clean}\n" + "\n".join(clean_context)

        suspected_mod = self._find_suspected_mod(reason_clean, clean_context)

        if re.search(r"invalid player data|nbt|corrupt|tag not found", combined_evidence, re.I):
            category = "INVALID_DATA"
            cat_label = "Datos Inválidos / Corrupción"
            severity = "error"
            suggestion = "Revisar los datos NBT del jugador en playerdata/ o reiniciar su inventario si tiene un ítem con error."
        elif re.search(r"incompatible client|please use neoforge|version mismatch|missing mod|channels \[.*\] are not present", combined_evidence, re.I):
            category = "CLIENT_MISMATCH"
            cat_label = "Cliente Incompatible / Versión"
            severity = "warning"
            suggestion = "Verificar que el jugador tenga instalada la versión exacta del modpack o cliente compatible con el servidor."
        elif re.search(r"crash report has been saved|encountered an unexpected exception\s+net\.minecraft|a single server tick took", combined_evidence, re.I):
            category = "SERVER_CRASH"
            cat_label = "Caída del Servidor"
            severity = "error"
            suggestion = f"El servidor sufrió una caída mientras el jugador estaba conectado ({suspected_mod or 'Ver logs'})."
        elif re.search(r"capability|illegalstateexception|nullpointerexception|mixin|modloadingexception|registry|classnotfoundexception|nosuchmethoderror", combined_evidence, re.I):
            category = "MOD_ERROR"
            cat_label = "Error de Mod / Capacidad"
            severity = "error"
            suggestion = f"Conflicto de mod detectado ({suspected_mod or 'Librería/Capacidad'}). Verificar que el mod esté actualizado."
        elif _TIMEOUT_RX.search(combined_evidence):
            category = "TIMEOUT"
            cat_label = "Tiempo de Espera Agotado"
            severity = "warning"
            suggestion = "El jugador perdió conexión por lag o caída de paquetes de red."
        elif _KICK_RX.search(combined_evidence):
            category = "KICKED_BANNED"
            cat_label = "Expulsión o Baneo"
            severity = "warning"
            suggestion = "El jugador fue expulsado o baneado del servidor."
        elif suspected_mod:
            category = "MOD_ERROR"
            cat_label = "Error de Mod / Capacidad"
            severity = "error"
            suggestion = f"Conflicto de mod detectado ({suspected_mod}). Verificar que el mod esté actualizado."
        elif re.search(r"exception|fatal", combined_evidence, re.I):
            category = "MOD_ERROR"
            cat_label = "Error de Mod / Capacidad"
            severity = "error"
            suggestion = "Se detectó un error inesperado al procesar la conexión del jugador."
        else:
            category = "UNKNOWN"
            cat_label = "Desconexión no clasificada"
            severity = "warning"
            suggestion = None

        if category == "NORMAL_DISCONNECT":
            suspected_mod = None

        return category, cat_label, severity, suspected_mod, suggestion

    def _parse_lines(self, lines: list[str], filename: str) -> list[PlayerCrashEvent]:
        events: list[PlayerCrashEvent] = []
        total = len(lines)

        for i, line in enumerate(lines):
            for pat in _DISCONNECT_PATTERNS:
                match = pat.search(line)
                if not match:
                    continue

                player = match.group(1).strip()
                reason_detail = match.group(2).strip() if match.lastindex and match.lastindex >= 2 else "Desconexión"

                # Extraer contexto: 35 líneas anteriores y 10 posteriores
                start_idx = max(0, i - 35)
                end_idx = min(total, i + 10)
                context_block = lines[start_idx:end_idx]

                category, cat_label, severity, suspected_mod, suggestion = self._classify_event(
                    reason_detail, context_block
                )

                # Extraer timestamp
                ts_match = re.search(
                    r"\[(\d{1,2}[a-zA-Z]{3,4}\d{4}\s+\d{2}:\d{2}:\d{2}(?:\.\d{3})?|\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{3})?|\d{2}:\d{2}:\d{2})\]",
                    line,
                )
                if ts_match:
                    raw_ts = ts_match.group(1)
                    timestamp = raw_ts
                else:
                    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

                # Generar ID estable basado en jugador + timestamp + línea
                event_hash = hashlib.sha256(f"{filename}:{i}:{player}:{reason_detail}".encode("utf-8")).hexdigest()[:12]
                avatar_url = f"https://mc-heads.net/avatar/{player}/64"

                events.append(
                    PlayerCrashEvent(
                        id=event_hash,
                        player=player,
                        avatar_url=avatar_url,
                        category=category,
                        category_label=cat_label,
                        severity=severity,
                        summary=reason_detail or "El jugador perdió la conexión",
                        timestamp=timestamp,
                        file_source=filename,
                        context_lines=context_block,
                        suspected_mod=suspected_mod,
                        suggestion=suggestion,
                    )
                )
                break

        return events

    async def list_events(
        self,
        player: str | None = None,
        category: str | None = None,
        search: str | None = None,
        limit: int = 100,
    ) -> PlayerCrashesListResponse:
        await self.initialize()

        all_events = sorted(self._events.values(), key=lambda e: e.timestamp, reverse=True)

        filtered = []
        unique_players = sorted({e.player for e in all_events})

        for evt in all_events:
            if player and evt.player.lower() != player.lower():
                continue
            if category and evt.category != category:
                continue
            if search:
                s_lower = search.lower()
                matches_search = (
                    s_lower in evt.player.lower()
                    or s_lower in evt.summary.lower()
                    or s_lower in evt.category_label.lower()
                    or (evt.suspected_mod and s_lower in evt.suspected_mod.lower())
                    or any(s_lower in line.lower() for line in evt.context_lines)
                )
                if not matches_search:
                    continue

            filtered.append(evt)
            if len(filtered) >= limit:
                break

        categories_list = [
            {"key": cat_key, "label": label}
            for cat_key, label, _, _ in _CATEGORY_MAP
        ]

        critical_count = sum(1 for e in all_events if e.severity == "error")

        return PlayerCrashesListResponse(
            total_events=len(all_events),
            players_count=len(unique_players),
            critical_count=critical_count,
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
