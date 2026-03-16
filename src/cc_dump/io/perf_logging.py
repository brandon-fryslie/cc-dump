"""Slow-path performance logging with stack capture and complexity tracking.

// [LAW:one-source-of-truth] Slow-stage thresholds are centralized in SLOW_STAGE_THRESHOLDS_MS.
// [LAW:single-enforcer] Threshold-exceeded diagnostics are emitted only by monitor_slow_path()
//   and monitor_complexity().
"""

from __future__ import annotations

import logging
import math
import sys
import threading
import time
import traceback
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field


_enabled = True


def is_enabled() -> bool:
    return _enabled


def set_enabled(val: bool) -> None:
    global _enabled
    _enabled = val


# [LAW:no-mode-explosion] One central threshold map; avoid per-callsite knobs.
SLOW_STAGE_THRESHOLDS_MS: dict[str, float] = {
    "conversation.rerender_affected": 250.0,
    "conversation.background_rerender_tick": 200.0,
    "conversation.recalculate_offsets_from": 200.0,
}

_DEFAULT_THRESHOLD_MS = 250.0
_STACK_LIMIT = 40
_THREAD_STACK_LIMIT = 20


def _threshold_for(stage: str) -> float:
    return SLOW_STAGE_THRESHOLDS_MS.get(stage, _DEFAULT_THRESHOLD_MS)


def _resolve_context(
    context: Mapping[str, object] | Callable[[], Mapping[str, object]] | None,
) -> Mapping[str, object]:
    if context is None:
        return {}
    if callable(context):
        try:
            resolved = context()
        except Exception as exc:  # pragma: no cover - defensive logging path
            return {"context_error": repr(exc)}
        return resolved if isinstance(resolved, Mapping) else {"context_value": resolved}
    return context


def _format_context(context: Mapping[str, object]) -> str:
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
    context: Mapping[str, object] | Callable[[], Mapping[str, object]] | None = None,
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


# ─── Complexity-aware monitoring ──────────────────────────────────────
#
# Tracks *what work was done* (items touched vs total) rather than just
# how long it took.  A fast O(n) is still architecturally wrong when
# O(viewport) was expected.
#
# // [LAW:single-enforcer] Complexity diagnostics emitted only by monitor_complexity().

# [LAW:no-mode-explosion] One central ratio map; avoid per-callsite knobs.
COMPLEXITY_RATIO_THRESHOLDS: dict[str, float] = {
    "conversation.rerender_affected": 0.3,  # should only touch viewport
    "conversation.recalculate_offsets": 0.1,  # should be O(log n) per turn
}

_DEFAULT_COMPLEXITY_RATIO_THRESHOLD = 0.5


@dataclass
class ComplexityTracker:
    """Accumulates work metrics during a monitored operation.

    Callsites call ``.touch()`` for each item processed.
    """

    total_items: int
    items_touched: int = 0
    extra: dict[str, object] = field(default_factory=dict)

    def touch(self, count: int = 1) -> None:
        """Record that *count* items were processed."""
        self.items_touched += count

    @property
    def ratio(self) -> float:
        """Fraction of total items touched (0.0 – 1.0)."""
        if self.total_items <= 0:
            return 0.0
        return self.items_touched / self.total_items

    @property
    def complexity_class(self) -> str:
        """Classify observed complexity from the ratio."""
        if self.total_items <= 1:
            return "O(1)"
        r = self.ratio
        if r <= 0.0:
            return "O(1)"
        log_ratio = math.log2(max(self.total_items, 2)) / self.total_items
        if r <= log_ratio * 3:
            return "O(log n)"
        if r <= 0.3:
            return "O(k)"
        return "O(n)"


def _evaluate_complexity(
    stage: str,
    tracker: ComplexityTracker,
    elapsed_ms: float,
    threshold_ms: float | None,
    logger: logging.Logger,
) -> None:
    ratio_threshold = COMPLEXITY_RATIO_THRESHOLDS.get(
        stage, _DEFAULT_COMPLEXITY_RATIO_THRESHOLD
    )
    time_threshold = (
        _threshold_for(stage) if threshold_ms is None else float(threshold_ms)
    )

    time_exceeded = elapsed_ms >= time_threshold
    ratio_exceeded = tracker.ratio > ratio_threshold and tracker.total_items > 10

    if not time_exceeded and not ratio_exceeded:
        return

    extra_text = _format_context(tracker.extra) if tracker.extra else ""
    logger.warning(
        "complexity alert stage=%s elapsed_ms=%.2f complexity=%s "
        "items_touched=%d total_items=%d ratio=%.3f threshold_ratio=%.3f%s",
        stage,
        elapsed_ms,
        tracker.complexity_class,
        tracker.items_touched,
        tracker.total_items,
        tracker.ratio,
        ratio_threshold,
        f" {extra_text}" if extra_text else "",
    )


@contextmanager
def monitor_complexity(
    stage: str,
    *,
    logger: logging.Logger,
    total_items: int,
    threshold_ms: float | None = None,
):
    """Track complexity and time for an operation.

    Yields a `ComplexityTracker` that callsites use to record items touched.
    At exit, logs if items_touched indicates linear work where sublinear was
    expected, **or** if the time threshold was exceeded.

    // [LAW:single-enforcer] Complexity diagnostics emitted only here.
    """
    tracker = ComplexityTracker(total_items=total_items)
    if not _enabled:
        yield tracker
        return
    started_ns = time.perf_counter_ns()
    try:
        yield tracker
    finally:
        elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        _evaluate_complexity(stage, tracker, elapsed_ms, threshold_ms, logger)
