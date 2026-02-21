"""Type-safe event system for the cc-dump pipeline.

// [LAW:one-source-of-truth] The class IS the type — no event_type string field.
// [LAW:single-enforcer] parse_sse_event is the sole SSE validation boundary.

This module is STABLE — never hot-reloaded. Safe for `from` imports everywhere.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


# ─── Type alias for JSON-parsed dicts ─────────────────────────────────────────

JsonDict = dict[str, object]


# ─── Enums ────────────────────────────────────────────────────────────────────


class PipelineEventKind(Enum):
    """Discriminator for pipeline events."""

    REQUEST_HEADERS = "request_headers"
    REQUEST = "request"
    RESPONSE_HEADERS = "response_headers"
    RESPONSE_EVENT = "response_event"
    RESPONSE_NON_STREAMING = "response_non_streaming"
    RESPONSE_COMPLETE = "response_complete"
    RESPONSE_DONE = "response_done"
    ERROR = "error"
    PROXY_ERROR = "proxy_error"
    LOG = "log"


class ContentBlockType(Enum):
    """Content block type in request body JSON."""

    TEXT = "text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"


class StopReason(Enum):
    """Stop reason from message_delta."""

    NONE = ""
    END_TURN = "end_turn"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"
    TOOL_USE = "tool_use"


class MessageRole(Enum):
    """Message role."""

    USER = "user"
    ASSISTANT = "assistant"


# ─── Value types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Usage:
    """Token usage counts."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass(frozen=True)
class MessageInfo:
    """Message metadata from message_start."""

    id: str
    role: MessageRole
    model: str
    usage: Usage


# ─── SSE Event Hierarchy ─────────────────────────────────────────────────────
# // [LAW:one-source-of-truth] The class IS the type — no event_type field needed.


@dataclass(frozen=True)
class SSEEvent:
    """Base class for all SSE events."""


@dataclass(frozen=True)
class MessageStartEvent(SSEEvent):
    """message_start SSE event."""

    message: MessageInfo


@dataclass(frozen=True)
class TextBlockStartEvent(SSEEvent):
    """content_block_start with type=text."""

    index: int


@dataclass(frozen=True)
class ToolUseBlockStartEvent(SSEEvent):
    """content_block_start with type=tool_use."""

    index: int
    id: str
    name: str


@dataclass(frozen=True)
class TextDeltaEvent(SSEEvent):
    """content_block_delta with type=text_delta."""

    index: int
    text: str


@dataclass(frozen=True)
class InputJsonDeltaEvent(SSEEvent):
    """content_block_delta with type=input_json_delta."""

    index: int
    partial_json: str


@dataclass(frozen=True)
class ContentBlockStopEvent(SSEEvent):
    """content_block_stop SSE event."""

    index: int


@dataclass(frozen=True)
class MessageDeltaEvent(SSEEvent):
    """message_delta SSE event."""

    stop_reason: StopReason
    stop_sequence: str
    output_tokens: int


@dataclass(frozen=True)
class MessageStopEvent(SSEEvent):
    """message_stop SSE event."""


# ─── Pipeline Event Hierarchy ─────────────────────────────────────────────────
# // [LAW:one-source-of-truth] kind is set by subclass, not caller.


@dataclass(frozen=True)
class PipelineEvent:
    """Base class for all pipeline events.

    // [LAW:one-source-of-truth] request_id/seq/recv_ns defined once here,
    // inherited by all event types. Populated on response-side events by proxy.
    """

    kind: PipelineEventKind = field(init=False)
    request_id: str = field(default="", kw_only=True)
    seq: int = field(default=0, kw_only=True)
    recv_ns: int = field(default=0, kw_only=True)


@dataclass(frozen=True)
class RequestHeadersEvent(PipelineEvent):
    """HTTP request headers."""

    headers: dict[str, str]
    kind: PipelineEventKind = field(default=PipelineEventKind.REQUEST_HEADERS, init=False)


@dataclass(frozen=True)
class RequestBodyEvent(PipelineEvent):
    """Parsed request body JSON."""

    body: dict[str, object]
    kind: PipelineEventKind = field(default=PipelineEventKind.REQUEST, init=False)


@dataclass(frozen=True)
class ResponseHeadersEvent(PipelineEvent):
    """HTTP response headers."""

    status_code: int
    headers: dict[str, str]
    kind: PipelineEventKind = field(default=PipelineEventKind.RESPONSE_HEADERS, init=False)


@dataclass(frozen=True)
class ResponseSSEEvent(PipelineEvent):
    """A parsed SSE event from the response stream."""

    sse_event: SSEEvent
    kind: PipelineEventKind = field(default=PipelineEventKind.RESPONSE_EVENT, init=False)


@dataclass(frozen=True)
class ResponseNonStreamingEvent(PipelineEvent):
    """A complete (non-streaming) HTTP response."""

    status_code: int
    headers: dict[str, str]
    body: dict
    kind: PipelineEventKind = field(default=PipelineEventKind.RESPONSE_NON_STREAMING, init=False)


@dataclass(frozen=True)
class ResponseCompleteEvent(PipelineEvent):
    """Complete reconstructed response from SSE assembly.

    Emitted by the proxy after assembling all SSE fragments into a complete
    Claude API response. Carries the same shape as a stream=false response.
    """

    body: dict
    kind: PipelineEventKind = field(default=PipelineEventKind.RESPONSE_COMPLETE, init=False)


