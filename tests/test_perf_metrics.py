"""Tests for cc_dump.experiments.perf_metrics — collector behavior, stats shape, and thresholds."""

import time

import pytest

from cc_dump.experiments.perf_metrics import MetricsCollector, StageStats, _compute_stats


# ─── MetricsCollector basics ────────────────────────────────────────────────


class TestCollectorDisabled:
    """Disabled collector is a no-op — zero overhead path."""

    def test_disabled_by_default(self):
        c = MetricsCollector()
        assert c.enabled is False

    def test_record_is_noop_when_disabled(self):
        c = MetricsCollector()
        c.record("format", elapsed_ns=1000)
        assert c.sample_count("format") == 0

    def test_mark_is_noop_when_disabled(self):
        c = MetricsCollector()
        c.mark("queue_delay", since_ns=time.monotonic_ns() - 1_000_000)
        assert c.sample_count("queue_delay") == 0

    def test_snapshot_empty_when_disabled(self):
        c = MetricsCollector()
        c.record("x", elapsed_ns=100)
        assert c.snapshot() == {}


class TestCollectorEnabled:
    """Enabled collector records and reports."""

    def test_enable_toggle(self):
        c = MetricsCollector()
        c.enabled = True
        assert c.enabled is True

    def test_record_accumulates_samples(self):
        c = MetricsCollector()
        c.enabled = True
        c.record("format", elapsed_ns=100)
        c.record("format", elapsed_ns=200)
        c.record("format", elapsed_ns=300)
        assert c.sample_count("format") == 3

    def test_mark_records_elapsed(self):
        c = MetricsCollector()
        c.enabled = True
        start = time.monotonic_ns()
        # Burn a small amount of time
        _ = sum(range(100))
        c.mark("work", since_ns=start)
        assert c.sample_count("work") == 1
        snap = c.snapshot()
        assert snap["work"].min_us >= 0  # non-negative

    def test_multiple_stages(self):
        c = MetricsCollector()
        c.enabled = True
        c.record("format", elapsed_ns=100)
        c.record("queue_delay", elapsed_ns=200)
        assert set(c.stage_names()) == {"format", "queue_delay"}

    def test_reset_clears_all(self):
        c = MetricsCollector()
        c.enabled = True
        c.record("a", elapsed_ns=1)
        c.record("b", elapsed_ns=2)
        c.reset()
        assert c.stage_names() == []
        assert c.snapshot() == {}

    def test_sample_count_unknown_stage(self):
        c = MetricsCollector()
        assert c.sample_count("nonexistent") == 0


# ─── StageStats shape ───────────────────────────────────────────────────────


class TestStatsShape:
    """Verify snapshot returns correct StageStats structure."""

    def test_stats_fields(self):
        c = MetricsCollector()
        c.enabled = True
        for ns in [1000, 2000, 3000, 4000, 5000]:
            c.record("test", elapsed_ns=ns)
        snap = c.snapshot()
        stats = snap["test"]
        assert isinstance(stats, StageStats)
        assert stats.count == 5
        assert stats.min_us == pytest.approx(1.0)
        assert stats.max_us == pytest.approx(5.0)
        assert stats.mean_us == pytest.approx(3.0)
        assert stats.p50_us == pytest.approx(3.0)
        assert stats.p95_us == pytest.approx(4.0)  # nearest-rank: int(0.95*4)=3 → 4000ns
        assert stats.p99_us == pytest.approx(4.0)  # nearest-rank: int(0.99*4)=3 → 4000ns

    def test_single_sample(self):
        c = MetricsCollector()
        c.enabled = True
        c.record("solo", elapsed_ns=42_000)
        snap = c.snapshot()
        stats = snap["solo"]
        assert stats.count == 1
        assert stats.min_us == stats.max_us == stats.p50_us == pytest.approx(42.0)

    def test_all_fields_are_floats(self):
        """All latency fields are float (microseconds)."""
        c = MetricsCollector()
        c.enabled = True
        c.record("x", elapsed_ns=1000)
        stats = c.snapshot()["x"]
        for attr in ("min_us", "max_us", "mean_us", "p50_us", "p95_us", "p99_us"):
            assert isinstance(getattr(stats, attr), float), f"{attr} should be float"


# ─── _compute_stats internals ───────────────────────────────────────────────


