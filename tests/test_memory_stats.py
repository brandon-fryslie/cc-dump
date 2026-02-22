"""Unit tests for memory snapshot diagnostics."""

from types import SimpleNamespace

import cc_dump.memory_stats


def test_capture_snapshot_with_store_and_render_state(monkeypatch):
    class DomainStoreStub:
        completed_count = 7

        def get_active_stream_ids(self):
            return ["r1", "r2"]

    class AnalyticsStoreStub:
        turn_count = 5

    conv = SimpleNamespace(
        _turns=[object(), object(), object()],
        _line_cache={"a": 1, "b": 2},
        _cache_keys_by_turn={0: {("k0",), ("k1",)}, 1: {("k2",)}},
        _block_strip_cache={"b0": 1},
    )

    app = SimpleNamespace(
        _domain_store=DomainStoreStub(),
        _analytics_store=AnalyticsStoreStub(),
        _get_conv=lambda: conv,
    )

    monkeypatch.setattr(cc_dump.memory_stats.tracemalloc, "is_tracing", lambda: True)
    monkeypatch.setattr(
        cc_dump.memory_stats.tracemalloc, "get_traced_memory", lambda: (1234, 5678)
    )

    snapshot = cc_dump.memory_stats.capture_snapshot(app)

    assert snapshot["domain_completed_turns"] == 7
    assert snapshot["domain_active_streams"] == 2
    assert snapshot["analytics_turns"] == 5
    assert snapshot["rendered_turns"] == 3
    assert snapshot["line_cache_entries"] == 2
    assert snapshot["line_cache_index_keys"] == 3
    assert snapshot["block_cache_entries"] == 1
    assert snapshot["python_alloc_current_bytes"] == 1234
    assert snapshot["python_alloc_peak_bytes"] == 5678
    assert snapshot["python_alloc_tracing"] == 1


def test_capture_snapshot_without_optional_state(monkeypatch):
    app = SimpleNamespace(
        _domain_store=None,
        _analytics_store=None,
        _get_conv=lambda: None,
    )

    monkeypatch.setattr(cc_dump.memory_stats.tracemalloc, "is_tracing", lambda: False)

    snapshot = cc_dump.memory_stats.capture_snapshot(app)

    assert snapshot["domain_completed_turns"] == 0
    assert snapshot["domain_active_streams"] == 0
    assert snapshot["analytics_turns"] == 0
    assert snapshot["rendered_turns"] == 0
    assert snapshot["line_cache_entries"] == 0
    assert snapshot["line_cache_index_keys"] == 0
    assert snapshot["block_cache_entries"] == 0
    assert snapshot["python_alloc_current_bytes"] == 0
    assert snapshot["python_alloc_peak_bytes"] == 0
    assert snapshot["python_alloc_tracing"] == 0
