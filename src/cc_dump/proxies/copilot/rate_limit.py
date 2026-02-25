"""Simple per-process rate limiter for Copilot upstream requests."""

from __future__ import annotations

import threading
import time


class CopilotRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_request_mono = 0.0

    def gate(
        self,
        *,
        min_interval_seconds: int,
        wait_on_limit: bool,
    ) -> tuple[bool, float]:
        interval = max(0.0, float(min_interval_seconds))
        if interval <= 0:
            return True, 0.0

        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_mono
            remaining = interval - elapsed
            if remaining <= 0:
                self._last_request_mono = now
                return True, 0.0
            if not wait_on_limit:
                return False, remaining

        time.sleep(max(0.0, remaining))
        with self._lock:
            self._last_request_mono = time.monotonic()
        return True, remaining


copilot_rate_limiter = CopilotRateLimiter()