@dataclass(frozen=True)
class ResponseDoneEvent(PipelineEvent):
    """Response stream completed."""

    kind: PipelineEventKind = field(default=PipelineEventKind.RESPONSE_DONE, init=False)


@dataclass(frozen=True)
class ErrorEvent(PipelineEvent):
    """HTTP error from upstream."""

    code: int
    reason: str
    kind: PipelineEventKind = field(default=PipelineEventKind.ERROR, init=False)


@dataclass(frozen=True)
class ProxyErrorEvent(PipelineEvent):
    """Proxy-level error (connection failure, etc.)."""

    error: str
    kind: PipelineEventKind = field(default=PipelineEventKind.PROXY_ERROR, init=False)


@dataclass(frozen=True)
class LogEvent(PipelineEvent):
    """HTTP access log entry."""

    method: str
    path: str
    status: str
    kind: PipelineEventKind = field(default=PipelineEventKind.LOG, init=False)


# ─── Parse boundary ──────────────────────────────────────────────────────────
# // [LAW:single-enforcer] Single parse boundary for SSE data validation.


def _str(v: object) -> str:
    """Narrow object to str."""
    if isinstance(v, str):
        return v
    return str(v)


def _int(v: object) -> int:
    """Narrow object to int."""
    if isinstance(v, int):
        return v
    return int(str(v))


def parse_sse_event(event_type: str, raw: dict[str, object]) -> SSEEvent:
    """Parse a raw SSE event dict into a typed SSEEvent.

    Called at the two production boundaries: proxy.py (live) and har_replayer.py (replay).

    Args:
        event_type: The SSE event type string (e.g., "message_start")
        raw: The parsed JSON event data

    Returns:
        Typed SSEEvent subclass

    Raises:
        ValueError: If event_type is unknown
    """
    handler = _SSE_PARSERS.get(event_type)
    if handler is None:
        raise ValueError(f"Unknown SSE event type: {event_type!r}")
    return handler(raw)


def _parse_message_start(raw: dict[str, object]) -> MessageStartEvent:
    msg_raw = raw.get("message", {})
    if not isinstance(msg_raw, dict):
        msg_raw = {}
    usage_raw = msg_raw.get("usage", {})
    if not isinstance(usage_raw, dict):
        usage_raw = {}
    role_str = _str(msg_raw.get("role", "assistant"))
    role = MessageRole(role_str) if role_str in ("user", "assistant") else MessageRole.ASSISTANT
    usage = Usage(
        input_tokens=_int(usage_raw.get("input_tokens", 0)),
        output_tokens=_int(usage_raw.get("output_tokens", 0)),
        cache_read_input_tokens=_int(usage_raw.get("cache_read_input_tokens", 0)),
        cache_creation_input_tokens=_int(usage_raw.get("cache_creation_input_tokens", 0)),
    )
    return MessageStartEvent(
        message=MessageInfo(
            id=_str(msg_raw.get("id", "")),
            role=role,
            model=_str(msg_raw.get("model", "")),
            usage=usage,
        )
    )


def _parse_content_block_start(raw: dict[str, object]) -> SSEEvent:
    index = _int(raw.get("index", 0))
    block_raw = raw.get("content_block", {})
    if not isinstance(block_raw, dict):
        block_raw = {}
    block_type = _str(block_raw.get("type", ""))
    if block_type == "tool_use":
        return ToolUseBlockStartEvent(
            index=index,
            id=_str(block_raw.get("id", "")),
            name=_str(block_raw.get("name", "")),
        )
    return TextBlockStartEvent(index=index)


def _parse_content_block_delta(raw: dict[str, object]) -> SSEEvent:
    index = _int(raw.get("index", 0))
    delta_raw = raw.get("delta", {})
    if not isinstance(delta_raw, dict):
        delta_raw = {}
    delta_type = _str(delta_raw.get("type", ""))
    if delta_type == "input_json_delta":
        return InputJsonDeltaEvent(
            index=index,
            partial_json=_str(delta_raw.get("partial_json", "")),
        )
    return TextDeltaEvent(
        index=index,
        text=_str(delta_raw.get("text", "")),
    )


def _parse_content_block_stop(raw: dict[str, object]) -> ContentBlockStopEvent:
    return ContentBlockStopEvent(index=_int(raw.get("index", 0)))


def _parse_message_delta(raw: dict[str, object]) -> MessageDeltaEvent:
    delta_raw = raw.get("delta", {})
    if not isinstance(delta_raw, dict):
        delta_raw = {}
    usage_raw = raw.get("usage", {})
    if not isinstance(usage_raw, dict):
        usage_raw = {}
    stop_str = _str(delta_raw.get("stop_reason", ""))
    try:
        stop_reason = StopReason(stop_str)
    except ValueError:
        stop_reason = StopReason.NONE
    return MessageDeltaEvent(
        stop_reason=stop_reason,
        stop_sequence=_str(delta_raw.get("stop_sequence", "")),
        output_tokens=_int(usage_raw.get("output_tokens", 0)),
    )


def _parse_message_stop(_raw: dict[str, object]) -> MessageStopEvent:
    return MessageStopEvent()


# [LAW:dataflow-not-control-flow] Dispatch table for SSE parsing
_SSE_PARSERS: dict[str, Callable[[dict[str, object]], SSEEvent]] = {
    "message_start": _parse_message_start,
    "content_block_start": _parse_content_block_start,
    "content_block_delta": _parse_content_block_delta,
    "content_block_stop": _parse_content_block_stop,
    "message_delta": _parse_message_delta,
    "message_stop": _parse_message_stop,
}
