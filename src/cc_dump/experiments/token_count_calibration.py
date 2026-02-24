"""Token-count calibration report builder for HAR corpora.

Compares per-request input token totals across:
1) provider-reported usage from HAR responses,
2) local tiktoken estimates from request payloads,
3) optional Anthropic count_tokens measurements supplied via JSON map.

Usage:
    uv run python -m cc_dump.experiments.token_count_calibration path/to/file.har --json
    uv run python -m cc_dump.experiments.token_count_calibration a.har b.har --count-map count_tokens.json
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any

from cc_dump.core.token_counter import count_tokens


@dataclass(frozen=True)
class TokenComparisonRow:
    request_key: str
    source_file: str
    entry_index: int
    started_at: str
    model: str
    bucket: str
    message_count: int
    tool_use_count: int
    has_cache_read: bool
    has_cache_creation: bool
    provider_input_tokens: int
    provider_cache_read_tokens: int
    provider_cache_creation_tokens: int
    provider_total_input_tokens: int
    tiktoken_input_tokens: int
    tiktoken_delta_tokens: int
    tiktoken_abs_delta_pct: float
    count_tokens_input_tokens: int | None
    count_tokens_delta_tokens: int | None
    count_tokens_abs_delta_pct: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_pct(delta: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((abs(delta) / denominator) * 100.0, 4)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    # [LAW:verifiable-goals] Deterministic percentile selection; no random tie behavior.
    rank = (len(ordered) - 1) * (percentile / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[low])
    fraction = rank - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * fraction)


def _entry_request_key(
    *,
    source_file: str,
    entry_index: int,
    entry: dict[str, Any],
    response_body: dict[str, Any],
) -> str:
    response_id = str(response_body.get("id", "")).strip()
    if response_id:
        return response_id
    marker_data = entry.get("_cc_dump", {})
    if isinstance(marker_data, dict):
        run_id = str(marker_data.get("run_id", "")).strip()
        if run_id:
            return run_id
    return f"{source_file}:{entry_index}"


def _request_shape_bucket(
    *,
    estimated_tokens: int,
    tool_use_count: int,
    has_cache_read: bool,
    has_cache_creation: bool,
    content_types: set[str],
) -> str:
    size_bucket = "short" if estimated_tokens < 400 else "medium" if estimated_tokens < 2_000 else "long"
    tool_bucket = "tool_heavy" if tool_use_count >= 3 else "tool_light"
    cache_bucket = "cached" if (has_cache_read or has_cache_creation) else "uncached"
    if not content_types:
        content_bucket = "content_unknown"
    elif content_types == {"text"}:
        content_bucket = "content_text_only"
    elif len(content_types) == 1:
        only = next(iter(content_types))
        content_bucket = f"content_{only}"
    else:
        content_bucket = "content_mixed"
    return f"{size_bucket}:{tool_bucket}:{cache_bucket}:{content_bucket}"


def _extract_request_shape(request_body: dict[str, Any]) -> tuple[int, int, set[str]]:
    messages = request_body.get("messages", [])
    if not isinstance(messages, list):
        return 0, 0, set()
    message_count = len(messages)
    tool_use_count = 0
    content_types: set[str] = set()
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content", "")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = str(block.get("type", "")).strip()
                if block_type:
                    content_types.add(block_type)
                if block_type == "tool_use":
                    tool_use_count += 1
        elif isinstance(content, str):
            content_types.add("text")
    return message_count, tool_use_count, content_types


def _estimate_request_tokens(request_body: dict[str, Any]) -> int:
    payload = json.dumps(request_body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return count_tokens(payload)


def _load_har_entries(paths: list[str]) -> list[tuple[str, int, dict[str, Any]]]:
    indexed_entries: list[tuple[str, int, dict[str, Any]]] = []
    for path in paths:
        source_file = Path(path).name
        with open(path, encoding="utf-8") as f:
            har = json.load(f)
        entries = har.get("log", {}).get("entries", [])
        if not isinstance(entries, list):
            continue
        for idx, entry in enumerate(entries):
            if isinstance(entry, dict):
                indexed_entries.append((source_file, idx, entry))
    return indexed_entries


def _normalize_count_map(payload: object) -> dict[str, int]:
    # [LAW:one-source-of-truth] All count-map forms normalize to one canonical key->int map.
    normalized: dict[str, int] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized[str(key)] = _safe_int(value)
        return normalized
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            key = str(item.get("request_key", "")).strip()
            if not key:
                continue
            normalized[key] = _safe_int(item.get("count_tokens_input_tokens"))
    return normalized


def load_count_map(path: str) -> dict[str, int]:
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    return _normalize_count_map(payload)


def _lookup_count_tokens(
    *,
    count_map: dict[str, int],
    request_key: str,
    source_file: str,
    entry_index: int,
) -> int | None:
    if request_key in count_map:
        return count_map[request_key]
    fallback_key = f"{source_file}:{entry_index}"
    if fallback_key in count_map:
        return count_map[fallback_key]
    return None


def build_comparison_rows(
    *,
    har_files: list[str],
    count_map: dict[str, int] | None = None,
) -> list[TokenComparisonRow]:
    count_map = count_map or {}
    rows: list[TokenComparisonRow] = []
    for source_file, entry_index, entry in _load_har_entries(har_files):
        request_text = str(entry.get("request", {}).get("postData", {}).get("text", "")).strip()
        response_text = str(entry.get("response", {}).get("content", {}).get("text", "")).strip()
        if not request_text or not response_text:
            continue
        try:
            request_body = json.loads(request_text)
            response_body = json.loads(response_text)
        except json.JSONDecodeError:
            continue
        usage = response_body.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}

        provider_input_tokens = _safe_int(usage.get("input_tokens"))
        provider_cache_read_tokens = _safe_int(usage.get("cache_read_input_tokens"))
        provider_cache_creation_tokens = _safe_int(usage.get("cache_creation_input_tokens"))
        provider_total_input_tokens = (
            provider_input_tokens + provider_cache_read_tokens + provider_cache_creation_tokens
        )
        if provider_total_input_tokens <= 0:
            continue

        tiktoken_tokens = _estimate_request_tokens(request_body)
        tiktoken_delta = tiktoken_tokens - provider_total_input_tokens
        message_count, tool_use_count, content_types = _extract_request_shape(request_body)
        has_cache_read = provider_cache_read_tokens > 0
        has_cache_creation = provider_cache_creation_tokens > 0
        bucket = _request_shape_bucket(
            estimated_tokens=tiktoken_tokens,
            tool_use_count=tool_use_count,
            has_cache_read=has_cache_read,
            has_cache_creation=has_cache_creation,
            content_types=content_types,
        )
        request_key = _entry_request_key(
            source_file=source_file,
            entry_index=entry_index,
            entry=entry,
            response_body=response_body,
        )
        count_tokens_input = _lookup_count_tokens(
            count_map=count_map,
            request_key=request_key,
            source_file=source_file,
            entry_index=entry_index,
        )
        count_tokens_delta = (
            count_tokens_input - provider_total_input_tokens if count_tokens_input is not None else None
        )
        count_tokens_delta_pct = (
            _safe_pct(count_tokens_delta, provider_total_input_tokens)
            if count_tokens_delta is not None
            else None
        )
        rows.append(
            TokenComparisonRow(
                request_key=request_key,
                source_file=source_file,
                entry_index=entry_index,
                started_at=str(entry.get("startedDateTime", "")),
                model=str(request_body.get("model", "")),
                bucket=bucket,
                message_count=message_count,
                tool_use_count=tool_use_count,
                has_cache_read=has_cache_read,
                has_cache_creation=has_cache_creation,
                provider_input_tokens=provider_input_tokens,
                provider_cache_read_tokens=provider_cache_read_tokens,
                provider_cache_creation_tokens=provider_cache_creation_tokens,
                provider_total_input_tokens=provider_total_input_tokens,
                tiktoken_input_tokens=tiktoken_tokens,
                tiktoken_delta_tokens=tiktoken_delta,
                tiktoken_abs_delta_pct=_safe_pct(tiktoken_delta, provider_total_input_tokens),
                count_tokens_input_tokens=count_tokens_input,
                count_tokens_delta_tokens=count_tokens_delta,
                count_tokens_abs_delta_pct=count_tokens_delta_pct,
            )
        )
    return rows


def _summarize_deltas(deltas: list[int], pct_deltas: list[float]) -> dict[str, float]:
    if not deltas:
        return {
            "request_count": 0.0,
            "mean_delta_tokens": 0.0,
            "median_delta_tokens": 0.0,
            "mean_abs_delta_tokens": 0.0,
            "p95_abs_delta_pct": 0.0,
            "max_abs_delta_tokens": 0.0,
        }
    abs_deltas = [abs(value) for value in deltas]
    return {
        "request_count": float(len(deltas)),
        "mean_delta_tokens": round(statistics.mean(deltas), 4),
        "median_delta_tokens": round(float(statistics.median(deltas)), 4),
        "mean_abs_delta_tokens": round(statistics.mean(abs_deltas), 4),
        "p95_abs_delta_pct": round(_percentile(pct_deltas, 95.0), 4),
        "max_abs_delta_tokens": float(max(abs_deltas)),
    }


def _summarize_rows(rows: list[TokenComparisonRow]) -> dict[str, Any]:
    tiktoken_deltas = [row.tiktoken_delta_tokens for row in rows]
    tiktoken_pct = [row.tiktoken_abs_delta_pct for row in rows]
    count_rows = [row for row in rows if row.count_tokens_delta_tokens is not None]
    count_deltas = [int(row.count_tokens_delta_tokens) for row in count_rows]
    count_pct = [float(row.count_tokens_abs_delta_pct or 0.0) for row in count_rows]
    summary: dict[str, Any] = {
        "tiktoken_vs_provider": _summarize_deltas(tiktoken_deltas, tiktoken_pct),
        "count_tokens_vs_provider": _summarize_deltas(count_deltas, count_pct),
    }
    by_bucket: dict[str, list[TokenComparisonRow]] = {}
    for row in rows:
        by_bucket.setdefault(row.bucket, []).append(row)
    stratified: dict[str, Any] = {}
    for bucket, bucket_rows in sorted(by_bucket.items()):
        stratified[bucket] = {
            "tiktoken_vs_provider": _summarize_deltas(
                [row.tiktoken_delta_tokens for row in bucket_rows],
                [row.tiktoken_abs_delta_pct for row in bucket_rows],
            ),
            "count_tokens_vs_provider": _summarize_deltas(
                [int(row.count_tokens_delta_tokens) for row in bucket_rows if row.count_tokens_delta_tokens is not None],
                [float(row.count_tokens_abs_delta_pct or 0.0) for row in bucket_rows if row.count_tokens_delta_tokens is not None],
            ),
        }
    summary["stratified_by_bucket"] = stratified
    mismatch_rank = sorted(
        (
            {
                "bucket": bucket,
                "request_count": data["tiktoken_vs_provider"]["request_count"],
                "mean_abs_delta_tokens": data["tiktoken_vs_provider"]["mean_abs_delta_tokens"],
                "p95_abs_delta_pct": data["tiktoken_vs_provider"]["p95_abs_delta_pct"],
            }
            for bucket, data in stratified.items()
        ),
        key=lambda row: (-float(row["p95_abs_delta_pct"]), -float(row["mean_abs_delta_tokens"]), row["bucket"]),
    )
    summary["known_mismatch_categories"] = mismatch_rank[:8]
    return summary


def _derive_proposed_algorithm(rows: list[TokenComparisonRow]) -> dict[str, Any]:
    deltas_by_bucket: dict[str, list[int]] = {}
    all_deltas: list[int] = []
    for row in rows:
        delta = row.provider_total_input_tokens - row.tiktoken_input_tokens
        all_deltas.append(delta)
        deltas_by_bucket.setdefault(row.bucket, []).append(delta)
    bucket_bias_tokens = {
        bucket: int(round(statistics.median(values)))
        for bucket, values in sorted(deltas_by_bucket.items())
        if values
    }
    global_bias_tokens = int(round(statistics.median(all_deltas))) if all_deltas else 0
    return {
        "canonical_input_source": (
            "response.usage.input_tokens + response.usage.cache_read_input_tokens + "
            "response.usage.cache_creation_input_tokens"
        ),
        "fallback_estimator_formula": (
            "estimate = tiktoken(request_json) + bucket_bias_tokens.get(bucket, global_bias_tokens)"
        ),
        "global_bias_tokens": global_bias_tokens,
        "bucket_bias_tokens": bucket_bias_tokens,
        "notes": [
            "Use provider usage totals as authoritative display value when available.",
            "Use fallback estimate only for in-flight or missing-usage scenarios.",
        ],
    }


def build_report(rows: list[TokenComparisonRow]) -> dict[str, Any]:
    summary = _summarize_rows(rows)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "request_count": len(rows),
        "rows": [row.to_dict() for row in rows],
        "summary": summary,
        "proposed_algorithm": _derive_proposed_algorithm(rows),
    }


def _print_human_report(report: dict[str, Any]) -> None:
    summary = report["summary"]["tiktoken_vs_provider"]
    print("Token Calibration Report")
    print("=======================")
    print(f"Requests: {report['request_count']}")
    print(
        "tiktoken vs provider: mean_delta={:.2f} median_delta={:.2f} "
        "mean_abs_delta={:.2f} p95_abs_pct={:.2f}% max_abs_delta={:.0f}".format(
            float(summary["mean_delta_tokens"]),
            float(summary["median_delta_tokens"]),
            float(summary["mean_abs_delta_tokens"]),
            float(summary["p95_abs_delta_pct"]),
            float(summary["max_abs_delta_tokens"]),
        )
    )
    print("\nTop mismatch buckets:")
    for row in report["summary"]["known_mismatch_categories"]:
        print(
            "  - {bucket}: n={request_count:.0f} mean_abs={mean_abs_delta_tokens:.1f} "
            "p95_abs_pct={p95_abs_delta_pct:.2f}%".format(**row)
        )
    print("\nProposed estimator fallback:")
    algo = report["proposed_algorithm"]
    print(f"  canonical: {algo['canonical_input_source']}")
    print(f"  fallback:  {algo['fallback_estimator_formula']}")
    print(f"  global bias: {algo['global_bias_tokens']} tokens")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Token-count calibration report from HAR corpora")
    parser.add_argument("har_files", nargs="+", help="HAR file paths")
    parser.add_argument(
        "--count-map",
        default="",
        help="Optional JSON file with Anthropic count_tokens results keyed by request_key or file:index",
    )
    parser.add_argument("--output", default="", help="Optional output JSON report path")
    parser.add_argument("--json", action="store_true", help="Print full JSON report to stdout")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    count_map = load_count_map(args.count_map) if args.count_map else {}
    rows = build_comparison_rows(har_files=args.har_files, count_map=count_map)
    if not rows:
        sys.stderr.write("no comparable HAR rows found\n")
        return 2
    report = build_report(rows)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            f.write("\n")
    if args.json:
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        _print_human_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
