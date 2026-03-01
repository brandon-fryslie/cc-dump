"""Behavioral tests for the replay pipeline.

Tests that replay (non-streaming) data flows through the same pipeline as live
data and produces visible, correct content — without asserting on internal
event types or implementation structure.
"""

import json
import pytest
from unittest.mock import MagicMock

from cc_dump.app.domain_store import DomainStore

from cc_dump.core.formatting import (
    FormattedBlock,
    HttpHeadersBlock,
    StreamInfoBlock,
    StopReasonBlock,
    TextContentBlock,
    StreamToolUseBlock,
    ThinkingBlock,
    format_complete_response,
    format_request,
    format_response_headers,
)
from cc_dump.pipeline.har_replayer import load_har, convert_to_events
from cc_dump.tui.event_handlers import (
    handle_request_headers,
    handle_request,
    handle_response_progress,
    handle_response_event,
    handle_response_headers,
    handle_response_complete,
    handle_response_non_streaming,
)
from cc_dump.pipeline.response_assembler import ResponseAssembler
from cc_dump.pipeline.event_types import (
    RequestHeadersEvent,
    RequestBodyEvent,
    ResponseHeadersEvent,
    ResponseSSEEvent,
    ResponseCompleteEvent,
    ResponseNonStreamingEvent,
    PipelineEventKind,
    parse_sse_event,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


def _make_complete_message(
    text="Hello!", model="claude-3-opus-20240229", stop_reason="end_turn",
    content=None, msg_id="msg_test",
):
    """Build a complete Claude API response message."""
    if content is None:
        content = [{"type": "text", "text": text}]
    return {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "content": content,
        "model": model,
        "stop_reason": stop_reason,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def _make_har(entries):
    """Build a minimal HAR dict from simplified entries."""
    har_entries = []
    for req_body, resp_body in entries:
        har_entries.append({
            "request": {
                "method": "POST",
                "url": "https://api.anthropic.com/v1/messages",
                "headers": [{"name": "content-type", "value": "application/json"}],
                "postData": {
                    "mimeType": "application/json",
                    "text": json.dumps(req_body),
                },
            },
            "response": {
                "status": 200,
                "headers": [{"name": "content-type", "value": "application/json"}],
                "content": {
                    "mimeType": "application/json",
                    "text": json.dumps(resp_body),
                },
            },
        })
    return {"log": {"version": "1.2", "entries": har_entries}}


def _mock_widgets():
    """Create minimal mock widgets for event handler tests."""
    conv = MagicMock()
    stats = MagicMock()
    ds = DomainStore()
    return {
        "conv": conv,
        "stats": stats,
        "filters": {},
        "refresh_callbacks": {},
        "analytics_store": None,
        "domain_store": ds,
    }


def _find_blocks(blocks, block_type):
    """Recursively find blocks of a given type."""
    result = []
    for block in blocks:
        if isinstance(block, block_type):
            result.append(block)
        for child in getattr(block, "children", []):
            result.extend(_find_blocks([child], block_type))
    return result


def _walk_blocks(blocks):
    for block in blocks:
        yield block
        yield from _walk_blocks(getattr(block, "children", []))


def _run_pipeline_events(events):
    """Run request/response events through the canonical handler boundary."""
    widgets = _mock_widgets()
    state = {
        "request_counter": 0,
        "positions": {},
        "known_hashes": {},
        "next_id": 1,
        "next_color": 0,
    }
    app_state = {}

    for event in events:
        if event.kind == PipelineEventKind.REQUEST_HEADERS:
            app_state = handle_request_headers(
                event, state, widgets, app_state, lambda *a: None
            )
        elif event.kind == PipelineEventKind.REQUEST:
            app_state = handle_request(event, state, widgets, app_state, lambda *a: None)
        elif event.kind == PipelineEventKind.RESPONSE_HEADERS:
            app_state = handle_response_headers(
                event, state, widgets, app_state, lambda *a: None
            )
        elif event.kind == PipelineEventKind.RESPONSE_EVENT:
            app_state = handle_response_event(
                event, state, widgets, app_state, lambda *a: None
            )
        elif event.kind == PipelineEventKind.RESPONSE_PROGRESS:
            app_state = handle_response_progress(
                event, state, widgets, app_state, lambda *a: None
            )
        elif event.kind == PipelineEventKind.RESPONSE_COMPLETE:
            app_state = handle_response_complete(
                event, state, widgets, app_state, lambda *a: None
            )
        elif event.kind == PipelineEventKind.RESPONSE_NON_STREAMING:
            app_state = handle_response_non_streaming(
                event, state, widgets, app_state, lambda *a: None
            )

    return state, widgets, app_state


def _project_response_turn(blocks):
    """Projection for live-vs-replay parity contracts (ignores volatile IDs/timestamps)."""
    response_headers = tuple(
        (
            int(block.status_code),
            tuple(sorted((str(k), str(v)) for k, v in block.headers.items())),
        )
        for block in _find_blocks(blocks, HttpHeadersBlock)
        if block.header_type == "response"
    )
    models = tuple(block.model for block in _find_blocks(blocks, StreamInfoBlock))
    stop_reasons = tuple(block.reason for block in _find_blocks(blocks, StopReasonBlock))
    text = tuple(block.content for block in _find_blocks(blocks, TextContentBlock))
    tool_use_names = tuple(
        block.name for block in _find_blocks(blocks, StreamToolUseBlock)
    )
    attribution = tuple(
        sorted(
            {
                str(getattr(block, "session_id", ""))
                for block in _walk_blocks(blocks)
            }
        )
    )

    return {
        "response_headers": response_headers,
        "models": models,
        "stop_reasons": stop_reasons,
        "text": text,
        "tool_use_names": tool_use_names,
        "attribution": attribution,
    }


# ─── format_complete_response behavior ────────────────────────────────────────


class TestFormatCompleteResponse:
    """Verify format_complete_response produces correct block content."""

    def test_text_response_produces_text_block(self):
        msg = _make_complete_message(text="Hello world")
        blocks = format_complete_response(msg)

        text_blocks = _find_blocks(blocks, TextContentBlock)
        assert len(text_blocks) == 1
        assert text_blocks[0].content == "Hello world"

    def test_includes_model_info(self):
        msg = _make_complete_message(model="claude-sonnet-4-5-20250929")
        blocks = format_complete_response(msg)

        info = _find_blocks(blocks, StreamInfoBlock)
        assert len(info) == 1
        assert info[0].model == "claude-sonnet-4-5-20250929"

    def test_includes_stop_reason(self):
        msg = _make_complete_message(stop_reason="tool_use")
        blocks = format_complete_response(msg)

        stops = _find_blocks(blocks, StopReasonBlock)
        assert len(stops) == 1
        assert stops[0].reason == "tool_use"

    def test_tool_use_produces_tool_block(self):
        content = [
            {"type": "text", "text": "Let me check that."},
            {"type": "tool_use", "id": "toolu_123", "name": "Read", "input": {"path": "foo.py"}},
        ]
        msg = _make_complete_message(content=content, stop_reason="tool_use")
        blocks = format_complete_response(msg)

        text_blocks = _find_blocks(blocks, TextContentBlock)
        tool_blocks = _find_blocks(blocks, StreamToolUseBlock)
        assert len(text_blocks) == 1
        assert text_blocks[0].content == "Let me check that."
        assert len(tool_blocks) == 1
        assert tool_blocks[0].name == "Read"

    def test_thinking_produces_thinking_block(self):
        content = [
            {"type": "thinking", "thinking": "Let me think..."},
            {"type": "text", "text": "Here's my answer."},
        ]
        msg = _make_complete_message(content=content)
        blocks = format_complete_response(msg)

        thinking = _find_blocks(blocks, ThinkingBlock)
        assert len(thinking) == 1
        assert thinking[0].content == "Let me think..."

    def test_empty_content_still_has_structure(self):
        """Even with no content blocks, we get model info and stop reason."""
        msg = _make_complete_message(content=[])
        blocks = format_complete_response(msg)

        assert len(_find_blocks(blocks, StreamInfoBlock)) == 1
        assert len(_find_blocks(blocks, StopReasonBlock)) == 1

    def test_unknown_content_type_skipped(self):
        content = [
            {"type": "text", "text": "Known"},
            {"type": "future_type", "data": "unknown"},
        ]
        msg = _make_complete_message(content=content)
        blocks = format_complete_response(msg)

        # Unknown type silently skipped, known type still present
        text_blocks = _find_blocks(blocks, TextContentBlock)
        assert len(text_blocks) == 1
        assert text_blocks[0].content == "Known"


# ─── Event handler behavior ──────────────────────────────────────────────────


class TestCompleteResponseEventHandler:
    """Verify canonical handle_response_complete adds turns to conversation."""

    def test_adds_turn_to_conversation(self):
        widgets = _mock_widgets()
        state = {"current_session": "sess_abc"}
        app_state = {}

        headers_event = ResponseHeadersEvent(
            status_code=200,
            headers={"content-type": "application/json"},
            request_id="req-1",
        )
        complete_event = ResponseCompleteEvent(
            body=_make_complete_message(text="Hello!"),
            request_id="req-1",
        )

        handle_response_headers(headers_event, state, widgets, app_state, lambda *a: None)
        handle_response_complete(complete_event, state, widgets, app_state, lambda *a: None)

        # Verify blocks were added to domain store
        ds = widgets["domain_store"]
        completed = ds.iter_completed_blocks()
        assert len(completed) == 1
        blocks = completed[0]
        assert len(blocks) > 0
        assert all(isinstance(b, FormattedBlock) for b in blocks)

    def test_response_blocks_contain_text_content(self):
        widgets = _mock_widgets()
        state = {}
        app_state = {}

        headers_event = ResponseHeadersEvent(
            status_code=200,
            headers={},
            request_id="req-1",
        )
        complete_event = ResponseCompleteEvent(
            body=_make_complete_message(text="Visible content here"),
            request_id="req-1",
        )

        handle_response_headers(headers_event, state, widgets, app_state, lambda *a: None)
        handle_response_complete(complete_event, state, widgets, app_state, lambda *a: None)

        ds = widgets["domain_store"]
        blocks = ds.iter_completed_blocks()[0]
        text_blocks = _find_blocks(blocks, TextContentBlock)
        assert any("Visible content" in b.content for b in text_blocks)

    def test_non_streaming_transport_normalizes_to_complete_path(self):
        widgets = _mock_widgets()
        state = {"current_session": "sess_abc"}
        app_state = {}

        event = ResponseNonStreamingEvent(
            status_code=200,
            headers={"content-type": "application/json"},
            body=_make_complete_message(text="Hello via wrapper"),
            request_id="req-legacy",
        )
        handle_response_non_streaming(event, state, widgets, app_state, lambda *a: None)

        ds = widgets["domain_store"]
        completed = ds.iter_completed_blocks()
        assert len(completed) == 1
        text_blocks = _find_blocks(completed[0], TextContentBlock)
        assert any("Hello via wrapper" in b.content for b in text_blocks)


# ─── Session detection through request pipeline ──────────────────────────────


class TestSessionDetectionViaRequest:
    """Verify session_id is captured in formatting state from request body."""

    def test_session_id_extracted_from_user_id(self):
        state = {
            "request_counter": 0,
            "positions": {},
            "known_hashes": {},
            "next_id": 1,
            "next_color": 0,
        }
        body = {
            "model": "claude-3-opus-20240229",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": "Hello"}],
            "metadata": {
                "user_id": "user_abc123def_account_11111111-2222-3333-4444-555555555555_session_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            },
        }

        format_request(body, state)

        assert state["current_session"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    def test_no_metadata_leaves_session_unset(self):
        state = {
            "request_counter": 0,
            "positions": {},
            "known_hashes": {},
            "next_id": 1,
            "next_color": 0,
        }
        body = {
            "model": "claude-3-opus-20240229",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": "Hello"}],
        }

        format_request(body, state)

        assert "current_session" not in state


# ─── End-to-end: HAR → events → blocks ───────────────────────────────────────


class TestReplayEndToEnd:
    """Verify the full replay pipeline: HAR file → load → convert → handle."""

    def test_replay_produces_visible_turns(self, tmp_path):
        """Loading and replaying a HAR file produces turns with text content."""
        har = _make_har([
            (
                {"model": "claude-3-opus-20240229", "max_tokens": 4096,
                 "messages": [{"role": "user", "content": "What is 2+2?"}]},
                _make_complete_message(text="2+2 = 4"),
            ),
        ])
        har_path = tmp_path / "test.har"
        with open(har_path, "w") as f:
            json.dump(har, f)

        # Load and convert
        pairs = load_har(str(har_path))
        events = convert_to_events(*pairs[0])

        # Feed through handlers
        widgets = _mock_widgets()
        state = {"request_counter": 0, "positions": {}, "known_hashes": {},
                 "next_id": 1, "next_color": 0}
        app_state = {}

        for event in events:
            kind = event.kind
            if kind == PipelineEventKind.REQUEST:
                app_state = handle_request(event, state, widgets, app_state, lambda *a: None)
            elif kind == PipelineEventKind.RESPONSE_HEADERS:
                app_state = handle_response_headers(event, state, widgets, app_state, lambda *a: None)
            elif kind == PipelineEventKind.RESPONSE_COMPLETE:
                app_state = handle_response_complete(event, state, widgets, app_state, lambda *a: None)

        # domain_store should have 2 completed turns (request + response)
        ds = widgets["domain_store"]
        assert ds.completed_count == 2

        # Response turn should contain the answer text
        response_blocks = ds.iter_completed_blocks()[1]
        text_blocks = _find_blocks(response_blocks, TextContentBlock)
        assert any("2+2 = 4" in b.content for b in text_blocks)

    def test_replay_captures_session_id(self, tmp_path):
        """Session ID from request metadata is available after replay."""
        session_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        har = _make_har([
            (
                {
                    "model": "claude-3-opus-20240229",
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": "Hello"}],
                    "metadata": {
                        "user_id": f"user_abc123def_account_11111111-2222-3333-4444-555555555555_session_{session_uuid}"
                    },
                },
                _make_complete_message(text="Hi"),
            ),
        ])
        har_path = tmp_path / "test.har"
        with open(har_path, "w") as f:
            json.dump(har, f)

        pairs = load_har(str(har_path))
        events = convert_to_events(*pairs[0])

        widgets = _mock_widgets()
        state = {"request_counter": 0, "positions": {}, "known_hashes": {},
                 "next_id": 1, "next_color": 0}
        app_state = {}

        for event in events:
            kind = event.kind
            if kind == PipelineEventKind.REQUEST:
                app_state = handle_request(event, state, widgets, app_state, lambda *a: None)
            elif kind == PipelineEventKind.RESPONSE_HEADERS:
                app_state = handle_response_headers(event, state, widgets, app_state, lambda *a: None)
            elif kind == PipelineEventKind.RESPONSE_COMPLETE:
                app_state = handle_response_complete(event, state, widgets, app_state, lambda *a: None)

        assert state["current_session"] == session_uuid
        ds = widgets["domain_store"]
        response_blocks = ds.iter_completed_blocks()[1]
        assert len(response_blocks) > 0

    def test_multi_turn_replay(self, tmp_path):
        """Multiple HAR entries produce multiple turns."""
        har = _make_har([
            (
                {"model": "claude-3-opus-20240229", "max_tokens": 4096,
                 "messages": [{"role": "user", "content": "Turn 1"}]},
                _make_complete_message(text="Response 1", msg_id="msg_1"),
            ),
            (
                {"model": "claude-3-opus-20240229", "max_tokens": 4096,
                 "messages": [{"role": "user", "content": "Turn 2"}]},
                _make_complete_message(text="Response 2", msg_id="msg_2"),
            ),
        ])
        har_path = tmp_path / "test.har"
        with open(har_path, "w") as f:
            json.dump(har, f)

        pairs = load_har(str(har_path))
        assert len(pairs) == 2

        widgets = _mock_widgets()
        state = {"request_counter": 0, "positions": {}, "known_hashes": {},
                 "next_id": 1, "next_color": 0}
        app_state = {}

        for pair in pairs:
            events = convert_to_events(*pair)
            for event in events:
                kind = event.kind
                if kind == PipelineEventKind.REQUEST:
                    app_state = handle_request(event, state, widgets, app_state, lambda *a: None)
                elif kind == PipelineEventKind.RESPONSE_HEADERS:
                    app_state = handle_response_headers(event, state, widgets, app_state, lambda *a: None)
                elif kind == PipelineEventKind.RESPONSE_COMPLETE:
                    app_state = handle_response_complete(event, state, widgets, app_state, lambda *a: None)

        # 2 request turns + 2 response turns = 4 completed turns
        ds = widgets["domain_store"]
        assert ds.completed_count == 4


class TestLiveReplayParityContracts:
    def test_live_sse_assembly_matches_har_replay_projection(self):
        session_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        request_headers = {"content-type": "application/json", "x-contract": "parity"}
        request_body = {
            "model": "claude-sonnet-4-5-20250929",
            "stream": True,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "run parity"}]}],
            "metadata": {
                "user_id": (
                    "user_deadbeef_account_11111111-2222-3333-4444-555555555555_"
                    f"session_{session_uuid}"
                )
            },
        }
        response_headers = {"content-type": "application/json"}
        raw_sse_events = [
            {
                "type": "message_start",
                "message": {
                    "id": "msg_live",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-4-5-20250929",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 11, "output_tokens": 0},
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "live parity output"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "tool_use", "id": "toolu_1", "name": "Read"},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": "{\"path\":\"README.md\"}"},
            },
            {"type": "content_block_stop", "index": 1},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": ""},
                "usage": {"output_tokens": 17},
            },
            {"type": "message_stop"},
        ]

        # // [LAW:one-source-of-truth] Live parity uses the same assembler boundary as proxy.
        assembler = ResponseAssembler()
        live_events = [
            RequestHeadersEvent(
                headers=request_headers,
                request_id="req-live",
                seq=0,
                recv_ns=1,
            ),
            RequestBodyEvent(body=request_body, request_id="req-live", seq=1, recv_ns=2),
            ResponseHeadersEvent(
                status_code=200,
                headers=response_headers,
                request_id="req-live",
                seq=2,
                recv_ns=3,
            ),
        ]
        seq = 2
        recv_ns = 3
        for raw in raw_sse_events:
            event_type = str(raw.get("type", ""))
            assembler.on_event(event_type, raw)
            seq += 1
            recv_ns += 1
            live_events.append(
                ResponseSSEEvent(
                    sse_event=parse_sse_event(event_type, raw),
                    request_id="req-live",
                    seq=seq,
                    recv_ns=recv_ns,
                )
            )
        assembler.on_done()
        assert assembler.result is not None

        seq += 1
        recv_ns += 1
        live_events.append(
            ResponseCompleteEvent(
                body=dict(assembler.result),
                request_id="req-live",
                seq=seq,
                recv_ns=recv_ns,
            )
        )

        replay_events = convert_to_events(
            request_headers,
            request_body,
            200,
            response_headers,
            dict(assembler.result),
        )

        live_state, live_widgets, _ = _run_pipeline_events(live_events)
        replay_state, replay_widgets, _ = _run_pipeline_events(replay_events)

        live_ds = live_widgets["domain_store"]
        replay_ds = replay_widgets["domain_store"]
        assert live_ds.completed_count == 2
        assert replay_ds.completed_count == 2
        assert live_state["current_session"] == session_uuid
        assert replay_state["current_session"] == session_uuid

        live_projection = _project_response_turn(live_ds.iter_completed_blocks()[1])
        replay_projection = _project_response_turn(replay_ds.iter_completed_blocks()[1])
        assert live_projection == replay_projection
