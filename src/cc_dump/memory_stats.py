"""Lightweight in-process memory snapshot helpers.

// [LAW:locality-or-seam] Memory diagnostics are centralized in this module.
"""

import tracemalloc


def capture_snapshot(app) -> dict[str, int]:
    """Capture coarse-grained memory-related counters from app/store state."""
    domain_store = getattr(app, "_domain_store", None)
    analytics_store = getattr(app, "_analytics_store", None)
    conv = app._get_conv() if hasattr(app, "_get_conv") else None

    completed_turns = int(getattr(domain_store, "completed_count", 0)) if domain_store is not None else 0
    active_streams = (
        len(domain_store.get_active_stream_ids()) if domain_store is not None else 0
    )
    analytics_turns = int(getattr(analytics_store, "turn_count", 0)) if analytics_store is not None else 0

    if conv is None:
        rendered_turns = 0
        line_cache_entries = 0
        line_cache_index_keys = 0
        block_cache_entries = 0
    else:
        rendered_turns = len(conv._turns)
        line_cache_entries = len(conv._line_cache)
        line_cache_index_keys = sum(len(keys) for keys in conv._cache_keys_by_turn.values())
        block_cache_entries = len(conv._block_strip_cache)

    tracing = tracemalloc.is_tracing()
    if tracing:
        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    else:
        current_bytes, peak_bytes = 0, 0

    return {
        "domain_completed_turns": completed_turns,
        "domain_active_streams": active_streams,
        "analytics_turns": analytics_turns,
        "rendered_turns": rendered_turns,
        "line_cache_entries": line_cache_entries,
        "line_cache_index_keys": line_cache_index_keys,
        "block_cache_entries": block_cache_entries,
        "python_alloc_current_bytes": int(current_bytes),
        "python_alloc_peak_bytes": int(peak_bytes),
        "python_alloc_tracing": 1 if tracing else 0,
    }
