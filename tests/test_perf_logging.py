"""Tests for slow-path perf logging utilities."""

import logging

from cc_dump.io.perf_logging import monitor_slow_path


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
    assert "PERF SLOW PATH START" not in caplog.text


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
    assert "PERF SLOW PATH START" in caplog.text
    assert "PERF SLOW PATH END" in caplog.text
    assert "stage=test.stage" in caplog.text
    assert "trigger=elapsed exceeded threshold by" in caplog.text
    assert "app_stack:" in caplog.text
    assert "<no application frames captured>" in caplog.text
    assert "alpha=1" in caplog.text
    assert "beta='two'" in caplog.text
