"""History of the server ``mods`` folder with one-click rollback.

Before every change the panel makes to ``server/mods`` a snapshot of the folder
is recorded: each mod file with its sha256, size, metadata and enabled state,
plus the action about to happen. Changes made outside the panel (Explorer, a
launcher, another tool) are detected when the folder is listed and recorded as
"external" snapshots.

Storage lives in ``web_panel/.mod_history`` (host-local, never versioned):

* ``history.json``: the manifest. ``current`` is the folder as last seen and
  ``snapshots`` is the ordered history (oldest first). Written atomically.
* ``jars/<sha256>.jar``: a content-addressed cache. Every jar the folder holds
  is cached once (hard link when the volume allows it, copy otherwise), so a
  jar removed later, by the panel or by hand, can still be put back.

Rollback stages the target state next to the mods, verifies every sha256 and
only then swaps the files; any failure while swapping moves everything back.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from app.core.config import Settings, settings
from app.core.path_safety import is_safe_component, write_private_text
from app.services.runtime_guard import ServerState
from app.services.protected_paths import require_not_protected
from app.services.server_process import server_manager

logger = logging.getLogger(__name__)

HISTORY_DIRNAME: Final = ".mod_history"
DEFAULT_MAX_SNAPSHOTS: Final = 20
DEFAULT_MAX_HISTORY_BYTES: Final = 2 * 1024 * 1024 * 1024
_MANIFEST_VERSION: Final = 1
_HASH_CHUNK: Final = 1024 * 1024
_MAX_TEXT: Final = 200
_STALE_TEMP_SECONDS: Final = 3600
_STAGING_PREFIX: Final = ".panel-restore-"
_SNAPSHOT_ID: Final = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
_CACHED_JAR: Final = re.compile(r"^([0-9a-f]{64})\.jar$")
_MONTHS: Final = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
RESTORE_WHILE_RUNNING_MESSAGE: Final = "Apagá el servidor antes de volver atrás."


class ModHistoryError(RuntimeError):
    status_code = 400


class ModHistoryNotFoundError(ModHistoryError):
    status_code = 404


class ModHistoryConflictError(ModHistoryError):
    status_code = 409


def is_mod_filename(filename: str) -> bool:
    """Plain ``*.jar`` / ``*.jar.disabled`` name: no traversal, ADS or Windows device names."""
    return bool(
        filename
        and Path(filename).name == filename
        and is_safe_component(filename)
        and (filename.endswith(".jar") or filename.endswith(".jar.disabled"))
    )


def _move(source: Path, target: Path) -> None:
    """Rename one file inside the mods folder (tests patch this to inject failures)."""
    os.replace(source, target)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_with_hash(source: Path, target: Path) -> str:
    """Copy ``source`` to a new ``target`` and return the sha256 of what was written."""
    digest = hashlib.sha256()
    with source.open("rb") as reader, target.open("xb") as writer:
        while chunk := reader.read(_HASH_CHUNK):
            digest.update(chunk)
            writer.write(chunk)
        writer.flush()
        os.fsync(writer.fileno())
    return digest.hexdigest()


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:_MAX_TEXT] or None


def _stem(filename: str) -> str:
    return filename.removesuffix(".disabled").removesuffix(".jar")


def _default_metadata_reader(path: Path) -> dict[str, Any]:
    # Imported lazily: mod_service imports this module.
    from app.services.mod_service import ModService

    return ModService._extract_jar_metadata(path)


@dataclass(frozen=True, slots=True)
class ModFileRecord:
    """One file of the mods folder as it was at a given moment."""

    filename: str
    sha256: str
    size: int
    mtime_ns: int
    enabled: bool
    mod_id: str | None = None
    name: str | None = None
    version: str | None = None

    @property
    def display_name(self) -> str:
        return self.name or _stem(self.filename)

    @property
    def key(self) -> str:
        """Identity used to pair two versions of the same mod."""
        return f"id:{self.mod_id.casefold()}" if self.mod_id else f"file:{_stem(self.filename).casefold()}"

    def to_json(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "sha256": self.sha256,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "enabled": self.enabled,
            "mod_id": self.mod_id,
            "name": self.name,
            "version": self.version,
        }

    @classmethod
    def from_json(cls, raw: Any) -> ModFileRecord:
        if not isinstance(raw, dict):
            raise ValueError("record is not an object")
        filename = raw.get("filename")
        sha = raw.get("sha256")
        size = raw.get("size")
        mtime_ns = raw.get("mtime_ns", 0)
        if not isinstance(filename, str) or not is_mod_filename(filename):
            raise ValueError("unsafe filename")
        if not isinstance(sha, str) or not _SHA256.match(sha):
            raise ValueError("invalid sha256")
        if not isinstance(size, int) or size < 0 or not isinstance(mtime_ns, int):
            raise ValueError("invalid size")
        return cls(
            filename=filename,
            sha256=sha,
            size=size,
            mtime_ns=mtime_ns,
            enabled=filename.endswith(".jar"),
            mod_id=_clean_text(raw.get("mod_id")),
            name=_clean_text(raw.get("name")),
            version=_clean_text(raw.get("version")),
        )


@dataclass(slots=True)
class _Snapshot:
    id: str
    created_at: str
    action: str
    detail: dict[str, Any]
    files: list[ModFileRecord]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "action": self.action,
            "detail": self.detail,
            "files": [record.to_json() for record in self.files],
        }


@dataclass(slots=True)
class _Manifest:
    current: list[ModFileRecord] | None = None
    snapshots: list[_Snapshot] = field(default_factory=list)


@dataclass(slots=True)
class HistoryToken:
    """Handle returned by :meth:`ModHistoryService.begin` and passed to ``finish``."""

    snapshot_id: str
    before: list[ModFileRecord]
    detail: dict[str, Any]
    hints: list[ModFileRecord] = field(default_factory=list)


@dataclass(slots=True)
class StateDiff:
    added: list[ModFileRecord] = field(default_factory=list)
    removed: list[ModFileRecord] = field(default_factory=list)
    updated: list[tuple[ModFileRecord, ModFileRecord]] = field(default_factory=list)
    enabled: list[ModFileRecord] = field(default_factory=list)
    disabled: list[ModFileRecord] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.updated or self.enabled or self.disabled)


def diff_states(before: Iterable[ModFileRecord], after: Iterable[ModFileRecord]) -> StateDiff:
    """Describe how the folder went from ``before`` to ``after`` in mod terms."""
    old = list(before)
    new = list(after)
    result = StateDiff()

    # 1. Untouched files.
    new_exact = {(record.filename, record.sha256) for record in new}
    old_exact = {(record.filename, record.sha256) for record in old}
    old = [record for record in old if (record.filename, record.sha256) not in new_exact]
    new = [record for record in new if (record.filename, record.sha256) not in old_exact]

    # 2. Same bytes under another name: switched on/off (or just renamed).
    for record in list(old):
        match = next((candidate for candidate in new if candidate.sha256 == record.sha256), None)
        if match is None:
            continue
        old.remove(record)
        new.remove(match)
        if record.enabled and not match.enabled:
            result.disabled.append(match)
        elif not record.enabled and match.enabled:
            result.enabled.append(match)

    # 3. Same mod, other bytes: a new version.
    for record in list(old):
        match = next((candidate for candidate in new if candidate.key == record.key), None)
        if match is None:
            continue
        old.remove(record)
        new.remove(match)
        result.updated.append((record, match))

    result.removed.extend(old)
    result.added.extend(new)
    return result


def _same_state(first: Iterable[ModFileRecord], second: Iterable[ModFileRecord]) -> bool:
    return {(r.filename, r.sha256) for r in first} == {(r.filename, r.sha256) for r in second}


def _parse_moment(value: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def format_moment(value: str, now: datetime | None = None) -> str:
    """``"12 de octubre a las 18:04"`` in the host's local time (year only when it differs)."""
    moment = _parse_moment(value)
    if moment is None:
        return value
    local = moment.astimezone()
    reference = (now or datetime.now(UTC)).astimezone()
    year = f" de {local.year}" if local.year != reference.year else ""
    return f"{local.day} de {_MONTHS[local.month - 1]}{year} a las {local:%H:%M}"


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return f"{', '.join(parts[:-1])} y {parts[-1]}"


