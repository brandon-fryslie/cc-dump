"""Synthetic benchmark: interception latency vs stdout-only collection.

This benchmark models a single side-channel run with configurable startup and
per-token delay. It compares:
1) stdout-only: first visible token occurs after subprocess completes
2) interception: first visible token occurs when first stream chunk arrives

Usage:
    uv run python benchmarks/bench_side_channel_latency.py
    uv run python benchmarks/bench_side_channel_latency.py --runs 100 --json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    startup_ms: float
    token_delay_ms: float
    token_count: int
    interception_overhead_ms: float


@dataclass(frozen=True)
class RunResult:
    first_token_stdout_ms: float
    first_token_intercept_ms: float
    total_stdout_ms: float
    total_intercept_ms: float


def simulate_run(s: Scenario) -> RunResult:
    stream_duration_ms = s.token_delay_ms * s.token_count
    total_ms = s.startup_ms + stream_duration_ms
    first_intercept_ms = s.startup_ms + s.token_delay_ms + s.interception_overhead_ms
    first_stdout_ms = total_ms  # stdout-only consumer sees data at process end
    total_intercept_ms = total_ms + s.interception_overhead_ms
    return RunResult(
        first_token_stdout_ms=first_stdout_ms,
        first_token_intercept_ms=first_intercept_ms,
        total_stdout_ms=total_ms,
        total_intercept_ms=total_intercept_ms,
    )


def summarize(results: list[RunResult]) -> dict[str, float]:
    first_stdout = [r.first_token_stdout_ms for r in results]
    first_intercept = [r.first_token_intercept_ms for r in results]
    total_stdout = [r.total_stdout_ms for r in results]
    total_intercept = [r.total_intercept_ms for r in results]
    return {
        "runs": float(len(results)),
        "first_token_stdout_ms_mean": statistics.mean(first_stdout),
        "first_token_intercept_ms_mean": statistics.mean(first_intercept),
        "first_token_delta_ms_mean": statistics.mean(
            [a - b for a, b in zip(first_stdout, first_intercept, strict=False)]
        ),
        "total_stdout_ms_mean": statistics.mean(total_stdout),
        "total_intercept_ms_mean": statistics.mean(total_intercept),
        "total_delta_ms_mean": statistics.mean(
            [a - b for a, b in zip(total_stdout, total_intercept, strict=False)]
        ),
    }


def print_report(summary_stats: dict[str, float], scenario: Scenario) -> None:
    print("\n============================================================")
    print("  Side-Channel Latency Benchmark (Synthetic)")
    print("============================================================")
    print(
        "  scenario: startup={:.0f}ms token_delay={:.0f}ms tokens={} "
        "interception_overhead={:.1f}ms".format(
            scenario.startup_ms,
            scenario.token_delay_ms,
            scenario.token_count,
            scenario.interception_overhead_ms,
        )
    )
    print("  runs:     {}".format(int(summary_stats["runs"])))
    print("")
    print(
        "  first token: stdout-only={:.1f}ms  intercept={:.1f}ms  delta={:.1f}ms".format(
            summary_stats["first_token_stdout_ms_mean"],
            summary_stats["first_token_intercept_ms_mean"],
            summary_stats["first_token_delta_ms_mean"],
        )
    )
    print(
        "  total:       stdout-only={:.1f}ms  intercept={:.1f}ms  delta={:.1f}ms".format(
            summary_stats["total_stdout_ms_mean"],
            summary_stats["total_intercept_ms_mean"],
            summary_stats["total_delta_ms_mean"],
        )
    )
    print("============================================================\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark side-channel interception latency")
    parser.add_argument("--runs", type=int, default=50, help="Number of simulated runs")
    parser.add_argument("--startup-ms", type=float, default=900.0, help="Process/model startup latency")
    parser.add_argument("--token-delay-ms", type=float, default=18.0, help="Average token/chunk delay")
    parser.add_argument("--tokens", type=int, default=80, help="Number of streamed tokens/chunks")
    parser.add_argument(
        "--interception-overhead-ms",
        type=float,
        default=2.0,
        help="Proxy interception overhead added to interception path",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    scenario = Scenario(
        startup_ms=max(0.0, args.startup_ms),
        token_delay_ms=max(0.1, args.token_delay_ms),
        token_count=max(1, args.tokens),
        interception_overhead_ms=max(0.0, args.interception_overhead_ms),
    )
    runs = max(1, args.runs)

    results = [simulate_run(scenario) for _ in range(runs)]
    summary_stats = summarize(results)

    payload = {
        "scenario": {
            "startup_ms": scenario.startup_ms,
            "token_delay_ms": scenario.token_delay_ms,
            "token_count": scenario.token_count,
            "interception_overhead_ms": scenario.interception_overhead_ms,
        },
        "summary": summary_stats,
    }

    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    print_report(summary_stats, scenario)


if __name__ == "__main__":
    main()
