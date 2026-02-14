"""Tee stderr to both the real terminal and the TUI LogsPanel.

// [LAW:single-enforcer] All stderr→LogsPanel routing is enforced here.
// No call-site changes needed — install() replaces sys.stderr globally.

Thread-safe: proxy, router, and HAR threads all write stderr.
"""

import re
import sys
import threading
from collections import deque
from typing import Callable, Optional

# Callback signature: (level: str, source: str, message: str)
DrainFn = Callable[[str, str, str], None]

_PREFIX_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")

# Keywords that indicate log level (checked case-insensitively against prefix + message)
_ERROR_KEYWORDS = {"error", "fail", "exception", "traceback"}
_WARN_KEYWORDS = {"warn", "warning"}


def _parse_line(line: str) -> tuple[str, str, str]:
    """Parse a stderr line into (level, source, message).

    Lines matching ``[prefix] message`` extract prefix as source.
    Level is inferred from keywords in the prefix and message.
    """
    m = _PREFIX_RE.match(line)
    source = m.group(1) if m else "stderr"
    message = m.group(2) if m else line

    # Infer level from combined text — strip punctuation so "error:" matches "error"
    lower = line.lower()
    words = {w.rstrip(":,.!") for w in lower.split()}
    # [LAW:dataflow-not-control-flow] Level lookup via set intersection, not branching
    level = (
        "ERROR" if _ERROR_KEYWORDS & words else
        "WARN" if _WARN_KEYWORDS & words else
        "INFO"
    )
    return level, source, message


class StderrTee:
    """File-like wrapper that tees writes to real stderr + optional drain callback."""

    def __init__(self, real_stderr):
        self._real = real_stderr
        self._lock = threading.RLock()  # RLock: drain callback may trigger stderr write
        self._drain: Optional[DrainFn] = None
        self._buffer = ""  # Partial line accumulator
        self._ring: deque[str] = deque(maxlen=500)  # Pre-TUI buffer

    # ── File-like interface ────────────────────────────────────────────

    def write(self, s: str) -> int:
        # Always write to real stderr first
        self._real.write(s)

        with self._lock:
            self._buffer += s
            # Process complete lines
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                self._emit(line)
        return len(s)

    def flush(self):
        self._real.flush()

    def fileno(self):
        return self._real.fileno()

    def isatty(self):
        return self._real.isatty()

    @property
    def encoding(self):
        return self._real.encoding

    @property
    def errors(self):
        return self._real.errors

    @property
    def name(self):
        return self._real.name

    def readable(self):
        return False

    def writable(self):
        return True

    def seekable(self):
        return False

    # ── Connect / disconnect ──────────────────────────────────────────

    def connect(self, drain_fn: DrainFn) -> None:
        """Register drain callback and flush buffered messages."""
        with self._lock:
            self._drain = drain_fn
            # Flush ring buffer
            for line in self._ring:
                level, source, message = _parse_line(line)
                drain_fn(level, source, message)
            self._ring.clear()

    def disconnect(self) -> None:
        """Unregister drain callback. Subsequent writes go to real stderr only."""
        with self._lock:
            self._drain = None

    # ── Internal ──────────────────────────────────────────────────────

    def _emit(self, line: str) -> None:
        """Route a complete line to drain or ring buffer. Caller holds _lock."""
        drain = self._drain
        if drain is not None:
            level, source, message = _parse_line(line)
            try:
                drain(level, source, message)
            except Exception:
                pass  # Never let drain errors break stderr
        else:
            self._ring.append(line)


# ── Module-level helpers ──────────────────────────────────────────────

_tee: Optional[StderrTee] = None


def install() -> StderrTee:
    """Replace sys.stderr with a StderrTee. Idempotent."""
    global _tee
    if _tee is not None:
        return _tee
    _tee = StderrTee(sys.stderr)
    sys.stderr = _tee  # type: ignore[assignment]
    return _tee


def get_tee() -> Optional[StderrTee]:
    """Return the installed tee, or None if not installed."""
    return _tee