def _versioned(record: ModFileRecord) -> str:
    return f"{record.display_name} {record.version}" if record.version else record.display_name


def describe_change(action: str, detail: dict[str, Any], diff: StateDiff) -> str:
    """Plain-Spanish sentence for what happened right after a snapshot."""
    if action == "restore":
        target = detail.get("target_created_at")
        if isinstance(target, str):
            return f"Volviste a como estaban tus mods el {format_moment(target)}"
        return "Volviste a un punto anterior"

    external = action == "external"

    def verb(personal: str, singular: str, plural: str, count: int) -> str:
        if not external:
            return personal
        return singular if count == 1 else plural

    def subject(records: list[ModFileRecord]) -> str:
        return records[0].display_name if len(records) == 1 else f"{len(records)} mods"

    parts: list[str] = []
    if diff.updated:
        count = len(diff.updated)
        word = verb("actualizaste", "se actualizó", "se actualizaron", count)
        if count == 1:
            old, new = diff.updated[0]
            name = new.display_name
            if old.version and new.version and old.version != new.version:
                parts.append(f"{word} {name} de {old.version} a {new.version}")
            else:
                parts.append(f"{word} {name}")
        else:
            parts.append(f"{word} {count} mods")
    if diff.added:
        count = len(diff.added)
        main = detail.get("filename")
        main_record = next((r for r in diff.added if r.filename == main), None)
        if action == "install" and main_record is not None and count > 1:
            others = count - 1
            needs = "mod que necesita" if others == 1 else "mods que necesita"
            parts.append(f"instalaste {main_record.display_name} y {others} {needs}")
        else:
            personal = "instalaste" if action == "install" else "agregaste"
            parts.append(f"{verb(personal, 'se agregó', 'se agregaron', count)} {subject(diff.added)}")
    if diff.removed:
        count = len(diff.removed)
        parts.append(f"{verb('quitaste', 'se quitó', 'se quitaron', count)} {subject(diff.removed)}")
    if diff.enabled:
        count = len(diff.enabled)
        parts.append(f"{verb('encendiste', 'se encendió', 'se encendieron', count)} {subject(diff.enabled)}")
    if diff.disabled:
        count = len(diff.disabled)
        parts.append(f"{verb('apagaste', 'se apagó', 'se apagaron', count)} {subject(diff.disabled)}")

    if not parts:
        return "Cambios por fuera del panel" if external else "No cambió ningún mod"
    sentence = _join(parts)
    if external:
        return f"Cambios hechos por fuera del panel: {sentence}"
    return sentence[0].upper() + sentence[1:]


