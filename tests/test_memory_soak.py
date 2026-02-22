"""Regression tests for memory soak harness."""

import cc_dump.memory_soak


def test_run_memory_soak_enforces_guardrails():
    snapshots = cc_dump.memory_soak.run_memory_soak(
        turns=1200,
        snapshot_interval=300,
        har_max_pending=32,
    )

    assert snapshots
    assert snapshots[-1].turn == 1200
    assert snapshots[-1].analytics_turns == 1200
    assert snapshots[-1].domain_completed_turns == 1200

    max_pending = max(s.har_pending_requests for s in snapshots)
    assert max_pending <= 32

    max_line_cache_entries = max(s.line_cache_entries for s in snapshots)
    max_line_cache_index_keys = max(s.line_cache_index_keys for s in snapshots)
    line_cache_max = snapshots[-1].line_cache_maxsize
    assert max_line_cache_entries <= line_cache_max
    assert max_line_cache_index_keys <= line_cache_max

    peaks = [s.python_alloc_peak_bytes for s in snapshots]
    assert peaks == sorted(peaks)
