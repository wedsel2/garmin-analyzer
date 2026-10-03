"""Limit on failed sign-ins, kept in memory.

The web service is one process, so a table is not needed. A restart forgets
the counts, which someone guessing passwords cannot cause.
"""

import threading
import time
from collections.abc import Callable


class FailureLimiter:
    """Blocks a key after too many failures within a period."""

    def __init__(
        self, limit: int, period_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = limit
        self._period = period_seconds
        self._clock = clock
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def blocked(self, key: str) -> bool:
        with self._lock:
            self._forget_old()
            return len(self._failures.get(key, ())) >= self._limit

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._forget_old()
            self._failures.setdefault(key, []).append(self._clock())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def _forget_old(self) -> None:
        # Also drops keys that have gone quiet, so the table cannot keep
        # growing from addresses that fail once.
        horizon = self._clock() - self._period
        for key, times in list(self._failures.items()):
            recent = [moment for moment in times if moment > horizon]
            if recent:
                self._failures[key] = recent
            else:
                del self._failures[key]
