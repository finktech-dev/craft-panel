"""Progress reporting contract shared by long-running services and the job service.

Services accept an optional ``progress`` callback and announce which step of
their published plan they are on. The callback is synchronous and may be called
from worker threads (zipping, extracting), so implementations must be
thread-safe. Callers that do not care about progress simply pass nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Protocol

logger = logging.getLogger(__name__)

# Ordered (key, plain-Spanish label) pairs describing what an operation does.
StepPlan = Sequence[tuple[str, str]]

_MEBIBYTE = 1024 * 1024


class ProgressCallback(Protocol):
    def __call__(self, step: str, message: str | None = None, percent: float | None = None) -> None: ...


def report(
    progress: ProgressCallback | None,
    step: str,
    message: str | None = None,
    percent: float | None = None,
) -> None:
    """Forward one progress update; a broken listener must never break the real work."""
    if progress is None:
        return
    try:
        progress(step, message, percent)
    except Exception:  # noqa: BLE001 - progress is best effort by design
        logger.debug("Progress listener failed for step %s.", step, exc_info=True)


def format_megabytes(value: int) -> str:
    megabytes = value / _MEBIBYTE
    text = f"{megabytes:.1f}" if megabytes < 10 else f"{megabytes:.0f}"
    return text.replace(".", ",")


def download_message(done: int, total: int | None) -> tuple[str, float | None]:
    """Sentence and percent for a download, with or without a known size."""
    if total and total > 0:
        return (
            f"Descargados {format_megabytes(done)} de {format_megabytes(total)} MB.",
            min(100.0, done * 100 / total),
        )
    return f"Descargados {format_megabytes(done)} MB.", None
