"""Deterministic memory soak harness for regression checks."""

from __future__ import annotations

import argparse
import json
import os
import tracemalloc
from dataclasses import asdict, dataclass

import cc_dump.core.formatting
from cc_dump.app.analytics_store import AnalyticsStore
from cc_dump.app.domain_store import DomainStore
from cc_dump.pipeline.event_types import RequestBodyEvent, RequestHeadersEvent, ResponseCompleteEvent
from cc_dump.pipeline.har_recorder import HARRecordingSubscriber
from cc_dump.tui.widget_factory import ConversationView
from textual.strip import Strip


@dataclass(frozen=True)
class SoakSnapshot:
    turn: int
    analytics_turns: int
    domain_completed_turns: int
    har_pending_requests: int
    line_cache_entries: int
    line_cache_index_keys: int
    line_cache_maxsize: int
    python_alloc_current_bytes: int
    python_alloc_peak_bytes: int


def _snapshot(
    *,
    turn: int,
    analytics_store: AnalyticsStore,
    domain_store: DomainStore,
    har_subscriber: HARRecordingSubscriber,
    conv: ConversationView,
) -> SoakSnapshot:
    tracing = tracemalloc.is_tracing()
    if tracing:
        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    else:
        current_bytes, peak_bytes = 0, 0

    return SoakSnapshot(
        turn=turn,
        analytics_turns=analytics_store.turn_count,
        domain_completed_turns=domain_store.completed_count,
        har_pending_requests=len(har_subscriber._pending_by_request),
        line_cache_entries=len(conv._line_cache),
        line_cache_index_keys=sum(len(keys) for keys in conv._cache_keys_by_turn.values()),
        line_cache_maxsize=conv._line_cache.maxsize,
        python_alloc_current_bytes=int(current_bytes),
        python_alloc_peak_bytes=int(peak_bytes),
    )


def run_memory_soak(
    *,
    turns: int = 1200,
    snapshot_interval: int = 200,
    har_max_pending: int = 64,
) -> list[SoakSnapshot]:
    """Run deterministic synthetic workload and return periodic snapshots.

    The harness drives core long-session state owners:
    - AnalyticsStore turn accumulation
    - DomainStore completed turn accumulation
    - HAR pending-request tracking under incomplete request churn
    - ConversationView line-cache index churn with periodic prune
    """
    if turns <= 0:
        return []

    original_har_cap = os.environ.get("CC_DUMP_HAR_MAX_PENDING")
    os.environ["CC_DUMP_HAR_MAX_PENDING"] = str(max(1, har_max_pending))

    started_tracing_here = False
    if not tracemalloc.is_tracing():
        tracemalloc.start(25)
        started_tracing_here = True

    analytics_store = AnalyticsStore()
    domain_store = DomainStore()
    conv = ConversationView()
    har_subscriber = HARRecordingSubscriber("/tmp/cc-dump-memory-soak.har")

    snapshots: list[SoakSnapshot] = []
    try:
        for i in range(1, turns + 1):
            request_id = f"req-{i}"

            request_body = {
                "model": "claude-3-opus-20240229",
                "messages": [{"role": "user", "content": f"Turn {i}"}],
            }
            complete_body = {
                "id": f"msg-{i}",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "ok"}],
                "model": "claude-3-opus-20240229",
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }

            analytics_store.on_event(RequestBodyEvent(body=request_body, request_id=request_id))
            analytics_store.on_event(
                ResponseCompleteEvent(body=complete_body, request_id=request_id)
            )
            domain_store.add_turn(
                [
                    cc_dump.core.formatting.TextContentBlock(
                        content=f"turn {i}",
                        category=cc_dump.core.formatting.Category.ASSISTANT,
                    )
                ]
            )

            # Incomplete HAR request churn (no response complete) exercises pending cap.
            har_subscriber.on_event(RequestHeadersEvent(headers={}, request_id=request_id))

            # Cache-index churn with LRU-bounded cache + periodic prune.
            cache_key = ("line", i)
            conv._line_cache[cache_key] = Strip.blank(10)
            conv._cache_keys_by_turn[i] = {cache_key}
            conv._line_cache_index_write_count += 1
            if conv._line_cache_index_write_count >= conv._line_cache_index_prune_interval:
                conv._line_cache_index_write_count = 0
                conv._prune_line_cache_index()

            if (i % snapshot_interval) == 0 or i == turns:
                conv._prune_line_cache_index()
                snapshots.append(
                    _snapshot(
                        turn=i,
                        analytics_store=analytics_store,
                        domain_store=domain_store,
                        har_subscriber=har_subscriber,
                        conv=conv,
                    )
                )
    finally:
        har_subscriber.close()
        if original_har_cap is None:
            os.environ.pop("CC_DUMP_HAR_MAX_PENDING", None)
        else:
            os.environ["CC_DUMP_HAR_MAX_PENDING"] = original_har_cap
        if started_tracing_here:
            tracemalloc.stop()

    return snapshots


def main() -> int:
    parser = argparse.ArgumentParser(description="Run cc-dump memory soak harness")
    parser.add_argument("--turns", type=int, default=1200)
    parser.add_argument("--snapshot-interval", type=int, default=200)
    parser.add_argument("--har-max-pending", type=int, default=64)
    args = parser.parse_args()

    snapshots = run_memory_soak(
        turns=args.turns,
        snapshot_interval=args.snapshot_interval,
        har_max_pending=args.har_max_pending,
    )
    print(json.dumps([asdict(s) for s in snapshots], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
