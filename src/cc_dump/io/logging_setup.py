"""Centralized logging bootstrap for cc-dump runtime.

// [LAW:single-enforcer] Logger handler wiring is enforced in this module only.
// [LAW:one-source-of-truth] Runtime log path/level are derived here and returned to callers.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


@dataclass(frozen=True)
class LoggingRuntime:
    """Resolved runtime logging configuration."""

    level_name: str
    level: int
    file_path: str


_RUNTIME: LoggingRuntime | None = None


def _parse_level(raw: str) -> tuple[str, int]:
    normalized = str(raw or "INFO").strip().upper()
    level = getattr(logging, normalized, logging.INFO)
    level_name = logging.getLevelName(level)
    return str(level_name), int(level)


def _safe_name(value: str) -> str:
    candidate = "".join(ch if (ch.isalnum() or ch in {"-", "_"}) else "-" for ch in value)
    cleaned = candidate.strip("-_")
    return cleaned or "session"


def _default_log_path(session_name: str) -> str:
    log_dir = Path(
        os.environ.get("CC_DUMP_LOG_DIR", os.path.expanduser("~/.local/share/cc-dump/logs"))
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_session = _safe_name(session_name)
    return str(log_dir / f"{safe_session}-{ts}-{os.getpid()}.log")


def _make_stream_handler(level: int) -> logging.Handler:
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s %(message)s"))
    # [LAW:dataflow-not-control-flow] In-app-only records mark intent in data via cc_dump_in_app.
    handler.addFilter(lambda record: not bool(getattr(record, "cc_dump_in_app", False)))
    return handler


def _make_file_handler(level: int, file_path: str) -> logging.Handler:
    handler = RotatingFileHandler(
        file_path,
        maxBytes=20 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s [%(threadName)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    return handler


def configure(session_name: str = "unnamed-session") -> LoggingRuntime:
    """Configure cc_dump logger hierarchy with stderr + rotating file handlers.

    Idempotent: repeated calls return the originally configured runtime.
    """
    global _RUNTIME
    if _RUNTIME is not None:
        return _RUNTIME

    level_name, level = _parse_level(os.environ.get("CC_DUMP_LOG_LEVEL", "INFO"))
    file_path = os.environ.get("CC_DUMP_LOG_FILE", _default_log_path(session_name))
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)

    # [LAW:single-enforcer] All cc_dump module loggers propagate to this one logger.
    logger = logging.getLogger("cc_dump")
    logger.setLevel(level)
    logger.propagate = False
    logger.handlers.clear()
    logger.addHandler(_make_stream_handler(level))
    logger.addHandler(_make_file_handler(level, file_path))

    # Keep third-party logging quiet unless it is warning+.
    root = logging.getLogger()
    if root.level > logging.WARNING:
        root.setLevel(logging.WARNING)

    logging.captureWarnings(True)

    _RUNTIME = LoggingRuntime(level_name=level_name, level=level, file_path=file_path)
    return _RUNTIME


def get_runtime() -> LoggingRuntime | None:
    """Return configured logging runtime, if configure() has run."""
    return _RUNTIME
