"""Tests for cc_dump.event_types — constructor validation, parse round-trips, immutability."""

import pytest

from cc_dump.event_types import (
    # Enums
    PipelineEventKind,
    ContentBlockType,
    StopReason,
    MessageRole,
    # Value types
    Usage,
    MessageInfo,
    # SSE events
    SSEEvent,
    MessageStartEvent,
    TextBlockStartEvent,
    ToolUseBlockStartEvent,
    TextDeltaEvent,
    InputJsonDeltaEvent,
    ContentBlockStopEvent,
    MessageDeltaEvent,
    MessageStopEvent,
    # Pipeline events
    PipelineEvent,
    RequestHeadersEvent,
    RequestBodyEvent,
    ResponseHeadersEvent,
    ResponseSSEEvent,
    ResponseDoneEvent,
    ErrorEvent,
    ProxyErrorEvent,
    LogEvent,
    # Parse boundary
    parse_sse_event,
)

# ─── Value types ─────────────────────────────────────────────────────────────

class TestUsage:
    def test_frozen(self):
        u = Usage()
        with pytest.raises(AttributeError):
            u.input_tokens = 42


class TestMessageInfo:
    def test_frozen(self):
        mi = MessageInfo(id="x", role=MessageRole.USER, model="m", usage=Usage())
        with pytest.raises(AttributeError):
            mi.id = "y"


# ─── SSE Events ──────────────────────────────────────────────────────────────


class TestSSEEvents:
    def test_text_block_start(self):
        evt = TextBlockStartEvent(index=0)
        assert evt.index == 0

    def test_tool_use_block_start(self):
        evt = ToolUseBlockStartEvent(index=1, id="toolu_123", name="read_file")
        assert evt.id == "toolu_123"
        assert evt.name == "read_file"

    def test_text_delta(self):
        evt = TextDeltaEvent(index=0, text="Hello world")
        assert evt.text == "Hello world"

    def test_input_json_delta(self):
        evt = InputJsonDeltaEvent(index=0, partial_json='{"key": "val"}')
        assert evt.partial_json == '{"key": "val"}'

    def test_content_block_stop(self):
        evt = ContentBlockStopEvent(index=2)
        assert evt.index == 2

    def test_message_delta(self):
        evt = MessageDeltaEvent(
            stop_reason=StopReason.END_TURN,
            stop_sequence="",
            output_tokens=28,
        )
        assert evt.stop_reason == StopReason.END_TURN
        assert evt.output_tokens == 28

    def test_all_frozen(self):
        evt = TextDeltaEvent(index=0, text="x")
        with pytest.raises(AttributeError):
            evt.text = "y"


# ─── Pipeline Events ─────────────────────────────────────────────────────────


class TestPipelineEvents:
    def test_request_headers_kind(self):
        evt = RequestHeadersEvent(headers={"a": "b"})
        assert evt.kind == PipelineEventKind.REQUEST_HEADERS
        assert isinstance(evt, PipelineEvent)
        assert evt.headers == {"a": "b"}

    def test_request_body_kind(self):
        evt = RequestBodyEvent(body={"model": "claude-3"})
        assert evt.kind == PipelineEventKind.REQUEST
        assert evt.body == {"model": "claude-3"}

    def test_response_headers_kind(self):
        evt = ResponseHeadersEvent(status_code=200, headers={"x": "y"})
        assert evt.kind == PipelineEventKind.RESPONSE_HEADERS
        assert evt.status_code == 200

    def test_response_sse_kind(self):
        sse = MessageStopEvent()
        evt = ResponseSSEEvent(sse_event=sse)
        assert evt.kind == PipelineEventKind.RESPONSE_EVENT
        assert evt.sse_event is sse

    def test_response_done_kind(self):
        evt = ResponseDoneEvent()
        assert evt.kind == PipelineEventKind.RESPONSE_DONE

    def test_error_kind(self):
        evt = ErrorEvent(code=500, reason="Internal Server Error")
        assert evt.kind == PipelineEventKind.ERROR
        assert evt.code == 500

    def test_proxy_error_kind(self):
        evt = ProxyErrorEvent(error="Connection refused")
        assert evt.kind == PipelineEventKind.PROXY_ERROR
        assert evt.error == "Connection refused"

    def test_log_kind(self):
        evt = LogEvent(method="POST", path="/v1/messages", status="200")
        assert evt.kind == PipelineEventKind.LOG
        assert evt.method == "POST"

    def test_response_non_streaming_kind(self):
        from cc_dump.event_types import ResponseNonStreamingEvent
        evt = ResponseNonStreamingEvent(status_code=200, headers={}, body={"id": "msg_1"})
        assert evt.kind == PipelineEventKind.RESPONSE_NON_STREAMING
        assert evt.status_code == 200
        assert evt.body["id"] == "msg_1"

    def test_kind_not_settable_by_caller(self):
        """kind is set by the subclass, not passed in."""
        # PipelineEventKind.REQUEST is set automatically by RequestBodyEvent
        evt = RequestBodyEvent(body={})
        assert evt.kind == PipelineEventKind.REQUEST

    def test_all_frozen(self):
        evt = ErrorEvent(code=400, reason="Bad Request")
        with pytest.raises(AttributeError):
            evt.code = 500


