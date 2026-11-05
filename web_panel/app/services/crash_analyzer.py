"""Reads NeoForge crash reports and explains them simply."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings, settings
from app.schemas.crash import CrashReportSummary

_DESCRIPTION_PATTERN = re.compile(r"^Description:\s*(.+)$", re.MULTILINE)
_CAUSE_PATTERN = re.compile(r"^(?:Caused by:|Failure message:)\s*(.+)$", re.MULTILINE)
_MOD_FILE_PATTERN = re.compile(r"(?:Mod File|File):\s*([^\s]+?\.jar)\b", re.IGNORECASE)
_MOD_SECTION_PATTERN = re.compile(r"^\s*--\s*MOD\s+([^\s-]+)", re.MULTILINE | re.IGNORECASE)


class CrashAnalyzer:
    def __init__(self, configured_settings: Settings = settings) -> None:
        self._settings = configured_settings

    @property
    def crash_reports_directory(self) -> Path:
        assert self._settings.crash_reports_directory is not None
        return self._settings.crash_reports_directory

    async def get_latest_crash_report(self, since: float | None = None) -> CrashReportSummary | None:
        """Newest report, or ``None``; with ``since`` (epoch seconds) older reports are ignored."""
        if not self.crash_reports_directory.is_dir():
            return None
        report = await asyncio.to_thread(self._find_latest_report, since)
        if report is None:
            return None
        contents = await asyncio.to_thread(report.read_text, encoding="utf-8", errors="replace")
        return self._analyze(report, contents)

    def _find_latest_report(self, since: float | None = None) -> Path | None:
        reports = [path for path in self.crash_reports_directory.glob("*.txt") if path.is_file()]
        latest = max(reports, key=lambda path: path.stat().st_mtime, default=None)
        # A report from an earlier session is not the cause of this shutdown.
        if latest is not None and since is not None and latest.stat().st_mtime < since:
            return None
        return latest

    @staticmethod
    def _analyze(report: Path, contents: str) -> CrashReportSummary:
        description = _first_match(_DESCRIPTION_PATTERN, contents)
        trace_cause = _first_match(_CAUSE_PATTERN, contents)
        suspected_mod = _find_suspected_mod(contents)
        cause, suggestion = _diagnose(description, trace_cause, suspected_mod, contents)
        return CrashReportSummary(
            filename=report.name,
            timestamp=datetime.fromtimestamp(report.stat().st_mtime, UTC).isoformat(),
            cause=cause,
            suspected_mod=suspected_mod,
            suggestion=suggestion,
        )


def _first_match(pattern: re.Pattern[str], contents: str) -> str | None:
    match = pattern.search(contents)
    return match.group(1).strip() if match else None


def _find_suspected_mod(contents: str) -> str | None:
    match = _MOD_FILE_PATTERN.search(contents)
    if match:
        return Path(match.group(1)).name
    match = _MOD_SECTION_PATTERN.search(contents)
    return match.group(1).strip() if match else None


def _diagnose(
    description: str | None,
    trace_cause: str | None,
    suspected_mod: str | None,
    contents: str,
) -> tuple[str, str]:
    evidence = f"{description or ''}\n{trace_cause or ''}\n{contents}".casefold()
    if "outofmemoryerror" in evidence or "java heap space" in evidence:
        return (
            "Al juego le faltó memoria para trabajar.",
            "Si pasa seguido, usá menos mods pesados o cerrá otros programas de la computadora.",
        )
    if any(term in evidence for term in ("zipexception", "corrupt", "invalid or corrupt jar")):
        return (
            "Un archivo de un mod está roto o quedó incompleto.",
            "Bajá de nuevo ese mod desde su página oficial y fijate que sea para la misma versión de tu servidor.",
        )
    if suspected_mod or any(term in evidence for term in ("modloadingexception", "mixin", "failed to load mod")):
        return (
            f"Parece que {f'el mod {suspected_mod}' if suspected_mod else 'un mod'} no es compatible.",
            "Sacalo de la carpeta de mods, encendé de nuevo y avisales a tus amigos.",
        )
    return (
        "El servidor se cerró por un error que no reconocemos.",
        "Si pasa de nuevo, no cambies varias cosas a la vez y guardá el archivo de reporte para quien te ayuda.",
    )


crash_analyzer = CrashAnalyzer()
