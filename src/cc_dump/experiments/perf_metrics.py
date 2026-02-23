"""Lightweight streaming-latency instrumentation for the cc-dump pipeline.

// [LAW:one-source-of-truth] All latency measurement goes through this module.
// [LAW:single-enforcer] Metric recording happens here, not scattered in handlers.

This module is STABLE — never hot-reloaded. Safe for `from` imports.

Usage:
    from cc_dump.experiments.perf_metrics import metrics

    # Record a sample at a pipeline stage
    metrics.record("queue_delay", elapsed_ns=handler_ns - event.recv_ns)

    # Get statistics snapshot
    snap = metrics.snapshot()  # {"queue_delay": {"count": N, "p50_us": ..., ...}, ...}

    # Reset for next benchmark run
    metrics.reset()
"""

import time
from dataclasses import dataclass, field


@dataclass
class StageStats:
    """Computed statistics for a single pipeline stage.

    All latency values are in microseconds (us) for human readability.
    """

    count: int
    min_us: float
    max_us: float
    mean_us: float
    p50_us: float
    p95_us: float
    p99_us: float


class MetricsCollector:
    """Append-only collector for nanosecond latency samples.

    Thread-safe for concurrent record() calls (list.append is atomic in CPython).
    snapshot() is a point-in-time read — not linearizable with ongoing writes,
    but sufficient for benchmarking and diagnostics.
    """

    def __init__(self) -> None:
        self._stages: dict[str, list[int]] = {}
        self._enabled: bool = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def record(self, stage: str, *, elapsed_ns: int) -> None:
        """Record a latency sample (nanoseconds) for the given stage.

        No-op when disabled. Overhead when disabled: one bool check.
        """
        if not self._enabled:
            return
        samples = self._stages.get(stage)
        if samples is None:
            samples = []
            self._stages[stage] = samples
        samples.append(elapsed_ns)

    def mark(self, stage: str, *, since_ns: int) -> None:
        """Record elapsed time from since_ns to now.

        Convenience wrapper: ``record(stage, elapsed_ns=now - since_ns)``.
        """
        self.record(stage, elapsed_ns=time.monotonic_ns() - since_ns)

    def reset(self) -> None:
        """Clear all collected samples."""
        self._stages.clear()

    def stage_names(self) -> list[str]:
        """Return names of stages that have samples."""
        return list(self._stages.keys())

    def sample_count(self, stage: str) -> int:
        """Return number of samples for a stage (0 if unknown)."""
        samples = self._stages.get(stage)
        return len(samples) if samples is not None else 0

    def snapshot(self) -> dict[str, StageStats]:
        """Compute statistics for all stages.

        Returns:
            Dict mapping stage name to StageStats. Empty stages are omitted.
        """
        result: dict[str, StageStats] = {}
        for stage, samples in self._stages.items():
            if not samples:
                continue
            result[stage] = _compute_stats(samples)
        return result


def _compute_stats(samples: list[int]) -> StageStats:
    """Compute percentile statistics from nanosecond samples."""
    sorted_samples = sorted(samples)
    n = len(sorted_samples)
    total = sum(sorted_samples)

    return StageStats(
        count=n,
        min_us=sorted_samples[0] / 1_000,
        max_us=sorted_samples[-1] / 1_000,
        mean_us=(total / n) / 1_000,
        p50_us=_percentile(sorted_samples, 0.50) / 1_000,
        p95_us=_percentile(sorted_samples, 0.95) / 1_000,
        p99_us=_percentile(sorted_samples, 0.99) / 1_000,
    )


def _percentile(sorted_samples: list[int], pct: float) -> float:
    """Nearest-rank percentile from pre-sorted samples."""
    n = len(sorted_samples)
    idx = int(pct * (n - 1))
    return float(sorted_samples[idx])


# Module-level singleton — importable as `from cc_dump.experiments.perf_metrics import metrics`
metrics = MetricsCollector()
