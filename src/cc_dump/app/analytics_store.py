"""In-memory analytics store for API conversation data.

Replaces SQLite persistence. Accumulates request/response pairs into complete
"turns" with token counts and tool invocations. Supports state serialization
for hot-reload preservation.

// [LAW:one-source-of-truth] HAR files are the persistent source of truth.
// This store is runtime-only — derived data for analytics panels.
"""

import json
import logging
import hashlib
from dataclasses import dataclass, field
from typing import TypedDict

from cc_dump.pipeline.event_types import (
    PipelineEvent,
    PipelineEventKind,
    RequestHeadersEvent,
    RequestBodyEvent,
    ResponseCompleteEvent,
)
from cc_dump.core.analysis import (
    correlate_tools,
    classify_model,
    compute_session_cost,
    format_model_short,
    HAIKU_BASE_UNIT,
    ToolEconomicsRow,
)
from cc_dump.core.formatting import parse_user_id
from cc_dump.ai.side_channel_marker import extract_marker
from cc_dump.core.token_counter import count_tokens

logger = logging.getLogger(__name__)


TURN_METRICS_SCHEMA = "cc_dump.per_turn_metrics"
TURN_METRICS_VERSION = 1


_RETRY_HEADER_KEYS = (
    "x-stainless-retry-count",
    "anthropic-retry-attempt",
    "x-retry-count",
    "retry-count",
)
_INTERRUPTED_STOP_REASONS = frozenset({"max_tokens", "length", "content_filter"})
_REQUEST_META_LIMIT = 2048
_RETRY_ORDINAL_LIMIT = 8192


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

    sequence_num: int = 0
    request_id: str = ""
    session_id: str = ""
    model: str = ""
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    request_json: str = ""  # For timeline budget calculation
    request_recv_ns: int = 0
    response_recv_ns: int = 0
    latency_ms: float = 0.0
    retry_key: str = ""
    retry_ordinal: int = 0
    transport_retry_count: int = 0
    was_interrupted: bool = False
    command_count: int = 0
    command_families: tuple[str, ...] = ()
    purpose: str = "primary"
    prompt_version: str = ""
    policy_version: str = ""
    is_side_channel: bool = False
    provider: str = "anthropic"
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
    session_id: str
    request_recv_ns: int
    transport_retry_count: int
    provider: str = "anthropic"


@dataclass
class _RequestMeta:
    request_recv_ns: int = 0
    transport_retry_count: int = 0


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


class SideChannelPurposeSummaryRow(TypedDict):
    turns: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    prompt_versions: dict[str, int]
    policy_versions: dict[str, int]


class TurnMetricRecord(TypedDict):
    sequence_num: int
    request_id: str
    session_id: str
    provider: str
    purpose: str
    is_side_channel: bool
    model: str
    stop_reason: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    request_recv_ns: int
    response_recv_ns: int
    latency_ms: float
    retry_key: str
    retry_ordinal: int
    transport_retry_count: int
    is_retry: bool
    was_interrupted: bool
    tool_invocation_count: int
    tool_names: list[str]
    command_count: int
    command_families: list[str]


class TurnMetricSnapshot(TypedDict):
    schema: str
    version: int
    records: list[TurnMetricRecord]


def _extract_session_id(request_body: dict) -> str:
    metadata = request_body.get("metadata", {})
    if not isinstance(metadata, dict):
        return ""
    user_id = metadata.get("user_id", "")
    if not isinstance(user_id, str) or not user_id:
        return ""
    parsed = parse_user_id(user_id)
    if not isinstance(parsed, dict):
        return ""
    session_id = parsed.get("session_id", "")
    return session_id if isinstance(session_id, str) else ""


def _extract_transport_retry_count(headers: dict[str, str]) -> int:
    for key in _RETRY_HEADER_KEYS:
        value = headers.get(key, "")
        try:
            count = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if count >= 0:
            return count
    return 0


def _command_family(command: str) -> str:
    tokens = command.strip().split()
    if not tokens:
        return ""
    return tokens[0].lower()


