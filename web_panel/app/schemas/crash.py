"""Contrato del diagnóstico del Crash Doctor."""

from __future__ import annotations

from pydantic import BaseModel


class CrashReportSummary(BaseModel):
    filename: str
    timestamp: str
    cause: str
    suspected_mod: str | None
    suggestion: str
