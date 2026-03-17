"""Tests for slow-path perf logging utilities."""

import logging

from cc_dump.io.perf_logging import ComplexityTracker, monitor_complexity, monitor_slow_path


def test_monitor_slow_path_no_log_below_threshold(caplog):
    logger = logging.getLogger("cc_dump.test.perf")
    with caplog.at_level(logging.WARNING, logger="cc_dump.test.perf"):
        with monitor_slow_path(
            "test.stage",
            logger=logger,
            threshold_ms=10_000.0,
            context={"k": "v"},
        ):
            pass
    assert "perf threshold exceeded" not in caplog.text


def test_monitor_slow_path_logs_context_on_threshold(caplog):
    logger = logging.getLogger("cc_dump.test.perf")
    with caplog.at_level(logging.WARNING, logger="cc_dump.test.perf"):
        with monitor_slow_path(
            "test.stage",
            logger=logger,
            threshold_ms=0.0,
            context={"alpha": 1, "beta": "two"},
        ):
            pass
    assert "perf threshold exceeded stage=test.stage" in caplog.text
    assert "alpha=1" in caplog.text
    assert "beta='two'" in caplog.text


# ─── ComplexityTracker unit tests ─────────────────────────────────────


def test_complexity_tracker_ratio():
    t = ComplexityTracker(total_items=100)
    t.touch(50)
    assert t.ratio == 0.5


def test_complexity_tracker_ratio_zero_total():
    t = ComplexityTracker(total_items=0)
    t.touch(5)
    assert t.ratio == 0.0


def test_complexity_class_o1():
    t = ComplexityTracker(total_items=1)
    t.touch(1)
    assert t.complexity_class == "O(1)"


def test_complexity_class_logarithmic():
    t = ComplexityTracker(total_items=10_000)
    # ~14 items out of 10K ≈ log2(10000)/10000 ratio
    t.touch(14)
    assert t.complexity_class == "O(log n)"


def test_complexity_class_sublinear():
    t = ComplexityTracker(total_items=1000)
    t.touch(100)  # 10% — more than log but less than 30%
    assert t.complexity_class == "O(k)"


def test_complexity_class_linear():
    t = ComplexityTracker(total_items=1000)
    t.touch(500)
    assert t.complexity_class == "O(n)"


# ─── monitor_complexity integration tests ─────────────────────────────


def test_monitor_complexity_no_log_below_thresholds(caplog):
    """No log when both ratio and time are within bounds."""
    logger = logging.getLogger("cc_dump.test.cx")
    with caplog.at_level(logging.WARNING, logger="cc_dump.test.cx"):
        with monitor_complexity(
            "test.stage",
            logger=logger,
            total_items=100,
            threshold_ms=10_000.0,
        ) as tracker:
            tracker.touch(5)  # 5% ratio, well below 50% default
    assert "complexity alert" not in caplog.text


def test_monitor_complexity_logs_on_ratio_exceeded(caplog):
    """Logs when ratio exceeds threshold even if fast."""
    logger = logging.getLogger("cc_dump.test.cx")
    with caplog.at_level(logging.WARNING, logger="cc_dump.test.cx"):
        with monitor_complexity(
            "test.stage",
            logger=logger,
            total_items=100,
            threshold_ms=10_000.0,  # won't trigger on time
        ) as tracker:
            tracker.touch(80)  # 80% ratio > 50% default
    assert "complexity alert stage=test.stage" in caplog.text
    assert "items_touched=80" in caplog.text
    assert "total_items=100" in caplog.text
    assert "ratio=0.800" in caplog.text


def test_monitor_complexity_logs_on_time_exceeded(caplog):
    """Logs when time threshold exceeded even if ratio is low."""
    logger = logging.getLogger("cc_dump.test.cx")
    with caplog.at_level(logging.WARNING, logger="cc_dump.test.cx"):
        with monitor_complexity(
            "test.stage",
            logger=logger,
            total_items=100,
            threshold_ms=0.0,  # any time exceeds this
        ) as tracker:
            tracker.touch(1)  # 1% ratio, well below threshold
    assert "complexity alert stage=test.stage" in caplog.text


def test_monitor_complexity_skips_small_total(caplog):
    """Ratio check skipped when total_items <= 10 (avoid noise on small sets)."""
    logger = logging.getLogger("cc_dump.test.cx")
    with caplog.at_level(logging.WARNING, logger="cc_dump.test.cx"):
        with monitor_complexity(
            "test.stage",
            logger=logger,
            total_items=5,
            threshold_ms=10_000.0,
        ) as tracker:
            tracker.touch(5)  # 100% ratio but only 5 items
    assert "complexity alert" not in caplog.text


def test_monitor_complexity_extra_context(caplog):
    """Extra context dict is included in log output."""
    logger = logging.getLogger("cc_dump.test.cx")
    with caplog.at_level(logging.WARNING, logger="cc_dump.test.cx"):
        with monitor_complexity(
            "test.stage",
            logger=logger,
            total_items=100,
            threshold_ms=10_000.0,
        ) as tracker:
            tracker.touch(80)
            tracker.extra["vp_start"] = 5
            tracker.extra["vp_end"] = 20
    assert "vp_end=20" in caplog.text
    assert "vp_start=5" in caplog.text
