#!/usr/bin/env python3
"""Deterministic session insight artifact generator for HAR recordings.

Produces grouped artifacts:
1) per-turn metrics
2) rolling degradation
3) cut recommendation
4) seed context
5) budget attribution by purpose
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from cc_dump.har_checkpoint_diff import load_har_entries
from cc_dump.session_insights import build_session_insights


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate deterministic session insight artifacts.")
    parser.add_argument("--har", required=True, help="Path to HAR file")
    parser.add_argument("--session-id", help="Optional explicit session ID")
    parser.add_argument("--output-dir", default="/tmp/cc-dump-context-pruner", help="Output directory")
    parser.add_argument(
        "--rolling-window-size",
        type=int,
        default=6,
        help="Rolling window size for degradation scoring.",
    )
    parser.add_argument(
        "--estimator-overhead-tokens",
        type=int,
        default=0,
        help="Fixed token overhead added to tiktoken input estimate for calibration.",
    )
    parser.add_argument("--max-seed-messages", type=int, default=120, help="Max messages in seed output")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    har_path = Path(args.har)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = load_har_entries(har_path)
    artifacts = build_session_insights(
        entries,
        session_id=args.session_id,
        rolling_window_size=max(1, args.rolling_window_size),
        max_seed_messages=args.max_seed_messages,
        estimator_overhead_tokens=args.estimator_overhead_tokens,
    )

    stem = _safe_name(har_path.stem)
    if args.session_id:
        stem += f"-{_safe_name(args.session_id)}"
    turn_metrics_path = out_dir / f"{stem}-turn-metrics.json"
    rolling_path = out_dir / f"{stem}-rolling-degradation.json"
    tool_activity_path = out_dir / f"{stem}-tool-activity-raw.json"
    test_suite_path = out_dir / f"{stem}-test-suite-analysis.json"
    token_health_path = out_dir / f"{stem}-token-estimation-health.json"
    cut_path = out_dir / f"{stem}-cut-recommendation.json"
    seed_path = out_dir / f"{stem}-seed-context.json"
    budget_path = out_dir / f"{stem}-budget-by-purpose.json"
    manifest_path = out_dir / f"{stem}-manifest.json"

    turn_metrics_path.write_text(
        json.dumps([row.to_dict() for row in artifacts.turn_metrics], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rolling_path.write_text(
        json.dumps([row.to_dict() for row in artifacts.rolling_degradation], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tool_activity_path.write_text(
        json.dumps([row.to_dict() for row in artifacts.tool_activity_raw], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    test_suite_path.write_text(
        json.dumps(artifacts.test_suite_analysis, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    token_health_path.write_text(
        json.dumps(artifacts.token_estimation_health, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    cut_path.write_text(json.dumps(artifacts.cut_recommendation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seed_path.write_text(json.dumps(artifacts.seed_context, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    budget_path.write_text(json.dumps(artifacts.budget_by_purpose, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = {
        "session_id": artifacts.session_id,
        "groups": {
            "analytics": {
                "turn_metrics": str(turn_metrics_path),
                "rolling_degradation": str(rolling_path),
                "tool_activity_raw": str(tool_activity_path),
                "test_suite_analysis": str(test_suite_path),
                "token_estimation_health": str(token_health_path),
                "budget_by_purpose": str(budget_path),
            },
            "pruning": {
                "cut_recommendation": str(cut_path),
                "seed_context": str(seed_path),
            },
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"turn_metrics={turn_metrics_path}")
    print(f"rolling_degradation={rolling_path}")
    print(f"tool_activity_raw={tool_activity_path}")
    print(f"test_suite_analysis={test_suite_path}")
    print(f"token_estimation_health={token_health_path}")
    print(f"cut_recommendation={cut_path}")
    print(f"seed_context={seed_path}")
    print(f"budget_by_purpose={budget_path}")
    print(f"manifest={manifest_path}")
    print(
        "summary="
        + json.dumps(
            {
                "session_id": artifacts.session_id,
                "recommended_cut_index": artifacts.cut_recommendation["recommended_cut_index"],
                "keep_range": [
                    artifacts.cut_recommendation["keep_range_start"],
                    artifacts.cut_recommendation["keep_range_end"],
                ],
                "drop_range": [
                    artifacts.cut_recommendation["drop_range_start"],
                    artifacts.cut_recommendation["drop_range_end"],
                ],
                "dropped_entry_count": artifacts.cut_recommendation["dropped_entry_count"],
                "seed_message_count": len(artifacts.seed_context["seed_messages"]),
                "turn_metric_rows": len(artifacts.turn_metrics),
                "tool_activity_rows": len(artifacts.tool_activity_raw),
                "test_rerun_token_cost_exact": artifacts.test_suite_analysis["rerun_token_cost_exact"],
                "test_rerun_token_cost_ambiguous": artifacts.test_suite_analysis["rerun_token_cost_ambiguous"],
                "token_delta_over_10pct_requests": artifacts.token_estimation_health["requests_over_10pct"],
                "token_delta_over_10pct_requests_adjusted": artifacts.token_estimation_health[
                    "requests_over_10pct_adjusted"
                ],
                "estimator_overhead_tokens": artifacts.token_estimation_health["estimator_overhead_tokens"],
            },
            sort_keys=True,
        )
    )
    return 0


def _safe_name(raw: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", raw).strip("-")


if __name__ == "__main__":
    raise SystemExit(main())
