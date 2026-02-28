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


def _thread_dump() -> str:
    frames = sys._current_frames()
    names = {thread.ident: thread.name for thread in threading.enumerate()}
    chunks: list[str] = []
    for tid, frame in frames.items():
        chunks.append(f"\n--- thread={names.get(tid, 'unknown')} ident={tid} ---\n")
        chunks.extend(traceback.format_stack(frame, limit=_THREAD_STACK_LIMIT))
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
        context_text = _format_context(resolved_context)
        stack = "".join(traceback.format_stack(limit=_STACK_LIMIT))

        # Collect full thread dump only for severe threshold breaches.
        extra_threads = _thread_dump() if elapsed_ms >= (threshold * 2.0) else ""
        logger.warning(
            "perf threshold exceeded stage=%s elapsed_ms=%.2f threshold_ms=%.2f context=%s\n"
            "stacktrace:\n%s%s",
            stage,
            elapsed_ms,
            threshold,
            context_text,
            stack,
            f"\nthread_dump:{extra_threads}" if extra_threads else "",
        )