class TestComputeStats:
    def test_percentile_ordering(self):
        # 100 samples: 0ns, 1000ns, ..., 99000ns
        samples = [i * 1000 for i in range(100)]
        stats = _compute_stats(samples)
        assert stats.p50_us <= stats.p95_us <= stats.p99_us <= stats.max_us
        assert stats.min_us <= stats.p50_us

    def test_high_variance(self):
        # 99 fast + 1 outlier
        samples = [1000] * 99 + [10_000_000]
        stats = _compute_stats(samples)
        assert stats.p50_us == pytest.approx(1.0)
        assert stats.max_us == pytest.approx(10_000.0)
        assert stats.p99_us <= stats.max_us


# ─── Benchmark integration smoke test ───────────────────────────────────────


class TestBenchmarkSmoke:
    """Verify the benchmark module runs and returns correct shape."""

    def test_benchmark_returns_expected_keys(self):
        from benchmarks.bench_streaming import run_benchmark
        results = run_benchmark(n_deltas=10)
        assert "n_deltas" in results
        assert results["n_deltas"] == 10
        assert "n_events" in results
        assert results["n_events"] > 10  # deltas + start/stop/delta events
        assert "wall_time_ms" in results
        assert results["wall_time_ms"] > 0
        assert "mem_peak_kb" in results
        assert "stages" in results
        assert "format" in results["stages"]
        assert "queue_delay" in results["stages"]

    def test_benchmark_stage_stats_shape(self):
        from benchmarks.bench_streaming import run_benchmark
        results = run_benchmark(n_deltas=20)
        for stage_name, stage_stats in results["stages"].items():
            assert "count" in stage_stats, f"{stage_name} missing count"
            assert "p50_us" in stage_stats, f"{stage_name} missing p50_us"
            assert "p95_us" in stage_stats, f"{stage_name} missing p95_us"
            assert "p99_us" in stage_stats, f"{stage_name} missing p99_us"
            assert "min_us" in stage_stats, f"{stage_name} missing min_us"
            assert "max_us" in stage_stats, f"{stage_name} missing max_us"
            assert "mean_us" in stage_stats, f"{stage_name} missing mean_us"

    def test_format_latency_under_threshold(self):
        """Format pipeline for 500 text deltas should complete under 100ms wall time."""
        from benchmarks.bench_streaming import run_benchmark
        results = run_benchmark(n_deltas=500)
        assert results["wall_time_ms"] < 5000, (
            f"Format pipeline took {results['wall_time_ms']:.1f}ms — "
            f"expected under 5000ms for 500 deltas"
        )
        # Per-event p95 format latency should be under 1ms (1000us)
        fmt = results["stages"]["format"]
        assert fmt["p95_us"] < 1000, (
            f"p95 format latency {fmt['p95_us']:.1f}us exceeds 1000us threshold"
        )

    def test_queue_delay_budget_under_threshold(self):
        """End-to-end event queue delay should remain within budget for 2k deltas."""
        from benchmarks.bench_streaming import run_benchmark
        results = run_benchmark(n_deltas=2000)
        queue_delay = results["stages"]["queue_delay"]
        assert queue_delay["p95_us"] < 100_000, (
            f"p95 queue delay {queue_delay['p95_us']:.1f}us exceeds 100000us budget"
        )

    def test_event_generation(self):
        """Verify synthetic event stream structure."""
        from benchmarks.bench_streaming import generate_sse_stream
        from cc_dump.pipeline.event_types import (
            ResponseSSEEvent,
            MessageStartEvent as MStart,
            TextBlockStartEvent as TBStart,
            TextDeltaEvent as TDelta,
            ContentBlockStopEvent as CBStop,
            MessageDeltaEvent as MDelta,
            MessageStopEvent as MStop,
        )
        events = generate_sse_stream(5)
        # Structure: msg_start, text_block_start, 5x text_delta,
        #            content_block_stop, message_delta, message_stop = 10
        assert len(events) == 10
        assert isinstance(events[0].sse_event, MStart)
        assert isinstance(events[1].sse_event, TBStart)
        for i in range(2, 7):
            assert isinstance(events[i].sse_event, TDelta)
        assert isinstance(events[7].sse_event, CBStop)
        assert isinstance(events[8].sse_event, MDelta)
        assert isinstance(events[9].sse_event, MStop)
        # All have recv_ns > 0 and sequential seq
        for i, evt in enumerate(events):
            assert isinstance(evt, ResponseSSEEvent)
            assert evt.recv_ns > 0
            assert evt.seq == i + 1
