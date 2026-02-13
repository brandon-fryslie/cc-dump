"""In-memory analytics store for API conversation data.

Replaces SQLite persistence. Accumulates request/response pairs into complete
"turns" with token counts and tool invocations. Supports state serialization
for hot-reload preservation.

// [LAW:one-source-of-truth] HAR files are the persistent source of truth.
// This store is runtime-only — derived data for analytics panels.
"""

import json
import sys
from dataclasses import dataclass, field

from cc_dump.event_types import (
    PipelineEvent,
    PipelineEventKind,
    RequestBodyEvent,
    ResponseSSEEvent,
    MessageStartEvent,
    MessageDeltaEvent,
    TextDeltaEvent,
)
from cc_dump.analysis import (
    correlate_tools,
    classify_model,
    HAIKU_BASE_UNIT,
    ToolEconomicsRow,
)
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
    tool_invocations: list[ToolInvocationRecord] = field(default_factory=list)


class AnalyticsStore:
    """In-memory event subscriber that accumulates analytics data.

    Replaces SQLiteWriter. Same event handling logic, but stores data
    in memory instead of SQLite. Query methods translate SQL to Python.
    """

    def __init__(self):
        self._turns: list[TurnRecord] = []
        self._seq = 0

        # Accumulator state for current turn (mirrors SQLiteWriter)
        self._current_request = None
        self._current_response_events = []
        self._current_text = []
        self._current_usage = {}
        self._current_stop = ""
        self._current_model = ""

    def on_event(self, event: PipelineEvent) -> None:
        """Handle an event from the router. Errors logged, never crash the proxy."""
        try:
            self._handle(event)
        except Exception as e:
            import traceback

            sys.stderr.write("[analytics] error: {}\n".format(e))
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()

    def _handle(self, event: PipelineEvent) -> None:
        """Internal event handler - may raise exceptions."""
        kind = event.kind

        if kind == PipelineEventKind.REQUEST:
            assert isinstance(event, RequestBodyEvent)
            # Start accumulating a new turn
            self._current_request = event.body
            self._current_response_events = []
            self._current_text = []
            self._current_usage = {}
            self._current_stop = ""
            self._current_model = self._current_request.get("model", "")

        elif kind == PipelineEventKind.RESPONSE_EVENT:
            assert isinstance(event, ResponseSSEEvent)
            sse = event.sse_event

            if isinstance(sse, MessageStartEvent):
                usage = sse.message.usage
                self._current_usage = {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_read_input_tokens": usage.cache_read_input_tokens,
                    "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                }
                self._current_model = sse.message.model or self._current_model

            elif isinstance(sse, TextDeltaEvent):
                self._current_text.append(sse.text)

            elif isinstance(sse, MessageDeltaEvent):
                self._current_stop = sse.stop_reason.value
                # Accumulate final usage (output tokens)
                if sse.output_tokens:
                    self._current_usage["output_tokens"] = sse.output_tokens

        elif kind == PipelineEventKind.RESPONSE_DONE:
            self._commit_turn()

    def _commit_turn(self):
        """Store accumulated turn in memory."""
        if not self._current_request:
            return

        self._seq += 1

        # Build tool invocations with token counts
        messages = self._current_request.get("messages", [])
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
            model=self._current_model,
            stop_reason=self._current_stop,
            input_tokens=self._current_usage.get("input_tokens", 0),
            output_tokens=self._current_usage.get("output_tokens", 0),
            cache_read_tokens=self._current_usage.get("cache_read_input_tokens", 0),
            cache_creation_tokens=self._current_usage.get(
                "cache_creation_input_tokens", 0
            ),
            request_json=json.dumps(self._current_request),
            tool_invocations=tool_records,
        )

        self._turns.append(turn)

        # Clear accumulator
        self._current_request = None

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
            cache_read_tokens, cache_creation_tokens, request_json
        """
        return [
            {
                "sequence_num": t.sequence_num,
                "input_tokens": t.input_tokens,
                "output_tokens": t.output_tokens,
                "cache_read_tokens": t.cache_read_tokens,
                "cache_creation_tokens": t.cache_creation_tokens,
                "request_json": t.request_json,
            }
            for t in self._turns
        ]

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
            # Accumulator state (for in-progress turns)
            "current_request": self._current_request,
            "current_response_events": self._current_response_events,
            "current_text": self._current_text,
            "current_usage": self._current_usage,
            "current_stop": self._current_stop,
            "current_model": self._current_model,
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
                    tool_invocations=tool_invocations,
                )
            )

        self._seq = state.get("seq", 0)
        self._current_request = state.get("current_request")
        self._current_response_events = state.get("current_response_events", [])
        self._current_text = state.get("current_text", [])
        self._current_usage = state.get("current_usage", {})
        self._current_stop = state.get("current_stop", "")
        self._current_model = state.get("current_model", "")
