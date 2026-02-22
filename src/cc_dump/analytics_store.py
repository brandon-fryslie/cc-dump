"""In-memory analytics store for API conversation data.

Replaces SQLite persistence. Accumulates request/response pairs into complete
"turns" with token counts and tool invocations. Supports state serialization
for hot-reload preservation.

// [LAW:one-source-of-truth] HAR files are the persistent source of truth.
// This store is runtime-only — derived data for analytics panels.
"""

import json
import sys
import traceback
from dataclasses import dataclass, field
from typing import TypedDict

from cc_dump.event_types import (
    PipelineEvent,
    PipelineEventKind,
    RequestBodyEvent,
    ResponseCompleteEvent,
)
from cc_dump.analysis import (
    correlate_tools,
    classify_model,
    compute_session_cost,
    format_model_short,
    HAIKU_BASE_UNIT,
    ToolEconomicsRow,
)
from cc_dump.side_channel_marker import extract_marker
from cc_dump.token_counter import count_tokens


@dataclass
class ToolInvocationRecord:
    """Record of a single tool invocation within a turn."""

    tool_name: str
    tool_use_id: str
    input_tokens: int
    result_tokens: int
    is_error: bool


@dataclass
class TurnRecord:
    """Record of a completed API turn (request + response)."""

    sequence_num: int
    model: str
    stop_reason: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    request_json: str  # For timeline budget calculation
    purpose: str = "primary"
    prompt_version: str = ""
    policy_version: str = ""
    is_side_channel: bool = False
    tool_invocations: list[ToolInvocationRecord] = field(default_factory=list)


@dataclass
class _PendingTurn:
    """Request-scoped pending turn state keyed by request_id."""

    request_id: str
    request_body: dict
    model: str
    purpose: str
    prompt_version: str
    policy_version: str
    is_side_channel: bool


class DashboardTurnRow(TypedDict):
    sequence_num: int
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int


class DashboardTimelineRow(DashboardTurnRow):
    input_total: int
    cache_pct: float
    delta_input: int


class DashboardModelRow(TypedDict):
    model: str
    model_label: str
    turns: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_usd: float
    input_total: int
    total_tokens: int
    cache_pct: float
    token_share_pct: float


class DashboardSummary(TypedDict):
    turn_count: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_usd: float
    input_total: int
    total_tokens: int
    cache_pct: float
    cache_savings_usd: float
    active_model_count: int
    latest_model_label: str