def _extract_tool_use_command(block: object) -> str:
    if not isinstance(block, dict):
        return ""
    if block.get("type") != "tool_use":
        return ""
    tool_input = block.get("input", {})
    if not isinstance(tool_input, dict):
        return ""
    command = tool_input.get("command", "")
    if not isinstance(command, str):
        return ""
    return command.strip()


def _parse_json_dict(raw: object) -> dict:
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_tool_call_command(tool_call: object) -> str:
    if not isinstance(tool_call, dict):
        return ""
    function = tool_call.get("function", {})
    if not isinstance(function, dict):
        return ""
    parsed_args = _parse_json_dict(function.get("arguments", ""))
    command = parsed_args.get("command", "")
    if not isinstance(command, str):
        return ""
    return command.strip()


def _extract_commands_from_content(content: object) -> list[str]:
    if not isinstance(content, list):
        return []
    commands: list[str] = []
    for block in content:
        command = _extract_tool_use_command(block)
        if command:
            commands.append(command)
    return commands


def _extract_commands_from_tool_calls(tool_calls: object) -> list[str]:
    if not isinstance(tool_calls, list):
        return []
    commands: list[str] = []
    for tool_call in tool_calls:
        command = _extract_tool_call_command(tool_call)
        if command:
            commands.append(command)
    return commands


def _extract_command_usage(messages: list) -> tuple[int, tuple[str, ...]]:
    commands: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        commands.extend(_extract_commands_from_content(message.get("content", [])))
        commands.extend(_extract_commands_from_tool_calls(message.get("tool_calls", [])))

    families = tuple(
        sorted({family for family in (_command_family(command) for command in commands) if family})
    )
    return len(commands), families


def _retry_fingerprint(
    *,
    provider: str,
    session_id: str,
    purpose: str,
    model: str,
    request_body: dict,
) -> str:
    # [LAW:one-source-of-truth] Retry identity is derived once from canonical request payload fields.
    fingerprint_payload = {
        "provider": provider,
        "session_id": session_id,
        "purpose": purpose,
        "model": model,
        "system": request_body.get("system"),
        "messages": request_body.get("messages"),
        "tools": request_body.get("tools"),
        "max_tokens": request_body.get("max_tokens"),
        "temperature": request_body.get("temperature"),
    }
    normalized = json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _compute_latency_ms(request_recv_ns: int, response_recv_ns: int) -> float:
    if request_recv_ns <= 0 or response_recv_ns <= 0:
        return 0.0
    return max(0.0, (response_recv_ns - request_recv_ns) / 1_000_000)


def _is_interrupted_stop_reason(stop_reason: str) -> bool:
    return stop_reason in _INTERRUPTED_STOP_REASONS


def _prune_mapping(mapping: dict, *, limit: int) -> None:
    # [LAW:dataflow-not-control-flow] Pruning is an unconditional bounded-data transform.
    while len(mapping) > limit:
        mapping.pop(next(iter(mapping)))


def _coerce_str(value: object, *, default: str = "") -> str:
    return str(value or default)


