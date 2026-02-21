"""Behavioral tests for the replay pipeline.

Tests that replay (non-streaming) data flows through the same pipeline as live
data and produces visible, correct content — without asserting on internal
event types or implementation structure.
"""

import json
import pytest
from unittest.mock import MagicMock

from cc_dump.domain_store import DomainStore

from cc_dump.formatting import (
    FormattedBlock,
    StreamInfoBlock,
    StopReasonBlock,
    TextContentBlock,
    StreamToolUseBlock,
    ThinkingBlock,
    format_complete_response,
    format_request,
    format_response_headers,
)
from cc_dump.har_replayer import load_har, convert_to_events
from cc_dump.tui.event_handlers import (
    handle_request,
    handle_response_non_streaming,
)
from cc_dump.event_types import (
    RequestBodyEvent,
    ResponseNonStreamingEvent,
    PipelineEventKind,
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


class TestNonStreamingEventHandler:
    """Verify handle_response_non_streaming adds turns to conversation."""

    def test_adds_turn_to_conversation(self):
        widgets = _mock_widgets()
        state = {"current_session": "sess_abc"}
        app_state = {}

        event = ResponseNonStreamingEvent(
            status_code=200,
            headers={"content-type": "application/json"},
            body=_make_complete_message(text="Hello!"),
        )

        handle_response_non_streaming(event, state, widgets, app_state, lambda *a: None)

        # Verify blocks were added to domain store
        ds = widgets["domain_store"]
        completed = ds.iter_completed_blocks()
        assert len(completed) == 1
        blocks = completed[0]
        assert len(blocks) > 0
        assert all(isinstance(b, FormattedBlock) for b in blocks)

    def test_stamps_session_id_on_blocks(self):
        widgets = _mock_widgets()
        state = {"current_session": "sess_xyz"}
        app_state = {}

        event = ResponseNonStreamingEvent(
            status_code=200,
            headers={},
            body=_make_complete_message(),
        )

        handle_response_non_streaming(event, state, widgets, app_state, lambda *a: None)

        ds = widgets["domain_store"]
        blocks = ds.iter_completed_blocks()[0]
        for block in blocks:
            assert block.session_id == "sess_xyz"

    def test_response_blocks_contain_text_content(self):
        widgets = _mock_widgets()
        state = {}
        app_state = {}

        event = ResponseNonStreamingEvent(
            status_code=200,
            headers={},
            body=_make_complete_message(text="Visible content here"),
        )

        handle_response_non_streaming(event, state, widgets, app_state, lambda *a: None)

        ds = widgets["domain_store"]
        blocks = ds.iter_completed_blocks()[0]
        text_blocks = _find_blocks(blocks, TextContentBlock)
        assert any("Visible content" in b.content for b in text_blocks)


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
            elif kind == PipelineEventKind.RESPONSE_NON_STREAMING:
                app_state = handle_response_non_streaming(
                    event, state, widgets, app_state, lambda *a: None
                )

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
            elif kind == PipelineEventKind.RESPONSE_NON_STREAMING:
                app_state = handle_response_non_streaming(
                    event, state, widgets, app_state, lambda *a: None
                )

        assert state["current_session"] == session_uuid
        # Response blocks are lane-attributed from in-band session metadata.
        ds = widgets["domain_store"]
        response_blocks = ds.iter_completed_blocks()[1]
        assert all(getattr(block, "agent_kind", "") in {"main", "subagent", "unknown"} for block in response_blocks)

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
                elif kind == PipelineEventKind.RESPONSE_NON_STREAMING:
                    app_state = handle_response_non_streaming(
                        event, state, widgets, app_state, lambda *a: None
                    )

        # 2 request turns + 2 response turns = 4 completed turns
        ds = widgets["domain_store"]
        assert ds.completed_count == 4
