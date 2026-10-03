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

    def attempt(self, key: str) -> bool:
        """Count an attempt as a failure, or return False when the key is blocked.

        Counting happens before the outcome is known, in the same step as the
        check, so attempts made at the same moment cannot all slip through.
        Call forgive or reset when the attempt turns out to have succeeded.
        """
        with self._lock:
            self._forget_old()
            times = self._failures.setdefault(key, [])
            if len(times) >= self._limit:
                return False
            times.append(self._clock())
            return True

    def forgive(self, key: str) -> None:
        """Take back the latest attempt of a key."""
        with self._lock:
            times = self._failures.get(key)
            if times:
                times.pop()

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
                times[:] = recent
            else:
                del self._failures[key]