# ─── parse_sse_event boundary ────────────────────────────────────────────────


class TestParseSSEEvent:
    def test_message_start(self):
        raw = {
            "type": "message_start",
            "message": {
                "id": "msg_abc",
                "role": "assistant",
                "model": "claude-3-opus",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 0,
                    "cache_read_input_tokens": 50,
                    "cache_creation_input_tokens": 25,
                },
            },
        }
        evt = parse_sse_event("message_start", raw)
        assert isinstance(evt, MessageStartEvent)
        assert evt.message.id == "msg_abc"
        assert evt.message.role == MessageRole.ASSISTANT
        assert evt.message.model == "claude-3-opus"
        assert evt.message.usage.input_tokens == 100
        assert evt.message.usage.cache_read_input_tokens == 50

    def test_text_block_start(self):
        raw = {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }
        evt = parse_sse_event("content_block_start", raw)
        assert isinstance(evt, TextBlockStartEvent)
        assert evt.index == 0

    def test_tool_use_block_start(self):
        raw = {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_x", "name": "bash"},
        }
        evt = parse_sse_event("content_block_start", raw)
        assert isinstance(evt, ToolUseBlockStartEvent)
        assert evt.id == "toolu_x"
        assert evt.name == "bash"

    def test_text_delta(self):
        raw = {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello!"},
        }
        evt = parse_sse_event("content_block_delta", raw)
        assert isinstance(evt, TextDeltaEvent)
        assert evt.text == "Hello!"

    def test_input_json_delta(self):
        raw = {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"path":'},
        }
        evt = parse_sse_event("content_block_delta", raw)
        assert isinstance(evt, InputJsonDeltaEvent)
        assert evt.partial_json == '{"path":'

    def test_content_block_stop(self):
        raw = {"type": "content_block_stop", "index": 0}
        evt = parse_sse_event("content_block_stop", raw)
        assert isinstance(evt, ContentBlockStopEvent)
        assert evt.index == 0

    def test_message_delta(self):
        raw = {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 42},
        }
        evt = parse_sse_event("message_delta", raw)
        assert isinstance(evt, MessageDeltaEvent)
        assert evt.stop_reason == StopReason.END_TURN
        assert evt.output_tokens == 42

    def test_message_delta_tool_use_stop(self):
        raw = {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 10},
        }
        evt = parse_sse_event("message_delta", raw)
        assert evt.stop_reason == StopReason.TOOL_USE

    def test_message_stop(self):
        raw = {"type": "message_stop"}
        evt = parse_sse_event("message_stop", raw)
        assert isinstance(evt, MessageStopEvent)

    def test_unknown_event_type_raises(self):
        with pytest.raises(ValueError, match="Unknown SSE event type"):
            parse_sse_event("ping", {})

    def test_missing_fields_use_defaults(self):
        """parse_sse_event is tolerant of missing fields."""
        raw = {"type": "message_start", "message": {}}
        evt = parse_sse_event("message_start", raw)
        assert isinstance(evt, MessageStartEvent)
        assert evt.message.id == ""
        assert evt.message.model == ""
        assert evt.message.usage.input_tokens == 0

    def test_message_delta_missing_stop_reason(self):
        raw = {"type": "message_delta", "delta": {}, "usage": {}}
        evt = parse_sse_event("message_delta", raw)
        assert evt.stop_reason == StopReason.NONE
        assert evt.output_tokens == 0
