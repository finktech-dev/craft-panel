"""Crash-loop guard for ``restart_on_crash``: stop restarting a server that keeps falling."""

from __future__ import annotations

import threading
import time
from collections import deque

WINDOW_SECONDS = 10 * 60


class CrashRestartGuard:
    """Counts crashes in the last 10 minutes and pauses automatic restarts past the limit."""

    def __init__(self, window_seconds: float = WINDOW_SECONDS) -> None:
        self._window = window_seconds
        self._crashes: deque[float] = deque()
        self._lock = threading.Lock()
        self.paused_message: str | None = None

    def allow_restart(self, max_restarts: int, now: float | None = None) -> bool:
        """Record a crash; ``False`` once more than ``max_restarts`` happened inside the window."""
        moment = time.monotonic() if now is None else now
        with self._lock:
            while self._crashes and moment - self._crashes[0] > self._window:
                self._crashes.popleft()
            self._crashes.append(moment)
            if self.paused_message is not None:
                return False
            if len(self._crashes) > max_restarts:
                self.paused_message = (
                    f"Se cerró solo {len(self._crashes)} veces en 10 minutos, así que dejamos de volver a encenderlo. "
                    "Mirá qué lo está tirando abajo y encendelo vos cuando esté arreglado."
                )
                return False
            return True

    def reset(self) -> None:
        """Called when someone starts the server by hand: automatic restarts may run again."""
        with self._lock:
            self._crashes.clear()
            self.paused_message = None


crash_guard = CrashRestartGuard()