def _coerce_int(value: object, *, default: int = 0) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _coerce_float(value: object, *, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _coerce_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _coerce_str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


class AnalyticsStore:
    """In-memory event subscriber that accumulates analytics data.

    Replaces SQLiteWriter. Same event handling logic, but stores data
    in memory instead of SQLite. Query methods translate SQL to Python.
    """

    def __init__(self):
        self._turns: list[TurnRecord] = []
        self._seq = 0
        self._pending: dict[str, _PendingTurn] = {}
        self._request_meta: dict[str, _RequestMeta] = {}
        self._retry_ordinals: dict[str, int] = {}

    @property
    def turn_count(self) -> int:
        """Number of completed turns tracked in analytics store."""
        return len(self._turns)

    def on_event(self, event: PipelineEvent) -> None:
        """Handle an event from the router. Errors logged, never crash the proxy."""
        try:
            self._handle(event)
        except Exception:
            logger.exception("analytics subscriber error")

    def _handle(self, event: PipelineEvent) -> None:
        """Internal event handler - may raise exceptions."""
        if event.kind == PipelineEventKind.REQUEST_HEADERS:
            self._handle_request_headers(event)
            return
        if event.kind == PipelineEventKind.REQUEST:
            self._handle_request(event)
            return
        if event.kind == PipelineEventKind.RESPONSE_COMPLETE:
            self._handle_response_complete(event)

    def _handle_request_headers(self, event: PipelineEvent) -> None:
        assert isinstance(event, RequestHeadersEvent)
        # [LAW:single-enforcer] Retry header normalization happens at this boundary only.
        headers = {str(key).lower(): str(value) for key, value in event.headers.items()}
        self._request_meta[event.request_id] = _RequestMeta(
            request_recv_ns=event.recv_ns,
            transport_retry_count=_extract_transport_retry_count(headers),
        )
        _prune_mapping(self._request_meta, limit=_REQUEST_META_LIMIT)

    def _handle_request(self, event: PipelineEvent) -> None:
        assert isinstance(event, RequestBodyEvent)
        body = event.body if isinstance(event.body, dict) else {}
        marker = extract_marker(body)
        request_meta = self._request_meta.pop(event.request_id, _RequestMeta())
        request_recv_ns = request_meta.request_recv_ns if request_meta.request_recv_ns > 0 else event.recv_ns
        purpose = marker.purpose if marker is not None else "primary"
        prompt_version = marker.prompt_version if marker is not None else ""
        policy_version = marker.policy_version if marker is not None else ""
        self._pending[event.request_id] = _PendingTurn(
            request_id=event.request_id,
            request_body=body,
            model=str(body.get("model", "") or ""),
            purpose=purpose,
            prompt_version=prompt_version,
            policy_version=policy_version,
            is_side_channel=marker is not None,
            session_id=_extract_session_id(body),
            request_recv_ns=request_recv_ns,
            transport_retry_count=request_meta.transport_retry_count,
            provider=event.provider,
        )

    def _handle_response_complete(self, event: PipelineEvent) -> None:
        # [LAW:one-source-of-truth] Extract all response data from complete body.
        assert isinstance(event, ResponseCompleteEvent)
        pending = self._pending.get(event.request_id)
        if pending is None:
            return
        body = event.body
        self._commit_turn(
            pending=pending,
            usage=self._normalize_usage(body),
            model=str(body.get("model", "") or pending.model),
            stop_reason=self._extract_stop_reason(body),
            response_recv_ns=event.recv_ns,
        )

    def _normalize_usage(self, body: dict) -> dict[str, int]:
        usage = body.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        # [LAW:single-enforcer] Normalize provider-specific usage keys at this boundary.
        return {
            "input_tokens": usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0) or usage.get("completion_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
        }

    def _extract_stop_reason(self, body: dict) -> str:
        # Anthropic: top-level stop_reason. OpenAI: choices[0].finish_reason.
        stop_reason = str(body.get("stop_reason", "") or "")
        if stop_reason:
            return stop_reason
        choices = body.get("choices", [])
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            return str(choices[0].get("finish_reason", "") or "")
        return ""

    def _messages_from_request(self, request_body: dict) -> list:
        messages = request_body.get("messages", [])
        return messages if isinstance(messages, list) else []

    def _build_tool_records(self, messages: list) -> list[ToolInvocationRecord]:
        records: list[ToolInvocationRecord] = []
        for inv in correlate_tools(messages):
            records.append(
                ToolInvocationRecord(
                    tool_name=inv.name,
                    tool_use_id=inv.tool_use_id,
                    input_tokens=count_tokens(inv.input_str),
                    result_tokens=count_tokens(inv.result_str),
                    is_error=inv.is_error,
                )
            )
        return records

    def _next_retry_ordinal(self, pending: _PendingTurn, model: str) -> tuple[str, int]:
        retry_key = _retry_fingerprint(
            provider=pending.provider,
            session_id=pending.session_id,
            purpose=pending.purpose,
            model=model,
            request_body=pending.request_body,
        )
        retry_ordinal = self._retry_ordinals.get(retry_key, 0)
        self._retry_ordinals[retry_key] = retry_ordinal + 1
        _prune_mapping(self._retry_ordinals, limit=_RETRY_ORDINAL_LIMIT)
        return retry_key, retry_ordinal

    def _build_turn_record(
        self,
        *,
        pending: _PendingTurn,
        usage: dict[str, int],
        model: str,
        stop_reason: str,
        response_recv_ns: int,
    ) -> TurnRecord:
        messages = self._messages_from_request(pending.request_body)
        tool_records = self._build_tool_records(messages)
        command_count, command_families = _extract_command_usage(messages)
        retry_key, retry_ordinal = self._next_retry_ordinal(pending, model)
        return TurnRecord(
            sequence_num=self._seq,
            request_id=pending.request_id,
            session_id=pending.session_id,
            model=model,
            stop_reason=stop_reason,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
            request_json=json.dumps(pending.request_body),
            request_recv_ns=pending.request_recv_ns,
            response_recv_ns=response_recv_ns,
            latency_ms=_compute_latency_ms(pending.request_recv_ns, response_recv_ns),
            retry_key=retry_key,
            retry_ordinal=retry_ordinal,
            transport_retry_count=pending.transport_retry_count,
            was_interrupted=_is_interrupted_stop_reason(stop_reason),
            command_count=command_count,
            command_families=command_families,
            purpose=pending.purpose,
            prompt_version=pending.prompt_version,
            policy_version=pending.policy_version,
            is_side_channel=pending.is_side_channel,
            provider=pending.provider,
            tool_invocations=tool_records,
        )

    def _commit_turn(
        self,
        *,
        pending: _PendingTurn,
        usage: dict[str, int],
        model: str,
        stop_reason: str,
        response_recv_ns: int,
    ) -> None:
        """Store accumulated turn in memory."""
        if not pending.request_body:
            return

        self._seq += 1
        turn = self._build_turn_record(
            pending=pending,
            usage=usage,
            model=model,
            stop_reason=stop_reason,
            response_recv_ns=response_recv_ns,
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

    def get_turn_metrics_snapshot(self) -> TurnMetricSnapshot:
        """Return deterministic per-turn metric records with explicit schema/version."""
        # [LAW:one-source-of-truth] Per-turn metrics derive from canonical TurnRecord rows.
        records: list[TurnMetricRecord] = []
        for turn in self._turns:
            records.append(
                {
                    "sequence_num": turn.sequence_num,
                    "request_id": turn.request_id,
                    "session_id": turn.session_id,
                    "provider": turn.provider,
                    "purpose": turn.purpose,
                    "is_side_channel": turn.is_side_channel,
                    "model": turn.model,
                    "stop_reason": turn.stop_reason,
                    "input_tokens": turn.input_tokens,
                    "output_tokens": turn.output_tokens,
                    "cache_read_tokens": turn.cache_read_tokens,
                    "cache_creation_tokens": turn.cache_creation_tokens,
                    "request_recv_ns": turn.request_recv_ns,
                    "response_recv_ns": turn.response_recv_ns,
                    "latency_ms": turn.latency_ms,
                    "retry_key": turn.retry_key,
                    "retry_ordinal": turn.retry_ordinal,
                    "transport_retry_count": turn.transport_retry_count,
                    "is_retry": turn.retry_ordinal > 0,
                    "was_interrupted": turn.was_interrupted,
                    "tool_invocation_count": len(turn.tool_invocations),
                    "tool_names": sorted({inv.tool_name for inv in turn.tool_invocations if inv.tool_name}),
                    "command_count": turn.command_count,
                    "command_families": list(turn.command_families),
                }
            )
        return {
            "schema": TURN_METRICS_SCHEMA,
            "version": TURN_METRICS_VERSION,
            "records": records,
        }

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

    def get_side_channel_purpose_summary(self) -> dict[str, SideChannelPurposeSummaryRow]:
        """Aggregate side-channel token usage by purpose."""
        summary: dict[str, SideChannelPurposeSummaryRow] = {}
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
                versions[turn.prompt_version] = versions.get(turn.prompt_version, 0) + 1
            if turn.policy_version:
                policy_versions = row["policy_versions"]
                policy_versions[turn.policy_version] = (
                    policy_versions.get(turn.policy_version, 0) + 1
                )
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

    def _serialize_tool_invocation(self, inv: ToolInvocationRecord) -> dict:
        return {
            "tool_name": inv.tool_name,
            "tool_use_id": inv.tool_use_id,
            "input_tokens": inv.input_tokens,
            "result_tokens": inv.result_tokens,
            "is_error": inv.is_error,
        }

    def _serialize_turn(self, turn: TurnRecord) -> dict:
        return {
            "sequence_num": turn.sequence_num,
            "request_id": turn.request_id,
            "session_id": turn.session_id,
            "model": turn.model,
            "stop_reason": turn.stop_reason,
            "input_tokens": turn.input_tokens,
            "output_tokens": turn.output_tokens,
            "cache_read_tokens": turn.cache_read_tokens,
            "cache_creation_tokens": turn.cache_creation_tokens,
            "request_json": turn.request_json,
            "request_recv_ns": turn.request_recv_ns,
            "response_recv_ns": turn.response_recv_ns,
            "latency_ms": turn.latency_ms,
            "retry_key": turn.retry_key,
            "retry_ordinal": turn.retry_ordinal,
            "transport_retry_count": turn.transport_retry_count,
            "was_interrupted": turn.was_interrupted,
            "command_count": turn.command_count,
            "command_families": list(turn.command_families),
            "purpose": turn.purpose,
            "prompt_version": turn.prompt_version,
            "policy_version": turn.policy_version,
            "is_side_channel": turn.is_side_channel,
            "provider": turn.provider,
            "tool_invocations": [
                self._serialize_tool_invocation(inv) for inv in turn.tool_invocations
            ],
        }

    def _serialize_pending_turn(self, pending: _PendingTurn) -> dict:
        return {
            "request_id": pending.request_id,
            "request_body": pending.request_body,
            "model": pending.model,
            "purpose": pending.purpose,
            "prompt_version": pending.prompt_version,
            "policy_version": pending.policy_version,
            "is_side_channel": pending.is_side_channel,
            "session_id": pending.session_id,
            "request_recv_ns": pending.request_recv_ns,
            "transport_retry_count": pending.transport_retry_count,
            "provider": pending.provider,
        }

    def _serialize_request_meta(self, request_id: str, meta: _RequestMeta) -> dict:
        return {
            "request_id": request_id,
            "request_recv_ns": meta.request_recv_ns,
            "transport_retry_count": meta.transport_retry_count,
        }

    def get_state(self) -> dict:
        """Extract state for hot-reload preservation."""
        return {
            "turns": [self._serialize_turn(turn) for turn in self._turns],
            "seq": self._seq,
            "pending": [
                self._serialize_pending_turn(pending)
                for pending in self._pending.values()
            ],
            "request_meta": [
                self._serialize_request_meta(request_id, meta)
                for request_id, meta in self._request_meta.items()
            ],
            "retry_ordinals": dict(self._retry_ordinals),
        }

    def _restore_tool_invocations(self, serialized: object) -> list[ToolInvocationRecord]:
        if not isinstance(serialized, list):
            return []
        tool_invocations: list[ToolInvocationRecord] = []
        for inv in serialized:
            if not isinstance(inv, dict):
                continue
            tool_invocations.append(
                ToolInvocationRecord(
                    tool_name=inv["tool_name"],
                    tool_use_id=inv["tool_use_id"],
                    input_tokens=inv["input_tokens"],
                    result_tokens=inv["result_tokens"],
                    is_error=inv["is_error"],
                )
            )
        return tool_invocations

    def _restore_turn_record(self, t_data: dict) -> TurnRecord:
        return TurnRecord(
            sequence_num=t_data["sequence_num"],
            request_id=_coerce_str(t_data.get("request_id", "")),
            session_id=_coerce_str(t_data.get("session_id", "")),
            model=t_data["model"],
            stop_reason=t_data["stop_reason"],
            input_tokens=t_data["input_tokens"],
            output_tokens=t_data["output_tokens"],
            cache_read_tokens=t_data["cache_read_tokens"],
            cache_creation_tokens=t_data["cache_creation_tokens"],
            request_json=t_data["request_json"],
            request_recv_ns=_coerce_int(t_data.get("request_recv_ns", 0)),
            response_recv_ns=_coerce_int(t_data.get("response_recv_ns", 0)),
            latency_ms=_coerce_float(t_data.get("latency_ms", 0.0)),
            retry_key=_coerce_str(t_data.get("retry_key", "")),
            retry_ordinal=_coerce_int(t_data.get("retry_ordinal", 0)),
            transport_retry_count=_coerce_int(t_data.get("transport_retry_count", 0)),
            was_interrupted=bool(t_data.get("was_interrupted", False)),
            command_count=_coerce_int(t_data.get("command_count", 0)),
            command_families=_coerce_str_tuple(t_data.get("command_families", [])),
            purpose=_coerce_str(t_data.get("purpose", "primary"), default="primary"),
            prompt_version=_coerce_str(t_data.get("prompt_version", "")),
            policy_version=_coerce_str(t_data.get("policy_version", "")),
            is_side_channel=bool(t_data.get("is_side_channel", False)),
            provider=_coerce_str(t_data.get("provider", "anthropic"), default="anthropic"),
            tool_invocations=self._restore_tool_invocations(
                t_data.get("tool_invocations", [])
            ),
        )

    def _restore_turns(self, serialized: object) -> list[TurnRecord]:
        if not isinstance(serialized, list):
            return []
        turns: list[TurnRecord] = []
        for t_data in serialized:
            if not isinstance(t_data, dict):
                continue
            turns.append(self._restore_turn_record(t_data))
        return turns

    def _restore_pending(self, serialized: object) -> dict[str, _PendingTurn]:
        if not isinstance(serialized, list):
            return {}
        pending: dict[str, _PendingTurn] = {}
        for p_data in serialized:
            if not isinstance(p_data, dict):
                continue
            restored = self._restore_pending_entry(p_data)
            if restored is None:
                continue
            request_id, pending_turn = restored
            pending[request_id] = pending_turn
        return pending

    def _restore_pending_entry(self, p_data: dict) -> tuple[str, _PendingTurn] | None:
        request_id = _coerce_str(p_data.get("request_id", ""))
        if not request_id:
            return None
        pending_turn = _PendingTurn(
            request_id=request_id,
            request_body=_coerce_dict(p_data.get("request_body", {})),
            model=_coerce_str(p_data.get("model", "")),
            purpose=_coerce_str(p_data.get("purpose", "primary"), default="primary"),
            prompt_version=_coerce_str(p_data.get("prompt_version", "")),
            policy_version=_coerce_str(p_data.get("policy_version", "")),
            is_side_channel=bool(p_data.get("is_side_channel", False)),
            session_id=_coerce_str(p_data.get("session_id", "")),
            request_recv_ns=_coerce_int(p_data.get("request_recv_ns", 0)),
            transport_retry_count=_coerce_int(p_data.get("transport_retry_count", 0)),
            provider=_coerce_str(p_data.get("provider", "anthropic"), default="anthropic"),
        )
        return request_id, pending_turn

    def _restore_request_meta(self, serialized: object) -> dict[str, _RequestMeta]:
        if not isinstance(serialized, list):
            return {}
        request_meta: dict[str, _RequestMeta] = {}
        for meta_data in serialized:
            if not isinstance(meta_data, dict):
                continue
            request_id = str(meta_data.get("request_id", "") or "")
            if not request_id:
                continue
            request_meta[request_id] = _RequestMeta(
                request_recv_ns=int(meta_data.get("request_recv_ns", 0) or 0),
                transport_retry_count=int(meta_data.get("transport_retry_count", 0) or 0),
            )
        return request_meta

    def _restore_retry_ordinals(self, serialized: object) -> dict[str, int]:
        if not isinstance(serialized, dict):
            return {}
        retry_ordinals: dict[str, int] = {}
        for key, value in serialized.items():
            if not isinstance(key, str):
                continue
            retry_ordinals[key] = int(value or 0)
        return retry_ordinals

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        # [LAW:dataflow-not-control-flow] Restore every slice from snapshot in a fixed sequence.
        self._turns = self._restore_turns(state.get("turns", []))
        self._seq = state.get("seq", 0)
        self._pending = self._restore_pending(state.get("pending", []))
        self._request_meta = self._restore_request_meta(state.get("request_meta", []))
        _prune_mapping(self._request_meta, limit=_REQUEST_META_LIMIT)
        self._retry_ordinals = self._restore_retry_ordinals(
            state.get("retry_ordinals", {})
        )
        _prune_mapping(self._retry_ordinals, limit=_RETRY_ORDINAL_LIMIT)
