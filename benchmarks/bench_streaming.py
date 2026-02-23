"""Repeatable benchmark for streaming-response latency through the format pipeline.

Generates synthetic SSE events matching a realistic Claude response and measures
format-pipeline latency (event_types → formatting → blocks) plus queue-delay
simulation using the perf_metrics collector.

Usage:
    uv run python benchmarks/bench_streaming.py             # default 500 deltas
    uv run python benchmarks/bench_streaming.py --deltas 2000
    uv run python benchmarks/bench_streaming.py --json       # machine-readable output
"""

import argparse
import json
import sys
import time
import tracemalloc

from cc_dump.pipeline.event_types import (
    MessageStartEvent,
    MessageInfo,
    MessageRole,
    Usage,
    TextDeltaEvent,
    ContentBlockStopEvent,
    MessageDeltaEvent,
    MessageStopEvent,
    StopReason,
    ResponseSSEEvent,
    ResponseDoneEvent,
    TextBlockStartEvent,
)
from cc_dump.core.formatting import format_response_event
from cc_dump.experiments.perf_metrics import MetricsCollector


def generate_sse_stream(n_deltas: int) -> list[ResponseSSEEvent]:
    """Build a realistic SSE event sequence for one assistant turn.

    Sequence: message_start → text_block_start → N text_deltas →
              content_block_stop → message_delta(end_turn) → message_stop
    """
    events: list[ResponseSSEEvent] = []
    seq = 0

    def _wrap(sse, *, request_id: str = "bench-req-1") -> ResponseSSEEvent:
        nonlocal seq
        seq += 1
        return ResponseSSEEvent(
            sse_event=sse,
            request_id=request_id,
            seq=seq,
            recv_ns=time.monotonic_ns(),
        )

    events.append(_wrap(MessageStartEvent(
        message=MessageInfo(
            id="msg_bench",
            role=MessageRole.ASSISTANT,
            model="claude-sonnet-4-20250514",
            usage=Usage(input_tokens=1000, output_tokens=0,
                        cache_read_input_tokens=800,
                        cache_creation_input_tokens=0),
        ),
    )))

    events.append(_wrap(TextBlockStartEvent(index=0)))

    # Realistic token-sized chunks (~4-15 chars each)
    chunk_texts = [
        "The ", "quick ", "brown ", "fox ", "jumps ", "over ", "the ", "lazy ", "dog. ",
        "Here ", "is ", "some ", "additional ", "text ", "to ", "simulate ", "a ",
        "realistic ", "streaming ", "response ", "from ", "Claude. ",
    ]
    for i in range(n_deltas):
        text = chunk_texts[i % len(chunk_texts)]
        events.append(_wrap(TextDeltaEvent(index=0, text=text)))

    events.append(_wrap(ContentBlockStopEvent(index=0)))
    events.append(_wrap(MessageDeltaEvent(
        stop_reason=StopReason.END_TURN, stop_sequence="", output_tokens=n_deltas,
    )))
    events.append(_wrap(MessageStopEvent()))

    return events


def run_benchmark(n_deltas: int) -> dict:
    """Run the streaming format benchmark and return results dict."""
    collector = MetricsCollector()
    collector.enabled = True

    events = generate_sse_stream(n_deltas)

    # --- Memory tracking ---
    tracemalloc.start()
    mem_before = tracemalloc.get_traced_memory()

    # --- Format pipeline benchmark ---
    wall_start = time.monotonic_ns()

    for event in events:
        fmt_start = time.monotonic_ns()
        blocks = format_response_event(event.sse_event)
        collector.mark("format", since_ns=fmt_start)

        # Simulate queue delay: time from recv_ns to format start
        collector.record("queue_delay", elapsed_ns=fmt_start - event.recv_ns)

        # Count blocks produced (lightweight, exercises the return path)
        _ = len(blocks)

    wall_elapsed_ns = time.monotonic_ns() - wall_start

    mem_after = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    snapshot = collector.snapshot()

    return {
        "n_deltas": n_deltas,
        "n_events": len(events),
        "wall_time_ms": wall_elapsed_ns / 1_000_000,
        "mem_peak_kb": mem_after[1] / 1024,
        "mem_current_kb": mem_after[0] / 1024,
        "mem_before_kb": mem_before[0] / 1024,
        "stages": {
            name: {
                "count": stats.count,
                "min_us": round(stats.min_us, 2),
                "max_us": round(stats.max_us, 2),
                "mean_us": round(stats.mean_us, 2),
                "p50_us": round(stats.p50_us, 2),
                "p95_us": round(stats.p95_us, 2),
                "p99_us": round(stats.p99_us, 2),
            }
            for name, stats in snapshot.items()
        },
    }


def print_report(results: dict) -> None:
    """Print a human-readable benchmark report."""
    print(f"\n{'='*60}")
    print(f"  Streaming Format Benchmark")
    print(f"{'='*60}")
    print(f"  Events:     {results['n_events']} ({results['n_deltas']} text deltas)")
    print(f"  Wall time:  {results['wall_time_ms']:.1f} ms")
    print(f"  Memory:     {results['mem_peak_kb']:.0f} KB peak, "
          f"{results['mem_current_kb']:.0f} KB current")
    print()

    for stage_name, stats in results["stages"].items():
        print(f"  [{stage_name}] ({stats['count']} samples)")
        print(f"    min={stats['min_us']:.1f}us  "
              f"p50={stats['p50_us']:.1f}us  "
              f"p95={stats['p95_us']:.1f}us  "
              f"p99={stats['p99_us']:.1f}us  "
              f"max={stats['max_us']:.1f}us")
        print()

    print(f"{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Streaming format pipeline benchmark")
    parser.add_argument("--deltas", type=int, default=500,
                        help="Number of text delta events (default: 500)")
    parser.add_argument("--json", action="store_true",
                        help="Output machine-readable JSON")
    args = parser.parse_args()

    results = run_benchmark(args.deltas)

    if args.json:
        json.dump(results, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print_report(results)


if __name__ == "__main__":
    main()
