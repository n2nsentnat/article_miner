"""Token-bucket style spacing for NCBI rate limits (thread-safe)."""

from __future__ import annotations

import threading
import time


class RateLimiter:
    """Enforces a minimum interval between successive operations."""

    def __init__(self, requests_per_second: float) -> None:
        if requests_per_second <= 0:
            msg = "requests_per_second must be positive"
            raise ValueError(msg)
        self._min_interval = 1.0 / requests_per_second
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        """Block until the next request slot according to the configured rate."""
        with self._lock:
            now = time.monotonic()
            if now < self._next_allowed:
                time.sleep(self._next_allowed - now)
            self._next_allowed = max(self._next_allowed, time.monotonic()) + self._min_interval