class AnalyticsStore:
    """In-memory event subscriber that accumulates analytics data.

    Replaces SQLiteWriter. Same event handling logic, but stores data
    in memory instead of SQLite. Query methods translate SQL to Python.
    """

    def __init__(self):
        self._turns: list[TurnRecord] = []
        self._seq = 0
        self._pending: dict[str, _PendingTurn] = {}

    @property
    def turn_count(self) -> int:
        """Number of completed turns tracked in analytics store."""
        return len(self._turns)

    def on_event(self, event: PipelineEvent) -> None:
        """Handle an event from the router. Errors logged, never crash the proxy."""
        try:
            self._handle(event)
        except Exception as e:
            sys.stderr.write("[analytics] error: {}\n".format(e))
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()

    def _handle(self, event: PipelineEvent) -> None:
        """Internal event handler - may raise exceptions."""
        kind = event.kind

        if kind == PipelineEventKind.REQUEST:
            assert isinstance(event, RequestBodyEvent)
            body = event.body if isinstance(event.body, dict) else {}
            marker = extract_marker(body)
            self._pending[event.request_id] = _PendingTurn(
                request_id=event.request_id,
                request_body=body,
                model=str(body.get("model", "") or ""),
                purpose=marker.purpose if marker is not None else "primary",
                prompt_version=marker.prompt_version if marker is not None else "",
                policy_version=marker.policy_version if marker is not None else "",
                is_side_channel=marker is not None,
            )

        elif kind == PipelineEventKind.RESPONSE_COMPLETE:
            # [LAW:one-source-of-truth] Extract all response data from complete body
            assert isinstance(event, ResponseCompleteEvent)
            pending = self._pending.get(event.request_id)
            if pending is None:
                return
            body = event.body
            usage = body.get("usage", {})
            usage_map = {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
                "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            }
            model = body.get("model", "") or pending.model
            stop_reason = body.get("stop_reason", "") or ""
            self._commit_turn(
                pending=pending,
                usage=usage_map,
                model=str(model),
                stop_reason=str(stop_reason),
            )

    def _commit_turn(
        self,
        *,
        pending: _PendingTurn,
        usage: dict[str, int],
        model: str,
        stop_reason: str,
    ) -> None:
        """Store accumulated turn in memory."""
        if not pending.request_body:
            return

        self._seq += 1

        # Build tool invocations with token counts
        messages = pending.request_body.get("messages", [])
        invocations = correlate_tools(messages)
        tool_records = []
        for inv in invocations:
            # Count actual tokens using tiktoken
            input_tokens = count_tokens(inv.input_str)
            result_tokens = count_tokens(inv.result_str)

            tool_records.append(
                ToolInvocationRecord(
                    tool_name=inv.name,
                    tool_use_id=inv.tool_use_id,
                    input_tokens=input_tokens,
                    result_tokens=result_tokens,
                    is_error=inv.is_error,
                )
            )

        # Create turn record
        turn = TurnRecord(
            sequence_num=self._seq,
            model=model,
            stop_reason=stop_reason,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            cache_creation_tokens=usage.get(
                "cache_creation_input_tokens", 0
            ),
            request_json=json.dumps(pending.request_body),
            purpose=pending.purpose,
            prompt_version=pending.prompt_version,
            policy_version=pending.policy_version,
            is_side_channel=pending.is_side_channel,
            tool_invocations=tool_records,
        )

        self._turns.append(turn)
        self._pending.pop(pending.request_id, None)

    # ─── Query methods (translated from db_queries.py SQL) ─────────────────

    def get_session_stats(self, current_turn: dict | None = None) -> dict:
        """Query cumulative token counts for the session.

        Args:
            current_turn: Optional dict with in-progress turn data to merge
                         Expected keys: input_tokens, output_tokens,
                         cache_read_tokens, cache_creation_tokens

        Returns:
            Dict with keys: input_tokens, output_tokens, cache_read_tokens,
            cache_creation_tokens
        """
        # [LAW:dataflow-not-control-flow] Sum across all turns
        stats = {
            "input_tokens": sum(t.input_tokens for t in self._turns),
            "output_tokens": sum(t.output_tokens for t in self._turns),
            "cache_read_tokens": sum(t.cache_read_tokens for t in self._turns),
            "cache_creation_tokens": sum(t.cache_creation_tokens for t in self._turns),
        }

        # Merge current incomplete turn if provided
        if current_turn:
            stats["input_tokens"] += current_turn.get("input_tokens", 0)
            stats["output_tokens"] += current_turn.get("output_tokens", 0)
            stats["cache_read_tokens"] += current_turn.get("cache_read_tokens", 0)
            stats["cache_creation_tokens"] += current_turn.get(
                "cache_creation_tokens", 0
            )

        return stats

    def get_latest_turn_stats(self) -> dict | None:
        """Query the most recent turn's token counts and model.

        Returns:
            Dict with keys: sequence_num, input_tokens, output_tokens,
            cache_read_tokens, cache_creation_tokens, model
            Returns None if no turns exist.
        """
        if not self._turns:
            return None

        t = self._turns[-1]
        return {
            "sequence_num": t.sequence_num,
            "input_tokens": t.input_tokens,
            "output_tokens": t.output_tokens,
            "cache_read_tokens": t.cache_read_tokens,
            "cache_creation_tokens": t.cache_creation_tokens,
            "model": t.model,
        }

    def get_turn_timeline(self) -> list[dict]:
        """Query turn timeline data for the session.

        Returns:
            List of dicts with keys: sequence_num, input_tokens, output_tokens,
            cache_read_tokens, cache_creation_tokens, request_json, model
        """
        return [
            {
                "sequence_num": t.sequence_num,
                "model": t.model,
                "input_tokens": t.input_tokens,
                "output_tokens": t.output_tokens,
                "cache_read_tokens": t.cache_read_tokens,
                "cache_creation_tokens": t.cache_creation_tokens,
                "request_json": t.request_json,
            }
            for t in self._turns
        ]

    def get_dashboard_snapshot(self, current_turn: dict | None = None) -> dict[str, object]:
        """Build canonical analytics dashboard data from real API usage fields only.

        // [LAW:one-source-of-truth] Dashboard derives from TurnRecord token fields only.
        """
        base_rows: list[DashboardTurnRow] = [
            {
                "sequence_num": t.sequence_num,
                "model": t.model or "",
                "input_tokens": t.input_tokens,
                "output_tokens": t.output_tokens,
                "cache_read_tokens": t.cache_read_tokens,
                "cache_creation_tokens": t.cache_creation_tokens,
            }
            for t in self._turns
        ]

        pending = current_turn if isinstance(current_turn, dict) else {}
        pending_row: DashboardTurnRow = {
            "sequence_num": len(base_rows) + 1,
            "model": str(pending.get("model", "") or ""),
            "input_tokens": int(pending.get("input_tokens", 0) or 0),
            "output_tokens": int(pending.get("output_tokens", 0) or 0),
            "cache_read_tokens": int(pending.get("cache_read_tokens", 0) or 0),
            "cache_creation_tokens": int(pending.get("cache_creation_tokens", 0) or 0),
        }
        include_pending = (
            pending_row["input_tokens"] > 0
            or pending_row["output_tokens"] > 0
            or pending_row["cache_read_tokens"] > 0
            or pending_row["cache_creation_tokens"] > 0
        )
        rows: list[DashboardTurnRow] = base_rows + ([pending_row] if include_pending else [])

        timeline_rows: list[DashboardTimelineRow] = []
        prev_input_total = 0
        for row in rows:
            input_total = row["input_tokens"] + row["cache_read_tokens"]
            cache_pct = (
                (100.0 * row["cache_read_tokens"] / input_total)
                if input_total > 0
                else 0.0
            )
            delta_input = input_total - prev_input_total if prev_input_total > 0 else 0
            prev_input_total = input_total
            timeline_rows.append(
                {
                    "sequence_num": row["sequence_num"],
                    "model": row["model"],
                    "input_tokens": row["input_tokens"],
                    "output_tokens": row["output_tokens"],
                    "cache_read_tokens": row["cache_read_tokens"],
                    "cache_creation_tokens": row["cache_creation_tokens"],
                    "input_total": input_total,
                    "cache_pct": cache_pct,
                    "delta_input": delta_input,
                }
            )

        model_agg: dict[str, DashboardModelRow] = {}
        for row in rows:
            model = row["model"]
            if model not in model_agg:
                model_agg[model] = {
                    "model": model,
                    "model_label": format_model_short(model),
                    "turns": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_creation_tokens": 0,
                    "cost_usd": 0.0,
                    "input_total": 0,
                    "total_tokens": 0,
                    "cache_pct": 0.0,
                    "token_share_pct": 0.0,
                }
            agg = model_agg[model]
            agg["turns"] += 1
            agg["input_tokens"] += row["input_tokens"]
            agg["output_tokens"] += row["output_tokens"]
            agg["cache_read_tokens"] += row["cache_read_tokens"]
            agg["cache_creation_tokens"] += row["cache_creation_tokens"]
            agg["cost_usd"] += compute_session_cost(
                row["input_tokens"],
                row["output_tokens"],
                row["cache_read_tokens"],
                row["cache_creation_tokens"],
                model,
            )

        model_rows: list[DashboardModelRow] = []
        for model, agg in model_agg.items():
            input_total = agg["input_tokens"] + agg["cache_read_tokens"]
            total_tokens = input_total + agg["output_tokens"]
            cache_pct = (
                (100.0 * agg["cache_read_tokens"] / input_total)
                if input_total > 0
                else 0.0
            )
            model_rows.append(
                {
                    "model": model,
                    "model_label": format_model_short(model),
                    "turns": agg["turns"],
                    "input_tokens": agg["input_tokens"],
                    "output_tokens": agg["output_tokens"],
                    "cache_read_tokens": agg["cache_read_tokens"],
                    "cache_creation_tokens": agg["cache_creation_tokens"],
                    "cost_usd": agg["cost_usd"],
                    "input_total": input_total,
                    "total_tokens": total_tokens,
                    "cache_pct": cache_pct,
                    "token_share_pct": 0.0,
                }
            )
        model_rows.sort(key=lambda mrow: (-mrow["total_tokens"], mrow["model_label"]))

        summary_total_tokens = sum(mrow["total_tokens"] for mrow in model_rows)
        for mrow in model_rows:
            mrow["token_share_pct"] = (
                (100.0 * mrow["total_tokens"] / summary_total_tokens)
                if summary_total_tokens > 0
                else 0.0
            )

        summary: DashboardSummary = {
            "turn_count": len(rows),
            "input_tokens": sum(row["input_tokens"] for row in rows),
            "output_tokens": sum(row["output_tokens"] for row in rows),
            "cache_read_tokens": sum(row["cache_read_tokens"] for row in rows),
            "cache_creation_tokens": sum(row["cache_creation_tokens"] for row in rows),
            "cost_usd": sum(mrow["cost_usd"] for mrow in model_rows),
            "input_total": 0,
            "total_tokens": 0,
            "cache_pct": 0.0,
            "cache_savings_usd": 0.0,
            "active_model_count": len(model_rows),
            "latest_model_label": format_model_short(rows[-1]["model"]) if rows else "Unknown",
        }
        summary["input_total"] = summary["input_tokens"] + summary["cache_read_tokens"]
        summary["total_tokens"] = summary["input_total"] + summary["output_tokens"]
        summary["cache_pct"] = (
            (100.0 * summary["cache_read_tokens"] / summary["input_total"])
            if summary["input_total"] > 0
            else 0.0
        )
        cache_savings = 0.0
        for row in rows:
            _, pricing = classify_model(row["model"])
            cache_savings += (
                row["cache_read_tokens"] * (pricing.base_input - pricing.cache_hit) / 1_000_000
            )
        summary["cache_savings_usd"] = cache_savings

        return {
            "summary": summary,
            "timeline": timeline_rows,
            "models": model_rows,
        }

    def get_side_channel_purpose_summary(self) -> dict[str, dict[str, object]]:
        """Aggregate side-channel token usage by purpose."""
        summary: dict[str, dict[str, object]] = {}
        for turn in self._turns:
            if not turn.is_side_channel:
                continue
            row = summary.get(turn.purpose)
            if row is None:
                row = {
                    "turns": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_creation_tokens": 0,
                    "prompt_versions": {},
                    "policy_versions": {},
                }
                summary[turn.purpose] = row
            row["turns"] += 1
            row["input_tokens"] += turn.input_tokens
            row["output_tokens"] += turn.output_tokens
            row["cache_read_tokens"] += turn.cache_read_tokens
            row["cache_creation_tokens"] += turn.cache_creation_tokens
            if turn.prompt_version:
                versions = row["prompt_versions"]
                if isinstance(versions, dict):
                    versions[turn.prompt_version] = int(versions.get(turn.prompt_version, 0)) + 1
            if turn.policy_version:
                policy_versions = row["policy_versions"]
                if isinstance(policy_versions, dict):
                    policy_versions[turn.policy_version] = int(
                        policy_versions.get(turn.policy_version, 0)
                    ) + 1
        return summary

    def get_tool_economics(self, group_by_model: bool = False) -> list[ToolEconomicsRow]:
        """Query per-tool economics with real token counts and cache attribution.

        Args:
            group_by_model: If False (default), aggregate by tool name only.
                           If True, group by (tool_name, model) for breakdown view.

        Returns:
            List of ToolEconomicsRow with:
            - Real token counts from tool_invocations (input_tokens, result_tokens)
            - Proportional cache attribution from parent turn
            - Normalized cost using model pricing
            - model field: None for aggregate mode, model string for breakdown mode
        """
        if not self._turns:
            return []

        # Aggregate by (tool_name, model) or just tool_name
        if group_by_model:
            by_key: dict[tuple[str, str], dict] = {}
        else:
            by_name: dict[str, dict] = {}

        for turn in self._turns:
            if not turn.tool_invocations:
                continue

            # Compute proportional cache attribution
            turn_tool_total = sum(inv.input_tokens for inv in turn.tool_invocations)

            for inv in turn.tool_invocations:
                # Proportional cache contribution
                if turn_tool_total > 0 and turn.cache_read_tokens > 0:
                    proportion = inv.input_tokens / turn_tool_total
                    cache_contrib = int(proportion * turn.cache_read_tokens)
                else:
                    cache_contrib = 0

                # Normalized cost
                _, pricing = classify_model(turn.model)
                inv_norm_cost = inv.input_tokens * (
                    pricing.base_input / HAIKU_BASE_UNIT
                ) + inv.result_tokens * (pricing.output / HAIKU_BASE_UNIT)

                if group_by_model:
                    key = (inv.tool_name, turn.model or "")
                    if key not in by_key:
                        by_key[key] = {
                            "calls": 0,
                            "input_tokens": 0,
                            "result_tokens": 0,
                            "cache_read": 0,
                            "norm_cost": 0.0,
                        }
                    agg = by_key[key]
                else:
                    name = inv.tool_name
                    if name not in by_name:
                        by_name[name] = {
                            "calls": 0,
                            "input_tokens": 0,
                            "result_tokens": 0,
                            "cache_read": 0,
                            "norm_cost": 0.0,
                        }
                    agg = by_name[name]

                agg["calls"] += 1
                agg["input_tokens"] += inv.input_tokens
                agg["result_tokens"] += inv.result_tokens
                agg["cache_read"] += cache_contrib
                agg["norm_cost"] += inv_norm_cost

        # Build result list sorted by norm_cost descending
        result = []

        if group_by_model:
            for (name, model), agg in sorted(
                by_key.items(), key=lambda x: (-x[1]["norm_cost"], x[0][0], x[0][1])
            ):
                result.append(
                    ToolEconomicsRow(
                        name=name,
                        calls=agg["calls"],
                        input_tokens=agg["input_tokens"],
                        result_tokens=agg["result_tokens"],
                        cache_read_tokens=agg["cache_read"],
                        norm_cost=agg["norm_cost"],
                        model=model if model else None,
                    )
                )
        else:
            for name, agg in sorted(
                by_name.items(), key=lambda x: x[1]["norm_cost"], reverse=True
            ):
                result.append(
                    ToolEconomicsRow(
                        name=name,
                        calls=agg["calls"],
                        input_tokens=agg["input_tokens"],
                        result_tokens=agg["result_tokens"],
                        cache_read_tokens=agg["cache_read"],
                        norm_cost=agg["norm_cost"],
                        model=None,
                    )
                )

        return result

    # ─── State management for hot-reload ───────────────────────────────────

    def get_state(self) -> dict:
        """Extract state for hot-reload preservation."""
        return {
            "turns": [
                {
                    "sequence_num": t.sequence_num,
                    "model": t.model,
                    "stop_reason": t.stop_reason,
                    "input_tokens": t.input_tokens,
                    "output_tokens": t.output_tokens,
                    "cache_read_tokens": t.cache_read_tokens,
                    "cache_creation_tokens": t.cache_creation_tokens,
                    "request_json": t.request_json,
                    "purpose": t.purpose,
                    "prompt_version": t.prompt_version,
                    "policy_version": t.policy_version,
                    "is_side_channel": t.is_side_channel,
                    "tool_invocations": [
                        {
                            "tool_name": inv.tool_name,
                            "tool_use_id": inv.tool_use_id,
                            "input_tokens": inv.input_tokens,
                            "result_tokens": inv.result_tokens,
                            "is_error": inv.is_error,
                        }
                        for inv in t.tool_invocations
                    ],
                }
                for t in self._turns
            ],
            "seq": self._seq,
            "pending": [
                {
                    "request_id": p.request_id,
                    "request_body": p.request_body,
                    "model": p.model,
                    "purpose": p.purpose,
                    "prompt_version": p.prompt_version,
                    "policy_version": p.policy_version,
                    "is_side_channel": p.is_side_channel,
                }
                for p in self._pending.values()
            ],
        }

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self._turns = []
        for t_data in state.get("turns", []):
            tool_invocations = [
                ToolInvocationRecord(
                    tool_name=inv["tool_name"],
                    tool_use_id=inv["tool_use_id"],
                    input_tokens=inv["input_tokens"],
                    result_tokens=inv["result_tokens"],
                    is_error=inv["is_error"],
                )
                for inv in t_data.get("tool_invocations", [])
            ]
            self._turns.append(
                TurnRecord(
                    sequence_num=t_data["sequence_num"],
                    model=t_data["model"],
                    stop_reason=t_data["stop_reason"],
                    input_tokens=t_data["input_tokens"],
                    output_tokens=t_data["output_tokens"],
                    cache_read_tokens=t_data["cache_read_tokens"],
                    cache_creation_tokens=t_data["cache_creation_tokens"],
                    request_json=t_data["request_json"],
                    purpose=str(t_data.get("purpose", "primary") or "primary"),
                    prompt_version=str(t_data.get("prompt_version", "") or ""),
                    policy_version=str(t_data.get("policy_version", "") or ""),
                    is_side_channel=bool(t_data.get("is_side_channel", False)),
                    tool_invocations=tool_invocations,
                )
            )

        self._seq = state.get("seq", 0)
        self._pending = {}
        for p_data in state.get("pending", []):
            if not isinstance(p_data, dict):
                continue
            request_id = str(p_data.get("request_id", "") or "")
            if not request_id:
                continue
            request_body = p_data.get("request_body", {})
            if not isinstance(request_body, dict):
                request_body = {}
            self._pending[request_id] = _PendingTurn(
                request_id=request_id,
                request_body=request_body,
                model=str(p_data.get("model", "") or ""),
                purpose=str(p_data.get("purpose", "primary") or "primary"),
                prompt_version=str(p_data.get("prompt_version", "") or ""),
                policy_version=str(p_data.get("policy_version", "") or ""),
                is_side_channel=bool(p_data.get("is_side_channel", False)),
            )
