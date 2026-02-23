"""Deterministic single-session insight pipeline.

// [LAW:one-source-of-truth] Insight artifact shapes and derivation logic are centralized here.
// [LAW:dataflow-not-control-flow] The same stages run for every session; variability is data-only.
// [LAW:verifiable-goals] Outputs are machine-checkable JSON artifacts.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import json
import re
import shlex
from typing import Any

from cc_dump.context_pruner import (
    build_context_prune_plan,
    extract_seed_messages,
    select_session_snapshots,
)
from cc_dump.har_checkpoint_diff import diff_checkpoints, snapshot_from_har_entry
from cc_dump.side_channel_marker import extract_marker
from cc_dump.token_counter import count_tokens


_CONSTRAINT_RE = re.compile(r"\b(do not|don't|must|never|only|without|cannot|can't)\b", re.IGNORECASE)
_DECISION_RE = re.compile(r"\b(decide|decision|we will|we should|plan|chosen|use)\b", re.IGNORECASE)
_PROGRESS_RE = re.compile(
    r"\b(done|completed|implemented|fixed|resolved|passed|merged|closed)\b", re.IGNORECASE
)
_ERROR_RE = re.compile(r"\b(error|failed|failure|exception|traceback|assert)\b", re.IGNORECASE)
_QUESTION_RE = re.compile(r"\?|(\bnext\b|\bremaining\b|\btodo\b|\bto do\b|\bneed to\b)", re.IGNORECASE)
_FAIL_RESULT_RE = re.compile(r"\b(fail|failed|failure|error|exception|traceback|assert)\b", re.IGNORECASE)


@dataclass(frozen=True)
class TurnMetric:
    entry_index: int
    started_at: str
    session_id: str
    model: str
    purpose: str
    comparison_mode: str
    shared_prefix_messages: int
    dropped_messages_from_previous: int
    appended_user_messages: int
    appended_assistant_messages: int
    interrupt_count: int
    repeated_command_count: int
    dominant_command_family: str
    dominant_command_family_count: int
    command_count: int
    tool_counts: dict[str, int]
    command_families: dict[str, int]
    input_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    output_tokens: int
    cache_hit_ratio: float
    estimated_input_tokens_tiktoken: int
    estimated_input_tokens_adjusted: int
    estimator_overhead_tokens: int
    reported_total_input_tokens: int
    input_token_delta: int
    input_token_delta_pct: float
    input_token_delta_adjusted: int
    input_token_delta_adjusted_pct: float
    progress_signal_count: int
    degradation_delta: int
    cumulative_degradation: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_index": self.entry_index,
            "started_at": self.started_at,
            "session_id": self.session_id,
            "model": self.model,
            "purpose": self.purpose,
            "comparison_mode": self.comparison_mode,
            "shared_prefix_messages": self.shared_prefix_messages,
            "dropped_messages_from_previous": self.dropped_messages_from_previous,
            "appended_user_messages": self.appended_user_messages,
            "appended_assistant_messages": self.appended_assistant_messages,
            "interrupt_count": self.interrupt_count,
            "repeated_command_count": self.repeated_command_count,
            "dominant_command_family": self.dominant_command_family,
            "dominant_command_family_count": self.dominant_command_family_count,
            "command_count": self.command_count,
            "tool_counts": dict(self.tool_counts),
            "command_families": dict(self.command_families),
            "input_tokens": self.input_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "output_tokens": self.output_tokens,
            "cache_hit_ratio": self.cache_hit_ratio,
            "estimated_input_tokens_tiktoken": self.estimated_input_tokens_tiktoken,
            "estimated_input_tokens_adjusted": self.estimated_input_tokens_adjusted,
            "estimator_overhead_tokens": self.estimator_overhead_tokens,
            "reported_total_input_tokens": self.reported_total_input_tokens,
            "input_token_delta": self.input_token_delta,
            "input_token_delta_pct": self.input_token_delta_pct,
            "input_token_delta_adjusted": self.input_token_delta_adjusted,
            "input_token_delta_adjusted_pct": self.input_token_delta_adjusted_pct,
            "progress_signal_count": self.progress_signal_count,
            "degradation_delta": self.degradation_delta,
            "cumulative_degradation": self.cumulative_degradation,
        }


@dataclass(frozen=True)
class RollingDegradationPoint:
    entry_index: int
    window_size: int
    window_start_entry: int
    window_end_entry: int
    avg_degradation: float
    max_degradation: int
    interrupt_sum: int
    repeated_command_sum: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_index": self.entry_index,
            "window_size": self.window_size,
            "window_start_entry": self.window_start_entry,
            "window_end_entry": self.window_end_entry,
            "avg_degradation": self.avg_degradation,
            "max_degradation": self.max_degradation,
            "interrupt_sum": self.interrupt_sum,
            "repeated_command_sum": self.repeated_command_sum,
        }


@dataclass(frozen=True)
class ToolActivityRecord:
    activity_id: str
    entry_index: int
    started_at: str
    session_id: str
    purpose: str
    model: str
    tool_name: str
    tool_use_id: str
    target_kind: str
    primary_target: str
    target_repeat_index: int
    is_repeat_target: bool
    command: str
    normalized_command: str
    command_family: str
    is_test_command: bool
    test_suite_key: str
    has_error_signal: bool
    result_excerpt: str
    turn_input_tokens: int
    turn_cache_read_tokens: int
    turn_cache_creation_tokens: int
    turn_output_tokens: int
    request_total_tokens: float
    request_tool_activity_count: int
    request_test_activity_count: int
    token_attribution_confidence: str
    exact_attributed_tokens: float
    tool_input_tokens: int
    tool_result_tokens: int
    input_payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "entry_index": self.entry_index,
            "started_at": self.started_at,
            "session_id": self.session_id,
            "purpose": self.purpose,
            "model": self.model,
            "tool_name": self.tool_name,
            "tool_use_id": self.tool_use_id,
            "target_kind": self.target_kind,
            "primary_target": self.primary_target,
            "target_repeat_index": self.target_repeat_index,
            "is_repeat_target": self.is_repeat_target,
            "command": self.command,
            "normalized_command": self.normalized_command,
            "command_family": self.command_family,
            "is_test_command": self.is_test_command,
            "test_suite_key": self.test_suite_key,
            "has_error_signal": self.has_error_signal,
            "result_excerpt": self.result_excerpt,
            "turn_input_tokens": self.turn_input_tokens,
            "turn_cache_read_tokens": self.turn_cache_read_tokens,
            "turn_cache_creation_tokens": self.turn_cache_creation_tokens,
            "turn_output_tokens": self.turn_output_tokens,
            "request_total_tokens": self.request_total_tokens,
            "request_tool_activity_count": self.request_tool_activity_count,
            "request_test_activity_count": self.request_test_activity_count,
            "token_attribution_confidence": self.token_attribution_confidence,
            "exact_attributed_tokens": self.exact_attributed_tokens,
            "tool_input_tokens": self.tool_input_tokens,
            "tool_result_tokens": self.tool_result_tokens,
            "input_payload": self.input_payload,
        }


@dataclass(frozen=True)
class SessionInsightArtifacts:
    session_id: str
    turn_metrics: tuple[TurnMetric, ...]
    rolling_degradation: tuple[RollingDegradationPoint, ...]
    tool_activity_raw: tuple[ToolActivityRecord, ...]
    test_suite_analysis: dict[str, Any]
    token_estimation_health: dict[str, Any]
    cut_recommendation: dict[str, Any]
    seed_context: dict[str, Any]
    budget_by_purpose: dict[str, dict[str, int | float]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_metrics": [metric.to_dict() for metric in self.turn_metrics],
            "rolling_degradation": [point.to_dict() for point in self.rolling_degradation],
            "tool_activity_raw": [record.to_dict() for record in self.tool_activity_raw],
            "test_suite_analysis": self.test_suite_analysis,
            "token_estimation_health": self.token_estimation_health,
            "cut_recommendation": self.cut_recommendation,
            "seed_context": self.seed_context,
            "budget_by_purpose": self.budget_by_purpose,
        }


def build_session_insights(
    entries: list[dict[str, Any]],
    *,
    session_id: str | None = None,
    rolling_window_size: int = 6,
    max_seed_messages: int = 120,
    estimator_overhead_tokens: int = 0,
) -> SessionInsightArtifacts:
    snapshots = [snapshot_from_har_entry(entry, idx) for idx, entry in enumerate(entries)]
    selected = select_session_snapshots(snapshots, session_id=session_id)
    if not selected:
        raise ValueError("no snapshots available for selected session")
    selected.sort(key=lambda snapshot: snapshot.entry_index)
    entry_by_index = {idx: entry for idx, entry in enumerate(entries)}
    turn_metrics = _build_turn_metrics(
        selected,
        entry_by_index,
        estimator_overhead_tokens=estimator_overhead_tokens,
    )
    rolling = _build_rolling_degradation(turn_metrics, rolling_window_size=rolling_window_size)
    tool_activity = _build_tool_activity_raw(selected, turn_metrics, entry_by_index)
    test_suite_analysis = _build_test_suite_analysis(tool_activity)
    token_estimation_health = _build_token_estimation_health(
        turn_metrics,
        estimator_overhead_tokens=estimator_overhead_tokens,
    )
    plan = build_context_prune_plan(selected)
    cut_recommendation = _plan_to_cut_recommendation(plan)
    chosen_snapshot = next(snapshot for snapshot in selected if snapshot.entry_index == plan.recommended_cut_index)
    seed_context = _build_seed_context(
        snapshot=chosen_snapshot,
        metrics=turn_metrics,
        keep_range=(plan.keep_range_start, plan.keep_range_end),
        max_seed_messages=max_seed_messages,
    )
    budget = _build_budget_by_purpose(turn_metrics)
    return SessionInsightArtifacts(
        session_id=selected[-1].session_id,
        turn_metrics=tuple(turn_metrics),
        rolling_degradation=tuple(rolling),
        tool_activity_raw=tuple(tool_activity),
        test_suite_analysis=test_suite_analysis,
        token_estimation_health=token_estimation_health,
        cut_recommendation=cut_recommendation,
        seed_context=seed_context,
        budget_by_purpose=budget,
    )


def _build_turn_metrics(
    snapshots: list[Any],
    entry_by_index: dict[int, dict[str, Any]],
    *,
    estimator_overhead_tokens: int,
) -> list[TurnMetric]:
    metrics: list[TurnMetric] = []
    cumulative_degradation = 0
    previous_snapshot = None
    for snapshot in snapshots:
        entry = entry_by_index[snapshot.entry_index]
        request_payload = json.loads(entry["request"]["postData"]["text"])
        marker = extract_marker(request_payload)
        purpose = marker.purpose if marker is not None else "primary"
        usage = snapshot.usage
        estimated_input = _estimate_request_input_tokens_tiktoken(request_payload)
        estimated_adjusted = estimated_input + estimator_overhead_tokens
        reported_total_input = (
            usage.input_tokens
            + usage.cache_read_input_tokens
            + usage.cache_creation_input_tokens
        )
        token_delta = estimated_input - reported_total_input
        token_delta_adjusted = estimated_adjusted - reported_total_input
        token_delta_pct = round((abs(token_delta) / reported_total_input) * 100.0, 4) if reported_total_input > 0 else 0.0
        token_delta_adjusted_pct = (
            round((abs(token_delta_adjusted) / reported_total_input) * 100.0, 4)
            if reported_total_input > 0
            else 0.0
        )
        if previous_snapshot is None:
            metric = TurnMetric(
                entry_index=snapshot.entry_index,
                started_at=snapshot.started_at,
                session_id=snapshot.session_id,
                model=snapshot.model,
                purpose=purpose,
                comparison_mode="origin",
                shared_prefix_messages=0,
                dropped_messages_from_previous=0,
                appended_user_messages=0,
                appended_assistant_messages=0,
                interrupt_count=0,
                repeated_command_count=0,
                dominant_command_family="",
                dominant_command_family_count=0,
                command_count=0,
                tool_counts={},
                command_families={},
                input_tokens=usage.input_tokens,
                cache_read_tokens=usage.cache_read_input_tokens,
                cache_creation_tokens=usage.cache_creation_input_tokens,
                output_tokens=usage.output_tokens,
                cache_hit_ratio=round(usage.cache_hit_ratio, 4),
                estimated_input_tokens_tiktoken=estimated_input,
                estimated_input_tokens_adjusted=estimated_adjusted,
                estimator_overhead_tokens=estimator_overhead_tokens,
                reported_total_input_tokens=reported_total_input,
                input_token_delta=token_delta,
                input_token_delta_pct=token_delta_pct,
                input_token_delta_adjusted=token_delta_adjusted,
                input_token_delta_adjusted_pct=token_delta_adjusted_pct,
                progress_signal_count=0,
                degradation_delta=0,
                cumulative_degradation=0,
            )
            metrics.append(metric)
            previous_snapshot = snapshot
            continue

        diff = diff_checkpoints(previous_snapshot, snapshot)
        family_counter = Counter(diff.appended_command_families)
        dominant_family, dominant_family_count = ("", 0)
        if family_counter:
            dominant_family, dominant_family_count = family_counter.most_common(1)[0]
        interrupt_count = sum(1 for text in diff.appended_user_messages if "[Request interrupted by user]" in text)
        repeated_command_count = sum(int(count) for count in diff.repeated_commands.values())
        progress_signal_count = _count_progress_signals(diff)
        degradation_delta = _compute_degradation_delta(
            interrupt_count=interrupt_count,
            repeated_command_count=repeated_command_count,
            command_count=len(diff.appended_commands),
            dominant_count=dominant_family_count,
            progress_signal_count=progress_signal_count,
            assistant_message_count=len(diff.appended_assistant_messages),
        )
        cumulative_degradation += degradation_delta
        metric = TurnMetric(
            entry_index=snapshot.entry_index,
            started_at=snapshot.started_at,
            session_id=snapshot.session_id,
            model=snapshot.model,
            purpose=purpose,
            comparison_mode=diff.comparison_mode,
            shared_prefix_messages=diff.lcp_messages,
            dropped_messages_from_previous=diff.dropped_messages_from_before,
            appended_user_messages=len(diff.appended_user_messages),
            appended_assistant_messages=len(diff.appended_assistant_messages),
            interrupt_count=interrupt_count,
            repeated_command_count=repeated_command_count,
            dominant_command_family=dominant_family,
            dominant_command_family_count=dominant_family_count,
            command_count=len(diff.appended_commands),
            tool_counts=dict(diff.appended_tool_counts),
            command_families=dict(diff.appended_command_families),
            input_tokens=usage.input_tokens,
            cache_read_tokens=usage.cache_read_input_tokens,
            cache_creation_tokens=usage.cache_creation_input_tokens,
            output_tokens=usage.output_tokens,
            cache_hit_ratio=round(usage.cache_hit_ratio, 4),
            estimated_input_tokens_tiktoken=estimated_input,
            estimated_input_tokens_adjusted=estimated_adjusted,
            estimator_overhead_tokens=estimator_overhead_tokens,
            reported_total_input_tokens=reported_total_input,
            input_token_delta=token_delta,
            input_token_delta_pct=token_delta_pct,
            input_token_delta_adjusted=token_delta_adjusted,
            input_token_delta_adjusted_pct=token_delta_adjusted_pct,
            progress_signal_count=progress_signal_count,
            degradation_delta=degradation_delta,
            cumulative_degradation=cumulative_degradation,
        )
        metrics.append(metric)
        previous_snapshot = snapshot
    return metrics


def _build_rolling_degradation(
    metrics: list[TurnMetric],
    *,
    rolling_window_size: int,
) -> list[RollingDegradationPoint]:
    points: list[RollingDegradationPoint] = []
    for idx, metric in enumerate(metrics):
        window_start = max(0, idx - rolling_window_size + 1)
        window = metrics[window_start : idx + 1]
        degradation_values = [point.degradation_delta for point in window]
        interrupt_values = [point.interrupt_count for point in window]
        repeated_values = [point.repeated_command_count for point in window]
        points.append(
            RollingDegradationPoint(
                entry_index=metric.entry_index,
                window_size=len(window),
                window_start_entry=window[0].entry_index,
                window_end_entry=window[-1].entry_index,
                avg_degradation=round(sum(degradation_values) / len(window), 4),
                max_degradation=max(degradation_values),
                interrupt_sum=sum(interrupt_values),
                repeated_command_sum=sum(repeated_values),
            )
        )
    return points


def _build_tool_activity_raw(
    snapshots: list[Any],
    metrics: list[TurnMetric],
    entry_by_index: dict[int, dict[str, Any]],
) -> list[ToolActivityRecord]:
    metric_by_entry = {metric.entry_index: metric for metric in metrics}
    target_counter: Counter[tuple[str, str]] = Counter()
    records: list[ToolActivityRecord] = []
    for index in range(1, len(snapshots)):
        before = snapshots[index - 1]
        after = snapshots[index]
        metric = metric_by_entry[after.entry_index]
        if metric.comparison_mode != "append_only":
            continue
        diff = diff_checkpoints(before, after)
        entry = entry_by_index[after.entry_index]
        request_payload = json.loads(entry["request"]["postData"]["text"])
        messages = request_payload.get("messages", [])
        if not isinstance(messages, list):
            continue
        appended_messages = messages[diff.lcp_messages :]
        tool_blocks = _extract_tool_use_blocks(appended_messages)
        if not tool_blocks:
            continue
        result_map = _extract_tool_result_map(appended_messages)
        test_count = sum(
            1
            for block in tool_blocks
            if _normalize_command(
                str(block.get("tool_name", "")),
                str(block.get("tool_input", {}).get("command", "")).strip(),
            )[2]
        )
        request_total_tokens = float(
            metric.input_tokens + metric.cache_read_tokens + metric.cache_creation_tokens + metric.output_tokens
        )
        for seq, block_data in enumerate(tool_blocks):
            tool_use_id = block_data.get("tool_use_id", "")
            tool_name = block_data.get("tool_name", "")
            tool_input = block_data.get("tool_input", {})
            target_kind, primary_target = _extract_target(tool_name, tool_input)
            target_key = (tool_name, primary_target) if primary_target else (tool_name, "")
            target_counter[target_key] += 1
            repeat_idx = target_counter[target_key]
            command = str(tool_input.get("command", "")).strip() if tool_name == "Bash" else ""
            normalized_command, command_family, is_test_command, test_suite_key = _normalize_command(tool_name, command)
            result_payload = result_map.get(tool_use_id, {})
            has_error_signal = bool(result_payload.get("has_error_signal", False))
            result_excerpt = str(result_payload.get("result_excerpt", ""))
            result_text = str(result_payload.get("result_text", ""))
            confidence = "exact_single_tool_request" if len(tool_blocks) == 1 else "ambiguous_multi_tool_request"
            exact_tokens = request_total_tokens if confidence == "exact_single_tool_request" else 0.0
            tool_input_tokens = count_tokens(json.dumps(tool_input, sort_keys=True))
            tool_result_tokens = count_tokens(result_text)
            record = ToolActivityRecord(
                activity_id=f"{after.entry_index}:{seq}:{tool_use_id or tool_name}",
                entry_index=after.entry_index,
                started_at=after.started_at,
                session_id=after.session_id,
                purpose=metric.purpose,
                model=after.model,
                tool_name=tool_name,
                tool_use_id=tool_use_id,
                target_kind=target_kind,
                primary_target=primary_target,
                target_repeat_index=repeat_idx,
                is_repeat_target=repeat_idx > 1 and bool(primary_target),
                command=command,
                normalized_command=normalized_command,
                command_family=command_family,
                is_test_command=is_test_command,
                test_suite_key=test_suite_key,
                has_error_signal=has_error_signal,
                result_excerpt=result_excerpt,
                turn_input_tokens=metric.input_tokens,
                turn_cache_read_tokens=metric.cache_read_tokens,
                turn_cache_creation_tokens=metric.cache_creation_tokens,
                turn_output_tokens=metric.output_tokens,
                request_total_tokens=round(request_total_tokens, 4),
                request_tool_activity_count=len(tool_blocks),
                request_test_activity_count=test_count,
                token_attribution_confidence=confidence,
                exact_attributed_tokens=round(exact_tokens, 4),
                tool_input_tokens=tool_input_tokens,
                tool_result_tokens=tool_result_tokens,
                input_payload=tool_input,
            )
            records.append(record)
    return records


def _build_test_suite_analysis(records: list[ToolActivityRecord]) -> dict[str, Any]:
    test_runs = [record for record in records if record.is_test_command and record.test_suite_key]
    grouped: dict[str, list[ToolActivityRecord]] = defaultdict(list)
    for record in test_runs:
        grouped[record.test_suite_key].append(record)
    suites: dict[str, dict[str, Any]] = {}
    rerun_count_total = 0
    rerun_exact_tokens_total = 0.0
    rerun_ambiguous_tokens_total = 0.0
    after_failure_exact_tokens_total = 0.0
    after_failure_ambiguous_tokens_total = 0.0
    baseline_exact_total = 0.0
    baseline_ambiguous_total = 0.0
    actual_exact_total = 0.0
    actual_ambiguous_total = 0.0
    for suite_key, runs in grouped.items():
        ordered = sorted(runs, key=lambda record: (record.entry_index, record.activity_id))
        run_count = len(ordered)
        repeat_runs = max(0, run_count - 1)
        rerun_count_total += repeat_runs
        tokens = [record.request_total_tokens for record in ordered]
        confidences = [record.token_attribution_confidence for record in ordered]
        failures = [record.has_error_signal for record in ordered]
        rerun_exact_tokens = 0.0
        rerun_ambiguous_tokens = 0.0
        for idx in range(1, len(tokens)):
            if confidences[idx] == "exact_single_tool_request":
                rerun_exact_tokens += tokens[idx]
            else:
                rerun_ambiguous_tokens += tokens[idx]
        rerun_exact_tokens_total += rerun_exact_tokens
        rerun_ambiguous_tokens_total += rerun_ambiguous_tokens
        after_failure_exact_tokens = 0.0
        after_failure_ambiguous_tokens = 0.0
        runs_after_failure = 0
        for idx in range(1, len(ordered)):
            if failures[idx - 1]:
                runs_after_failure += 1
                if confidences[idx] == "exact_single_tool_request":
                    after_failure_exact_tokens += tokens[idx]
                else:
                    after_failure_ambiguous_tokens += tokens[idx]
        after_failure_exact_tokens_total += after_failure_exact_tokens
        after_failure_ambiguous_tokens_total += after_failure_ambiguous_tokens
        first_ts = _parse_ts(ordered[0].started_at)
        last_ts = _parse_ts(ordered[-1].started_at)
        span_seconds = int((last_ts - first_ts).total_seconds()) if first_ts and last_ts else 0
        baseline_exact = tokens[0] if tokens and confidences[0] == "exact_single_tool_request" else 0.0
        baseline_ambiguous = tokens[0] if tokens and confidences[0] != "exact_single_tool_request" else 0.0
        actual_exact = sum(
            tokens[idx] for idx in range(len(tokens)) if confidences[idx] == "exact_single_tool_request"
        )
        actual_ambiguous = sum(
            tokens[idx] for idx in range(len(tokens)) if confidences[idx] != "exact_single_tool_request"
        )
        baseline_exact_total += baseline_exact
        baseline_ambiguous_total += baseline_ambiguous
        actual_exact_total += actual_exact
        actual_ambiguous_total += actual_ambiguous
        suites[suite_key] = {
            "run_count": run_count,
            "repeat_runs": repeat_runs,
            "failure_runs": sum(1 for flag in failures if flag),
            "runs_after_failure": runs_after_failure,
            "time_span_seconds": span_seconds,
            "estimated_tokens_total_exact": round(actual_exact, 4),
            "estimated_tokens_total_ambiguous": round(actual_ambiguous, 4),
            "estimated_tokens_reruns_exact": round(rerun_exact_tokens, 4),
            "estimated_tokens_reruns_ambiguous": round(rerun_ambiguous_tokens, 4),
            "estimated_tokens_after_failure_reruns_exact": round(after_failure_exact_tokens, 4),
            "estimated_tokens_after_failure_reruns_ambiguous": round(after_failure_ambiguous_tokens, 4),
            "clean_baseline_tokens_exact": round(baseline_exact, 4),
            "clean_baseline_tokens_ambiguous": round(baseline_ambiguous, 4),
            "retry_premium_tokens_exact": round(actual_exact - baseline_exact, 4),
            "retry_premium_tokens_ambiguous": round(actual_ambiguous - baseline_ambiguous, 4),
            "entries": [record.entry_index for record in ordered],
            "commands": [record.command for record in ordered],
            "confidence": {
                "exact_run_count": sum(1 for confidence in confidences if confidence == "exact_single_tool_request"),
                "ambiguous_run_count": sum(
                    1 for confidence in confidences if confidence != "exact_single_tool_request"
                ),
            },
        }
    return {
        "test_runs_total": len(test_runs),
        "unique_suites": len(suites),
        "rerun_count_total": rerun_count_total,
        "rerun_token_cost_exact": round(rerun_exact_tokens_total, 4),
        "rerun_token_cost_ambiguous": round(rerun_ambiguous_tokens_total, 4),
        "tokens_after_failure_reruns_exact": round(after_failure_exact_tokens_total, 4),
        "tokens_after_failure_reruns_ambiguous": round(after_failure_ambiguous_tokens_total, 4),
        "clean_baseline_tokens_exact": round(baseline_exact_total, 4),
        "clean_baseline_tokens_ambiguous": round(baseline_ambiguous_total, 4),
        "actual_tokens_exact": round(actual_exact_total, 4),
        "actual_tokens_ambiguous": round(actual_ambiguous_total, 4),
        "retry_premium_tokens_exact": round(actual_exact_total - baseline_exact_total, 4),
        "retry_premium_tokens_ambiguous": round(actual_ambiguous_total - baseline_ambiguous_total, 4),
        "suites": dict(sorted(suites.items(), key=lambda pair: pair[0])),
    }


def _plan_to_cut_recommendation(plan: Any) -> dict[str, Any]:
    return {
        "session_id": plan.session_id,
        "recommended_cut_index": plan.recommended_cut_index,
        "keep_range_start": plan.keep_range_start,
        "keep_range_end": plan.keep_range_end,
        "drop_range_start": plan.drop_range_start,
        "drop_range_end": plan.drop_range_end,
        "dropped_entry_count": plan.dropped_entry_count,
        "rationale": list(plan.rationale),
    }


def _build_token_estimation_health(
    metrics: list[TurnMetric],
    *,
    estimator_overhead_tokens: int,
) -> dict[str, Any]:
    if not metrics:
        return {
            "estimator_name": "tiktoken_cl100k_content_estimate",
            "is_billing_authoritative": False,
            "authoritative_cost_source": (
                "usage.input_tokens + usage.cache_read_input_tokens + usage.cache_creation_input_tokens"
            ),
            "estimator_overhead_tokens": estimator_overhead_tokens,
            "request_count": 0,
            "avg_delta_pct": 0.0,
            "max_delta_pct": 0.0,
            "requests_over_1pct": 0,
            "requests_over_10pct": 0,
            "avg_delta_adjusted_pct": 0.0,
            "max_delta_adjusted_pct": 0.0,
            "requests_over_1pct_adjusted": 0,
            "requests_over_10pct_adjusted": 0,
        }
    deltas = [metric.input_token_delta_pct for metric in metrics]
    deltas_adjusted = [metric.input_token_delta_adjusted_pct for metric in metrics]
    over_1pct = sum(1 for value in deltas if value > 1.0)
    over_10pct = sum(1 for value in deltas if value > 10.0)
    over_1pct_adjusted = sum(1 for value in deltas_adjusted if value > 1.0)
    over_10pct_adjusted = sum(1 for value in deltas_adjusted if value > 10.0)
    return {
        "estimator_name": "tiktoken_cl100k_content_estimate",
        "is_billing_authoritative": False,
        "authoritative_cost_source": (
            "usage.input_tokens + usage.cache_read_input_tokens + usage.cache_creation_input_tokens"
        ),
        "estimator_overhead_tokens": estimator_overhead_tokens,
        "request_count": len(metrics),
        "avg_delta_pct": round(sum(deltas) / len(deltas), 4),
        "max_delta_pct": round(max(deltas), 4),
        "requests_over_1pct": over_1pct,
        "requests_over_10pct": over_10pct,
        "avg_delta_adjusted_pct": round(sum(deltas_adjusted) / len(deltas_adjusted), 4),
        "max_delta_adjusted_pct": round(max(deltas_adjusted), 4),
        "requests_over_1pct_adjusted": over_1pct_adjusted,
        "requests_over_10pct_adjusted": over_10pct_adjusted,
    }


def _build_seed_context(
    *,
    snapshot: Any,
    metrics: list[TurnMetric],
    keep_range: tuple[int, int],
    max_seed_messages: int,
) -> dict[str, Any]:
    raw_messages = extract_seed_messages(snapshot, max_messages=max_seed_messages)
    user_texts = [row["text"] for row in raw_messages if row["role"] == "user"]
    assistant_texts = [row["text"] for row in raw_messages if row["role"] == "assistant"]
    goal = user_texts[0] if user_texts else ""
    constraints = _pick_lines(user_texts, _CONSTRAINT_RE, limit=12)
    decisions = _pick_lines(user_texts + assistant_texts, _DECISION_RE, limit=16)
    current_state = _pick_lines(reversed(assistant_texts), _PROGRESS_RE, limit=8)
    open_work = _pick_lines(reversed(user_texts), _QUESTION_RE, limit=8)
    error_evidence = _pick_lines(user_texts + assistant_texts, _ERROR_RE, limit=12)
    range_metrics = [m for m in metrics if keep_range[0] <= m.entry_index <= keep_range[1]]
    command_family_rollup: Counter[str] = Counter()
    for metric in range_metrics:
        command_family_rollup.update(metric.command_families)
    key_command_families = [
        {"family": name, "count": count}
        for name, count in command_family_rollup.most_common(10)
    ]
    token_snapshot = {}
    if range_metrics:
        last_metric = range_metrics[-1]
        token_snapshot = {
            "entry_index": last_metric.entry_index,
            "input_tokens": last_metric.input_tokens,
            "cache_read_tokens": last_metric.cache_read_tokens,
            "cache_creation_tokens": last_metric.cache_creation_tokens,
            "output_tokens": last_metric.output_tokens,
            "cache_hit_ratio": last_metric.cache_hit_ratio,
        }
    return {
        "task_goal": goal,
        "hard_constraints": constraints,
        "decisions_made": decisions,
        "current_state": current_state,
        "open_work_next": open_work,
        "distilled_evidence": {
            "errors": error_evidence,
            "command_families": key_command_families,
            "token_snapshot": token_snapshot,
        },
        "seed_messages": raw_messages,
    }


def _build_budget_by_purpose(metrics: list[TurnMetric]) -> dict[str, dict[str, int | float]]:
    rollups: dict[str, dict[str, int | float]] = defaultdict(
        lambda: {
            "runs": 0,
            "input_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "output_tokens": 0,
        }
    )
    for metric in metrics:
        row = rollups[metric.purpose]
        row["runs"] += 1
        row["input_tokens"] += metric.input_tokens
        row["cache_read_tokens"] += metric.cache_read_tokens
        row["cache_creation_tokens"] += metric.cache_creation_tokens
        row["output_tokens"] += metric.output_tokens
    for purpose, row in rollups.items():
        total_input = int(row["input_tokens"]) + int(row["cache_read_tokens"])
        row["cache_hit_ratio"] = round((int(row["cache_read_tokens"]) / total_input), 4) if total_input > 0 else 0.0
    return dict(sorted(rollups.items(), key=lambda pair: pair[0]))


def _pick_lines(texts: Any, pattern: re.Pattern[str], *, limit: int) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for text in texts:
        cleaned = _normalize_line(text)
        if not cleaned:
            continue
        if not pattern.search(cleaned):
            continue
        if cleaned in seen:
            continue
        lines.append(cleaned)
        seen.add(cleaned)
        if len(lines) >= limit:
            break
    return lines


def _normalize_line(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:240]


def _estimate_request_input_tokens_tiktoken(request_payload: dict[str, Any]) -> int:
    total = 0
    system = request_payload.get("system", "")
    total += _count_content_tokens(system)
    tools = request_payload.get("tools", [])
    if tools:
        total += count_tokens(json.dumps(tools, sort_keys=True))
    messages = request_payload.get("messages", [])
    if not isinstance(messages, list):
        return total
    for message in messages:
        if not isinstance(message, dict):
            total += count_tokens(str(message))
            continue
        role = str(message.get("role", ""))
        if role:
            total += count_tokens(role)
        total += _count_content_tokens(message.get("content", ""))
    return total


def _count_content_tokens(content: Any) -> int:
    if isinstance(content, str):
        return count_tokens(content)
    if isinstance(content, list):
        total = 0
        for item in content:
            total += _count_content_tokens(item)
        return total
    if isinstance(content, dict):
        block_type = str(content.get("type", ""))
        if block_type == "text":
            return count_tokens(str(content.get("text", "")))
        if block_type == "tool_use":
            tool_name = str(content.get("name", ""))
            tool_input = content.get("input", {})
            payload = tool_name + " " + json.dumps(tool_input, sort_keys=True)
            return count_tokens(payload)
        if block_type == "tool_result":
            return count_tokens(_stringify_tool_result(content.get("content", "")))
        return count_tokens(json.dumps(content, sort_keys=True))
    return count_tokens(str(content))


def _count_progress_signals(diff: Any) -> int:
    haystack = "\n".join(
        list(diff.appended_user_messages)
        + list(diff.appended_assistant_messages)
        + list(diff.appended_commands)
    ).lower()
    markers = ("git commit", "git push", "bd close", "tests passed", "all tests passed", "merged")
    return sum(haystack.count(marker) for marker in markers)


def _extract_tool_use_blocks(appended_messages: list[Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for msg_index, message in enumerate(appended_messages):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "assistant":
            continue
        content = message.get("content", [])
        if not isinstance(content, list):
            continue
        for block_index, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            tool_name = str(block.get("name", ""))
            blocks.append(
                {
                    "message_index": msg_index,
                    "block_index": block_index,
                    "tool_use_id": str(block.get("id", "")),
                    "tool_name": tool_name,
                    "tool_input": block.get("input", {}) if isinstance(block.get("input", {}), dict) else {},
                }
            )
    return blocks


def _extract_tool_result_map(appended_messages: list[Any]) -> dict[str, dict[str, Any]]:
    result_map: dict[str, dict[str, Any]] = {}
    for message in appended_messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") != "user":
            continue
        content = message.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_result":
                continue
            tool_use_id = str(block.get("tool_use_id", ""))
            if not tool_use_id:
                continue
            text = _stringify_tool_result(block.get("content", ""))
            is_error = bool(block.get("is_error", False))
            result_map[tool_use_id] = {
                "has_error_signal": is_error or bool(_FAIL_RESULT_RE.search(text.lower())),
                "result_excerpt": _normalize_line(text)[:240],
                "result_text": text,
            }
    return result_map


def _stringify_tool_result(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
                else:
                    parts.append(json.dumps(part, sort_keys=True))
            else:
                parts.append(str(part))
        return "\n".join(parts)
    return json.dumps(content, sort_keys=True)


def _extract_target(tool_name: str, tool_input: dict[str, Any]) -> tuple[str, str]:
    if tool_name in {"Read", "Edit", "Write", "MultiEdit"}:
        return ("file_path", str(tool_input.get("file_path", "")).strip())
    if tool_name == "Grep":
        path = str(tool_input.get("path", "")).strip()
        if path:
            return ("path", path)
        pattern = str(tool_input.get("pattern", "")).strip()
        return ("pattern", pattern)
    if tool_name == "Glob":
        pattern = str(tool_input.get("pattern", "")).strip()
        return ("pattern", pattern)
    if tool_name == "Bash":
        command = str(tool_input.get("command", "")).strip()
        return ("command", command)
    file_path = str(tool_input.get("file_path", "")).strip()
    if file_path:
        return ("file_path", file_path)
    return ("unknown", "")


def _normalize_command(tool_name: str, command: str) -> tuple[str, str, bool, str]:
    if tool_name != "Bash" or not command:
        return ("", "", False, "")
    command_family = _command_family(command)
    base = command
    for separator in ("|", "&&", ";"):
        if separator in base:
            base = base.split(separator, 1)[0].strip()
    try:
        tokens = shlex.split(base)
    except ValueError:
        tokens = base.split()
    if len(tokens) >= 2 and tokens[0] == "uv" and tokens[1] == "run":
        tokens = tokens[2:]
    if not tokens:
        return ("", command_family, False, "")
    runner = tokens[0]
    if runner not in {"pytest", "py.test"}:
        normalized = " ".join(tokens[: min(6, len(tokens))])
        return (normalized, command_family, False, "")
    signature_parts: list[str] = []
    idx = 1
    while idx < len(tokens):
        token = tokens[idx]
        if token in {"-k", "-m"} and idx + 1 < len(tokens):
            signature_parts.append(token)
            signature_parts.append(tokens[idx + 1])
            idx += 2
            continue
        if token.startswith("-"):
            idx += 1
            continue
        signature_parts.append(token)
        idx += 1
    suite_key = "pytest " + " ".join(signature_parts) if signature_parts else "pytest <default>"
    return (suite_key, command_family, True, suite_key)


def _command_family(command: str) -> str:
    trimmed = command.strip()
    if not trimmed:
        return "(empty)"
    try:
        tokens = shlex.split(trimmed)
    except ValueError:
        tokens = trimmed.split()
    if not tokens:
        return "(empty)"
    if len(tokens) >= 3 and tokens[0] == "uv" and tokens[1] == "run":
        return f"{tokens[0]} {tokens[1]} {tokens[2]}"
    if len(tokens) >= 2:
        return f"{tokens[0]} {tokens[1]}"
    return tokens[0]


def _parse_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    text = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _compute_degradation_delta(
    *,
    interrupt_count: int,
    repeated_command_count: int,
    command_count: int,
    dominant_count: int,
    progress_signal_count: int,
    assistant_message_count: int,
) -> int:
    dominance_penalty = 1 if command_count >= 5 and dominant_count >= max(4, int(command_count * 0.8)) else 0
    stagnation_penalty = 2 if command_count >= 5 and progress_signal_count == 0 else 0
    narrative_churn_penalty = 1 if assistant_message_count >= 4 and progress_signal_count == 0 else 0
    raw = (
        (2 * interrupt_count)
        + (2 * repeated_command_count)
        + dominance_penalty
        + stagnation_penalty
        + narrative_churn_penalty
        - progress_signal_count
    )
    return max(0, raw)