def describe_restore(diff: StateDiff) -> list[str]:
    """Lines explaining what going back to a snapshot would do to the current folder."""
    lines = [f"Vuelve {_versioned(record)}" for record in diff.added]
    lines += [f"Se quita {_versioned(record)}" for record in diff.removed]
    for current, target in diff.updated:
        if current.version and target.version and current.version != target.version:
            lines.append(f"{target.display_name} pasa de {current.version} a {target.version}")
        else:
            lines.append(f"{target.display_name} vuelve a la versión de ese momento")
    lines += [f"Se enciende {record.display_name}" for record in diff.enabled]
    lines += [f"Se apaga {record.display_name}" for record in diff.disabled]
    return lines


class ModHistoryService:
    """Records snapshots of ``server/mods`` and restores any of them."""

    def __init__(
        self,
        configured_settings: Settings = settings,
        manager: ServerState = server_manager,
        *,
        metadata_reader: Callable[[Path], dict[str, Any]] | None = None,
        max_snapshots: int = DEFAULT_MAX_SNAPSHOTS,
        max_history_bytes: int = DEFAULT_MAX_HISTORY_BYTES,
    ) -> None:
        self._settings = configured_settings
        self._manager = manager
        self._read_metadata = metadata_reader or _default_metadata_reader
        self._max_snapshots = max(1, max_snapshots)
        self._max_history_bytes = max(0, max_history_bytes)
        self._lock = threading.RLock()
        self._active = 0

    # ------------------------------------------------------------------ paths
    @property
    def mods_directory(self) -> Path:
        assert self._settings.mods_directory is not None
        return self._settings.mods_directory

    @property
    def history_directory(self) -> Path:
        assert self._settings.panel_directory is not None
        return self._settings.panel_directory / HISTORY_DIRNAME

    @property
    def jars_directory(self) -> Path:
        return self.history_directory / "jars"

    @property
    def manifest_path(self) -> Path:
        return self.history_directory / "history.json"

    def _jar_path(self, sha256: str) -> Path:
        if not _SHA256.match(sha256):
            raise ModHistoryError("El historial tiene un archivo con una suma de verificación inválida.")
        return self.jars_directory / f"{sha256}.jar"

    # --------------------------------------------------------------- manifest
    def _load(self) -> _Manifest:
        path = self.manifest_path
        if not path.is_file():
            return _Manifest()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not isinstance(raw.get("snapshots", []), list):
                raise ValueError("unexpected manifest shape")
        except (OSError, ValueError) as error:
            logger.warning("El historial de mods está dañado; se empieza uno nuevo: %s", error)
            with contextlib.suppress(OSError):
                path.replace(path.with_name(f"history.corrupt-{int(time.time())}.json"))
            return _Manifest()

        manifest = _Manifest()
        current = raw.get("current")
        if isinstance(current, list):
            try:
                manifest.current = [ModFileRecord.from_json(item) for item in current]
            except ValueError as error:
                logger.warning("Se ignora el estado guardado de la carpeta de mods: %s", error)
        for item in raw.get("snapshots", []):
            snapshot = self._parse_snapshot(item)
            if snapshot is not None:
                manifest.snapshots.append(snapshot)
        return manifest

    @staticmethod
    def _parse_snapshot(item: Any) -> _Snapshot | None:
        try:
            if not isinstance(item, dict):
                raise ValueError("snapshot is not an object")
            snapshot_id = item.get("id")
            created_at = item.get("created_at")
            action = item.get("action")
            if not isinstance(snapshot_id, str) or not _SNAPSHOT_ID.match(snapshot_id):
                raise ValueError("invalid id")
            if not isinstance(created_at, str) or _parse_moment(created_at) is None:
                raise ValueError("invalid date")
            if not isinstance(action, str) or not re.fullmatch(r"[a-z_]{1,32}", action):
                raise ValueError("invalid action")
            raw_detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
            detail = {
                str(key)[:64]: value if isinstance(value, int) else _clean_text(value)
                for key, value in raw_detail.items()
            }
            files = [ModFileRecord.from_json(record) for record in item.get("files", [])]
        except (ValueError, TypeError) as error:
            logger.warning("Se ignora un punto del historial de mods inválido: %s", error)
            return None
        return _Snapshot(snapshot_id, created_at, action, detail, files)

    def _save(self, manifest: _Manifest) -> None:
        payload = {
            "version": _MANIFEST_VERSION,
            "current": None if manifest.current is None else [r.to_json() for r in manifest.current],
            "snapshots": [snapshot.to_json() for snapshot in manifest.snapshots],
        }
        write_private_text(self.manifest_path, json.dumps(payload, ensure_ascii=False, indent=1))

    @staticmethod
    def _new_snapshot(action: str, detail: dict[str, Any], files: list[ModFileRecord]) -> _Snapshot:
        now = datetime.now(UTC)
        snapshot_id = f"{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
        return _Snapshot(snapshot_id, now.isoformat(), action, detail, list(files))

    # --------------------------------------------------------------- scanning
    def _scan(self, known: Iterable[ModFileRecord] = ()) -> list[ModFileRecord]:
        """Read the folder; only files whose name, size or mtime changed are hashed."""
        directory = self.mods_directory
        if not directory.is_dir():
            return []
        cache: dict[tuple[str, int, int], ModFileRecord] = {
            (record.filename.removesuffix(".disabled"), record.size, record.mtime_ns): record
            for record in known
        }
        records: list[ModFileRecord] = []
        with os.scandir(directory) as entries:
            for entry in entries:
                name = entry.name
                if not is_mod_filename(name):
                    continue
                try:
                    if not entry.is_file():
                        continue
                    stat = entry.stat()
                except OSError:
                    continue
                enabled = name.endswith(".jar")
                hit = cache.get((name.removesuffix(".disabled"), stat.st_size, stat.st_mtime_ns))
                if hit is not None:
                    records.append(replace(hit, filename=name, enabled=enabled))
                    continue
                path = Path(entry.path)
                try:
                    sha = _sha256_file(path)
                except OSError as error:
                    logger.warning("No se pudo leer %s para el historial: %s", name, error)
                    continue
                try:
                    metadata = self._read_metadata(path)
                except Exception:  # metadata is best effort
                    metadata = {}
                records.append(
                    ModFileRecord(
                        filename=name,
                        sha256=sha,
                        size=stat.st_size,
                        mtime_ns=stat.st_mtime_ns,
                        enabled=enabled,
                        mod_id=_clean_text(metadata.get("mod_id")),
                        name=_clean_text(metadata.get("display_name")),
                        version=_clean_text(metadata.get("version")),
                    )
                )
        records.sort(key=lambda record: record.filename.casefold())
        return records

    # ------------------------------------------------------------------ cache
    def _cache_records(self, records: Iterable[ModFileRecord]) -> None:
        """Keep one copy of every jar by content (hard link when possible)."""
        pending = [r for r in records if not (self.jars_directory / f"{r.sha256}.jar").is_file()]
        if not pending:
            return
        self.jars_directory.mkdir(parents=True, exist_ok=True)
        for record in pending:
            target = self._jar_path(record.sha256)
            if target.is_file():
                continue
            source = self.mods_directory / record.filename
            temporary = self.jars_directory / f".{record.sha256}.{uuid.uuid4().hex}.tmp"
            try:
                try:
                    os.link(source, temporary)
                except OSError:
                    if _copy_with_hash(source, temporary) != record.sha256:
                        logger.warning("%s cambió mientras se guardaba en el historial.", record.filename)
                        continue
                os.replace(temporary, target)
            except OSError as error:
                logger.warning("No se pudo guardar %s en el historial: %s", record.filename, error)
            finally:
                with contextlib.suppress(OSError):
                    temporary.unlink()

    def _apply_retention(self, manifest: _Manifest, protect: frozenset[str] = frozenset()) -> None:
        """Keep the newest snapshots within the count and size limits, then drop unused jars.

        Size counts only jars that are no longer in the mods folder: those are the
        bytes the history really costs. The newest snapshot is always kept, and a
        jar referenced by any kept snapshot is never deleted.
        """
        snapshots = manifest.snapshots
        current_shas = {record.sha256 for record in manifest.current or []}

        def removable() -> _Snapshot | None:
            return next((s for s in snapshots[:-1] if s.id not in protect), None)

        while len(snapshots) > self._max_snapshots and (victim := removable()) is not None:
            snapshots.remove(victim)
        while self._history_bytes(snapshots, current_shas) > self._max_history_bytes:
            victim = removable()
            if victim is None:
                break
            snapshots.remove(victim)
        self._collect_garbage(snapshots, current_shas)

    @staticmethod
    def _history_bytes(snapshots: list[_Snapshot], current_shas: set[str]) -> int:
        sizes: dict[str, int] = {}
        for snapshot in snapshots:
            for record in snapshot.files:
                if record.sha256 not in current_shas:
                    sizes[record.sha256] = record.size
        return sum(sizes.values())

    def _collect_garbage(self, snapshots: list[_Snapshot], current_shas: set[str]) -> None:
        directory = self.jars_directory
        if not directory.is_dir():
            return
        keep = set(current_shas)
        for snapshot in snapshots:
            keep.update(record.sha256 for record in snapshot.files)
        now = time.time()
        with os.scandir(directory) as entries:
            for entry in entries:
                match = _CACHED_JAR.match(entry.name)
                try:
                    if match is not None:
                        if match.group(1) not in keep:
                            os.unlink(entry.path)
                    elif entry.name.endswith(".tmp") and now - entry.stat().st_mtime > _STALE_TEMP_SECONDS:
                        os.unlink(entry.path)
                except OSError as error:
                    logger.debug("No se pudo limpiar %s del historial: %s", entry.name, error)

    # ------------------------------------------------------------- recording
    def begin(
        self,
        action: str,
        detail: dict[str, Any] | None = None,
        *,
        protect: frozenset[str] = frozenset(),
    ) -> HistoryToken:
        """Record the folder as it is right before ``action`` changes it."""
        with self._lock:
            self._active += 1
            try:
                manifest = self._load()
                current = self._scan(manifest.current or [])
                if manifest.current is not None and not _same_state(manifest.current, current):
                    manifest.snapshots.append(self._new_snapshot("external", {}, manifest.current))
                snapshot = self._new_snapshot(action, dict(detail or {}), current)
                manifest.snapshots.append(snapshot)
                manifest.current = current
                self._cache_records(current)
                self._apply_retention(manifest, protect | {snapshot.id})
                self._save(manifest)
            except BaseException:
                self._active -= 1
                raise
        return HistoryToken(snapshot.id, current, snapshot.detail)

    def finish(self, token: HistoryToken) -> None:
        """Store the folder after the action; a no-op action leaves no snapshot behind."""
        with self._lock:
            try:
                manifest = self._load()
                after = self._scan([*token.before, *token.hints])
                snapshot = next((s for s in manifest.snapshots if s.id == token.snapshot_id), None)
                if snapshot is not None:
                    snapshot.detail.update(token.detail)
                    if _same_state(token.before, after) and manifest.snapshots[-1] is snapshot:
                        manifest.snapshots.pop()
                manifest.current = after
                self._cache_records(after)
                self._apply_retention(manifest)
                self._save(manifest)
            finally:
                self._active = max(0, self._active - 1)

    def record_external_changes(self) -> bool:
        """Record a snapshot when the folder changed outside the panel. Returns whether it did."""
        if self._active:
            return False
        with self._lock:
            if self._active:
                return False
            manifest = self._load()
            previous = manifest.current
            current = self._scan(previous or [])
            if previous is None:
                manifest.current = current
                self._cache_records(current)
                self._save(manifest)
                return False
            if _same_state(previous, current):
                if previous != current:
                    manifest.current = current
                    self._save(manifest)
                return False
            manifest.snapshots.append(self._new_snapshot("external", {}, previous))
            manifest.current = current
            self._cache_records(current)
            self._apply_retention(manifest)
            self._save(manifest)
            return True

    # --------------------------------------------------------------- reading
    def _is_available(self, record: ModFileRecord, current_shas: set[str]) -> bool:
        return record.sha256 in current_shas or self._jar_path(record.sha256).is_file()

    def _entry(self, snapshot: _Snapshot, after: list[ModFileRecord], current_shas: set[str]) -> dict[str, Any]:
        diff = diff_states(snapshot.files, after)
        return {
            "id": snapshot.id,
            "created_at": snapshot.created_at,
            "action": snapshot.action,
            "summary": describe_change(snapshot.action, snapshot.detail, diff),
            "added": len(diff.added),
            "removed": len(diff.removed),
            "updated": len(diff.updated),
            "toggled": len(diff.enabled) + len(diff.disabled),
            "mod_count": len(snapshot.files),
            "restorable": all(self._is_available(r, current_shas) for r in snapshot.files),
        }

    def _load_fresh(self) -> _Manifest:
        try:
            self.record_external_changes()
        except Exception as error:  # history must stay readable even if the folder is not
            logger.warning("No se pudo revisar la carpeta de mods: %s", error)
        with self._lock:
            return self._load()

    def list_history(self) -> list[dict[str, Any]]:
        """Snapshots newest first, each with what changed right after it."""
        manifest = self._load_fresh()
        current = manifest.current or []
        current_shas = {record.sha256 for record in current}
        entries = []
        for index, snapshot in enumerate(manifest.snapshots):
            following = manifest.snapshots[index + 1].files if index + 1 < len(manifest.snapshots) else current
            entries.append(self._entry(snapshot, following, current_shas))
        entries.reverse()
        return entries

    def get_history(self, snapshot_id: str) -> dict[str, Any]:
        """One snapshot plus what going back to it would change in the current folder."""
        self._validate_id(snapshot_id)
        manifest = self._load_fresh()
        index = next((i for i, s in enumerate(manifest.snapshots) if s.id == snapshot_id), None)
        if index is None:
            raise ModHistoryNotFoundError("No encontramos ese punto del historial.")
        snapshot = manifest.snapshots[index]
        current = manifest.current or []
        current_shas = {record.sha256 for record in current}
        following = manifest.snapshots[index + 1].files if index + 1 < len(manifest.snapshots) else current
        entry = self._entry(snapshot, following, current_shas)
        restore_diff = diff_states(current, snapshot.files)

        def ref(record: ModFileRecord) -> dict[str, Any]:
            return {"filename": record.filename, "name": record.display_name, "version": record.version}

        entry["changes"] = {
            "added": [ref(r) for r in restore_diff.added],
            "removed": [ref(r) for r in restore_diff.removed],
            "updated": [
                {
                    "name": new.display_name,
                    "from_filename": old.filename,
                    "to_filename": new.filename,
                    "from_version": old.version,
                    "to_version": new.version,
                }
                for old, new in restore_diff.updated
            ],
            "enabled": [ref(r) for r in restore_diff.enabled],
            "disabled": [ref(r) for r in restore_diff.disabled],
        }
        entry["lines"] = describe_restore(restore_diff)
        entry["missing"] = [ref(r) for r in snapshot.files if not self._is_available(r, current_shas)]
        return entry

    @staticmethod
    def _validate_id(snapshot_id: str) -> None:
        if not isinstance(snapshot_id, str) or not _SNAPSHOT_ID.match(snapshot_id):
            raise ModHistoryNotFoundError("No encontramos ese punto del historial.")

    # --------------------------------------------------------------- restore
    def restore(self, snapshot_id: str) -> dict[str, Any]:
        """Put ``server/mods`` back exactly as it was in ``snapshot_id``.

        The current folder is recorded first, so the rollback can be undone.
        """
        self._validate_id(snapshot_id)
        if self._manager.is_running:
            raise ModHistoryConflictError(RESTORE_WHILE_RUNNING_MESSAGE)
        with self._lock:
            manifest = self._load()
            target = next((s for s in manifest.snapshots if s.id == snapshot_id), None)
            if target is None:
                raise ModHistoryNotFoundError("No encontramos ese punto del historial.")
            records = list(target.files)
            names = [record.filename.casefold() for record in records]
            if len(set(names)) != len(names):
                raise ModHistoryError("Ese punto del historial tiene archivos repetidos; no se puede usar.")
            when = format_moment(target.created_at)

            token = self.begin(
                "restore",
                {"target_id": target.id, "target_created_at": target.created_at},
                protect=frozenset({target.id}),
            )
            token.hints = records
            try:
                changed = self._apply_state(records, token.before)
            finally:
                self.finish(token)
            undo_id = token.snapshot_id if changed else None

        if not changed:
            return {"message": "Tus mods ya estaban así.", "undo_id": None, "restored_count": len(records)}
        return {
            "message": f"Listo. Tus mods quedaron como estaban el {when}.",
            "undo_id": undo_id,
            "restored_count": len(records),
        }

    def _safe_child(self, directory: Path, filename: str) -> Path:
        if not is_mod_filename(filename):
            raise ModHistoryError("El historial tiene un nombre de archivo inválido.")
        candidate = (directory / filename).resolve()
        if candidate.parent != directory.resolve() or not candidate.is_relative_to(self.mods_directory.resolve()):
            raise ModHistoryError("El historial tiene una ruta inválida.")
        return candidate

    def _apply_state(self, records: list[ModFileRecord], current: list[ModFileRecord]) -> bool:
        """Swap the folder to ``records``; on any failure the folder is left as it was."""
        mods = self.mods_directory
        mods.mkdir(parents=True, exist_ok=True)
        target_exact = {(r.filename, r.sha256) for r in records}
        current_exact = {(r.filename, r.sha256) for r in current}
        to_place = [r for r in records if (r.filename, r.sha256) not in current_exact]
        to_park = [r for r in current if (r.filename, r.sha256) not in target_exact]
        require_not_protected(*(mods / r.filename for r in [*to_place, *to_park]), configured=self._settings)
        if not to_place and not to_park:
            return False
        # Files that leave the folder must be kept in the cache, or the rollback could not be undone.
        self._cache_records(to_park)
        if not all(self._jar_path(record.sha256).is_file() for record in to_park):
            raise ModHistoryError(
                "No pudimos guardar una copia de cómo están tus mods ahora, así que no se cambió nada."
            )

        sources_by_sha: dict[str, list[Path]] = {}
        for record in current:
            sources_by_sha.setdefault(record.sha256, []).append(self._safe_child(mods, record.filename))

        marker = uuid.uuid4().hex
        staging = mods / f"{_STAGING_PREFIX}{marker}-new"
        parking = mods / f"{_STAGING_PREFIX}{marker}-old"
        staging.mkdir()
        parked: list[str] = []
        placed: list[str] = []
        parking_safe = True
        try:
            # 1. Stage every file that has to appear, verifying its bytes.
            for record in to_place:
                self._materialize(record, self._safe_child(staging, record.filename), sources_by_sha)

            # 2. Swap: park what has to go, then move the staged files in.
            parking.mkdir()
            try:
                for record in to_park:
                    _move(self._safe_child(mods, record.filename), self._safe_child(parking, record.filename))
                    parked.append(record.filename)
                for record in to_place:
                    destination = self._safe_child(mods, record.filename)
                    if destination.exists():
                        raise ModHistoryError(f"Ya hay un archivo llamado {record.filename}.")
                    _move(self._safe_child(staging, record.filename), destination)
                    placed.append(record.filename)
            except Exception as error:
                parking_safe = self._undo_swap(staging, parking, placed, parked)
                logger.warning("Falló la vuelta atrás de mods; se deshicieron los cambios: %s", error)
                raise ModHistoryError("No se pudo volver atrás. Tus mods quedaron como estaban.") from error
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            if parking_safe:
                shutil.rmtree(parking, ignore_errors=True)
            else:
                logger.error("Quedaron mods apartados en %s; movelos a mano a la carpeta de mods.", parking)
        return True

    def _undo_swap(self, staging: Path, parking: Path, placed: list[str], parked: list[str]) -> bool:
        mods = self.mods_directory
        restored_all = True
        for filename in reversed(placed):
            try:
                _move(mods / filename, staging / filename)
            except OSError as error:
                restored_all = False
                logger.error("No se pudo retirar %s: %s", filename, error)
        for filename in reversed(parked):
            try:
                _move(parking / filename, mods / filename)
            except OSError as error:
                restored_all = False
                logger.error("No se pudo devolver %s: %s", filename, error)
        return restored_all

    def _materialize(self, record: ModFileRecord, destination: Path, sources_by_sha: dict[str, list[Path]]) -> None:
        candidates: list[Path] = []
        cached = self._jar_path(record.sha256)
        if cached.is_file():
            candidates.append(cached)
        candidates.extend(sources_by_sha.get(record.sha256, []))
        for source in candidates:
            try:
                digest = _copy_with_hash(source, destination)
            except OSError as error:
                logger.warning("No se pudo copiar %s desde %s: %s", record.filename, source.name, error)
                with contextlib.suppress(OSError):
                    destination.unlink()
                continue
            if digest == record.sha256:
                with contextlib.suppress(OSError):
                    os.utime(destination, ns=(record.mtime_ns, record.mtime_ns))
                return
            destination.unlink()
        raise ModHistoryError(
            f"No encontramos una copia sana de {record.display_name}. No se cambió nada."
        )
