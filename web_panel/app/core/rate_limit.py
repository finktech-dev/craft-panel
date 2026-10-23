"""Tiny in-memory rate limits and busy guards for expensive admin endpoints.

The panel has a single administrator, so limits are global per endpoint: they
only exist to stop a stolen session, a stuck script or a double click from
hammering the disk, the CPU or third-party APIs (Modrinth, Discord).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, status


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._calls: defaultdict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str, max_calls: int, window_seconds: float) -> int:
        """Record a call; return 0 when allowed or the seconds to wait."""
        now = time.monotonic()
        calls = self._calls[key]
        while calls and now - calls[0] > window_seconds:
            calls.popleft()
        if len(calls) >= max_calls:
            return max(1, int(window_seconds - (now - calls[0])) + 1)
        calls.append(now)
        return 0

    def reset(self) -> None:
        self._calls.clear()


limiter = SlidingWindowLimiter()


def rate_limit(name: str, max_calls: int, window_seconds: float) -> Callable[[], None]:
    """FastAPI dependency: ``dependencies=[Depends(rate_limit("x", 10, 60))]``."""

    def _dependency() -> None:
        retry_after = limiter.hit(name, max_calls, window_seconds)
        if retry_after:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiadas solicitudes seguidas. Esperá unos segundos y probá de nuevo.",
                headers={"Retry-After": str(retry_after)},
            )

    return _dependency
