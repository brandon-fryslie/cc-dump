"""Slow-path performance logging with stack capture.

// [LAW:one-source-of-truth] Slow-stage thresholds are centralized in SLOW_STAGE_THRESHOLDS_MS.
// [LAW:single-enforcer] Threshold-exceeded diagnostics are emitted only by monitor_slow_path().
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from typing import Any


_enabled = True


def is_enabled() -> bool:
    return _enabled


def set_enabled(val: bool) -> None:
    global _enabled
    _enabled = val


# [LAW:no-mode-explosion] One central threshold map; avoid per-callsite knobs.
SLOW_STAGE_THRESHOLDS_MS: dict[str, float] = {
    "conversation.rerender_affected": 250.0,
    "conversation.background_rerender_tick": 120.0,
    "conversation.recalculate_offsets_from": 200.0,
}

_DEFAULT_THRESHOLD_MS = 250.0
_STACK_LIMIT = 40
_THREAD_STACK_LIMIT = 20
_THREAD_DUMP_MIN_MS = 500.0
_APP_PATH_MARKER = "/cc_dump/"
_PERF_LOG_START = "========== PERF SLOW PATH START =========="
_PERF_LOG_END = "========== PERF SLOW PATH END =========="


def _threshold_for(stage: str) -> float:
    return SLOW_STAGE_THRESHOLDS_MS.get(stage, _DEFAULT_THRESHOLD_MS)


def _resolve_context(
    context: Mapping[str, Any] | Callable[[], Mapping[str, Any]] | None,
) -> Mapping[str, Any]:
    if context is None:
        return {}
    if callable(context):
        try:
            resolved = context()
        except Exception as exc:  # pragma: no cover - defensive logging path
            return {"context_error": repr(exc)}
        return resolved if isinstance(resolved, Mapping) else {"context_value": resolved}
    return context


def _format_context(context: Mapping[str, Any]) -> str:
    # [LAW:dataflow-not-control-flow] Context serialization is data-driven (sorted keys).
    parts = [f"{k}={context[k]!r}" for k in sorted(context.keys())]
    return " ".join(parts)


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def _is_app_frame(filename: str) -> bool:
    return _APP_PATH_MARKER in _normalize_path(filename)


def _is_perf_logging_frame(filename: str) -> bool:
    return _normalize_path(filename).endswith("/io/perf_logging.py")


def _filter_app_frames(
    frames: list[traceback.FrameSummary],
) -> list[traceback.FrameSummary]:
    return [
        frame
        for frame in frames
        if _is_app_frame(frame.filename) and not _is_perf_logging_frame(frame.filename)
    ]


def _format_stack_frames(frames: list[traceback.FrameSummary]) -> str:
    if not frames:
        return "<no application frames captured>\n"
    return "".join(traceback.format_list(frames))


def _capture_app_stack() -> str:
    frames = traceback.extract_stack(limit=_STACK_LIMIT)
    return _format_stack_frames(_filter_app_frames(frames))


def _trigger_reason(elapsed_ms: float, threshold_ms: float) -> str:
    over_ms = elapsed_ms - threshold_ms
    if threshold_ms <= 0:
        return f"elapsed exceeded threshold by {over_ms:.2f}ms"
    return f"elapsed exceeded threshold by {over_ms:.2f}ms ({elapsed_ms / threshold_ms:.2f}x)"


def _thread_dump() -> str:
    frames = sys._current_frames()
    names = {thread.ident: thread.name for thread in threading.enumerate()}
    chunks: list[str] = []
    for tid, frame in frames.items():
        app_frames = _filter_app_frames(
            traceback.extract_stack(frame, limit=_THREAD_STACK_LIMIT)
        )
        if not app_frames:
            continue
        chunks.append(f"\n--- thread={names.get(tid, 'unknown')} ident={tid} ---\n")
        chunks.extend(traceback.format_list(app_frames))
    return "".join(chunks)


@contextmanager
def monitor_slow_path(
    stage: str,
    *,
    logger: logging.Logger,
    context: Mapping[str, Any] | Callable[[], Mapping[str, Any]] | None = None,
    threshold_ms: float | None = None,
):
    """Log stack diagnostics when a stage exceeds its latency threshold."""
    if not _enabled:
        yield
        return
    started_ns = time.perf_counter_ns()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        threshold = _threshold_for(stage) if threshold_ms is None else float(threshold_ms)
        if elapsed_ms < threshold:
            return

        resolved_context = _resolve_context(context)
        context_text = _format_context(resolved_context) or "-"
        stack = _capture_app_stack()

        # Collect full thread dump only for severe threshold breaches.
        extra_threads = (
            _thread_dump()
            if elapsed_ms >= max(threshold * 2.0, _THREAD_DUMP_MIN_MS)
            else ""
        )
        logger.warning(
            "%s\n"
            "stage=%s\n"
            "trigger=%s\n"
            "elapsed_ms=%.2f threshold_ms=%.2f over_ms=%.2f\n"
            "context=%s\n"
            "app_stack:\n%s%s\n"
            "%s",
            _PERF_LOG_START,
            stage,
            _trigger_reason(elapsed_ms, threshold),
            elapsed_ms,
            threshold,
            elapsed_ms - threshold,
            context_text,
            stack,
            f"\napp_thread_dump:{extra_threads}" if extra_threads else "",
            _PERF_LOG_END,
        )
