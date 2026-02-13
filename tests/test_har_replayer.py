"""Unit tests for har_replayer.py - HAR loading and event reconstruction."""

import json
import pytest

from cc_dump.har_replayer import load_har, convert_to_events
from cc_dump.event_types import (
    RequestHeadersEvent,
    RequestBodyEvent,
    ResponseHeadersEvent,
    ResponseSSEEvent,
    ResponseDoneEvent,
    MessageStartEvent,
    MessageDeltaEvent,
    MessageStopEvent,
    TextBlockStartEvent,
    ToolUseBlockStartEvent,
    TextDeltaEvent,
    InputJsonDeltaEvent,
    ContentBlockStopEvent,
    StopReason,
)


# ─── HAR Loading Tests ────────────────────────────────────────────────────────


def test_load_har_basic(tmp_path):
    """Load basic HAR file with single entry."""
    har_path = tmp_path / "test.har"
    har = {
        "log": {
            "version": "1.2",
            "creator": {"name": "cc-dump", "version": "0.2.0"},
            "entries": [
                {
                    "startedDateTime": "2024-01-01T00:00:00Z",
                    "time": 1234.5,
                    "request": {
                        "method": "POST",
                        "url": "https://api.anthropic.com/v1/messages",
                        "headers": [
                            {"name": "content-type", "value": "application/json"},
                        ],
                        "postData": {
                            "mimeType": "application/json",
                            "text": json.dumps({
                                "model": "claude-3-opus-20240229",
                                "messages": [{"role": "user", "content": "Hello"}],
                            }),
                        },
                    },
                    "response": {
                        "status": 200,
                        "headers": [
                            {"name": "content-type", "value": "application/json"},
                        ],
                        "content": {
                            "mimeType": "application/json",
                            "text": json.dumps({
                                "id": "msg_123",
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "text", "text": "Hello!"}],
                                "model": "claude-3-opus-20240229",
                                "usage": {"input_tokens": 10, "output_tokens": 5},
                            }),
                        },
                    },
                }
            ],
        }
    }

    with open(har_path, "w") as f:
        json.dump(har, f)

    pairs = load_har(str(har_path))

    assert len(pairs) == 1
    req_headers, req_body, resp_status, resp_headers, complete_message = pairs[0]

    # Verify request
    assert "content-type" in req_headers
    assert req_body["model"] == "claude-3-opus-20240229"

    # Verify response
    assert resp_status == 200
    assert "content-type" in resp_headers
    assert complete_message["id"] == "msg_123"
    assert complete_message["type"] == "message"


def test_load_har_multiple_entries(tmp_path):
    """Load HAR with multiple entries."""
    har_path = tmp_path / "test.har"
    har = {
        "log": {
            "version": "1.2",
            "entries": [
                {
                    "request": {
                        "method": "POST",
                        "url": "https://api.anthropic.com/v1/messages",
                        "headers": [],
                        "postData": {
                            "text": json.dumps({"model": "claude-3-opus-20240229"}),
                        },
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "text": json.dumps({
                                "id": "msg_1",
                                "type": "message",
                                "content": [],
                                "usage": {},
                            }),
                        },
                    },
                },
                {
                    "request": {
                        "method": "POST",
                        "url": "https://api.anthropic.com/v1/messages",
                        "headers": [],
                        "postData": {
                            "text": json.dumps({"model": "claude-3-opus-20240229"}),
                        },
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "text": json.dumps({
                                "id": "msg_2",
                                "type": "message",
                                "content": [],
                                "usage": {},
                            }),
                        },
                    },
                },
            ],
        }
    }

    with open(har_path, "w") as f:
        json.dump(har, f)

    pairs = load_har(str(har_path))

    assert len(pairs) == 2
    assert pairs[0][4]["id"] == "msg_1"
    assert pairs[1][4]["id"] == "msg_2"


@pytest.mark.parametrize(
    "har_dict,error_match",
    [
        pytest.param(
            {"invalid": "structure"},
            "missing 'log' key",
            id="missing_log",
        ),
        pytest.param(
            {"log": {"version": "1.2"}},
            "missing 'log.entries' key",
            id="missing_entries",
        ),
        pytest.param(
            {"log": {"entries": "not a list"}},
            "log.entries must be a list",
            id="entries_not_list",
        ),
    ],
)
def test_load_har_invalid_structure(tmp_path, har_dict, error_match):
    """Test various invalid HAR structure errors."""
    har_path = tmp_path / "test.har"

    with open(har_path, "w") as f:
        json.dump(har_dict, f)

    with pytest.raises(ValueError, match=error_match):
        load_har(str(har_path))


def test_load_har_empty_entries(tmp_path):
    """HAR with no entries raises error."""
    har_path = tmp_path / "test.har"
    har = {"log": {"entries": []}}

    with open(har_path, "w") as f:
        json.dump(har, f)

    with pytest.raises(ValueError, match="no valid entries"):
        load_har(str(har_path))


def test_load_har_malformed_entry_skipped(tmp_path, capsys):
    """Malformed entries are skipped with warning."""
    har_path = tmp_path / "test.har"
    har = {
        "log": {
            "entries": [
                # Valid entry
                {
                    "request": {
                        "headers": [],
                        "postData": {"text": json.dumps({"model": "test"})},
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "text": json.dumps({
                                "id": "msg_valid",
                                "type": "message",
                                "content": [],
                                "usage": {},
                            }),
                        },
                    },
                },
                # Invalid entry (missing request)
                {
                    "response": {
                        "content": {"text": "{}"},
                    },
                },
            ],
        }
    }

    with open(har_path, "w") as f:
        json.dump(har, f)

    pairs = load_har(str(har_path))

    # Should have one valid entry
    assert len(pairs) == 1
    assert pairs[0][4]["id"] == "msg_valid"

    # Check stderr for warning
    captured = capsys.readouterr()
    assert "skipping entry 1" in captured.err


def test_load_har_file_not_found():
    """FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError):
        load_har("/nonexistent/path.har")


def test_load_har_invalid_json(tmp_path):
    """JSONDecodeError for invalid JSON."""
    har_path = tmp_path / "test.har"
    with open(har_path, "w") as f:
        f.write("{invalid json")

    with pytest.raises(json.JSONDecodeError):
        load_har(str(har_path))


def test_load_har_response_not_complete_message(tmp_path, capsys):
    """Response that's not a complete message is skipped."""
    har_path = tmp_path / "test.har"
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "headers": [],
                        "postData": {"text": json.dumps({"model": "test"})},
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            # Invalid: not a complete message
                            "text": json.dumps({"type": "error", "error": "something"}),
                        },
                    },
                },
            ],
        }
    }

    with open(har_path, "w") as f:
        json.dump(har, f)

    with pytest.raises(ValueError, match="no valid entries"):
        load_har(str(har_path))


# ─── Event Conversion Tests ───────────────────────────────────────────────────


def test_convert_to_events_simple_text():
    """Convert simple text message to events."""
    req_headers = {"content-type": "application/json"}
    req_body = {
        "model": "claude-3-opus-20240229",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    resp_status = 200
    resp_headers = {"content-type": "application/json"}
    complete_message = {
        "id": "msg_123",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "Hello world"}],
        "model": "claude-3-opus-20240229",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    events = convert_to_events(req_headers, req_body, resp_status, resp_headers, complete_message)

    # Verify event sequence
    assert isinstance(events[0], RequestHeadersEvent)
    assert events[0].headers == req_headers
    assert isinstance(events[1], RequestBodyEvent)
    assert events[1].body == req_body
    assert isinstance(events[2], ResponseHeadersEvent)
    assert events[2].status_code == resp_status

    # message_start
    assert isinstance(events[3], ResponseSSEEvent)
    assert isinstance(events[3].sse_event, MessageStartEvent)
    assert events[3].sse_event.message.id == "msg_123"
    assert events[3].sse_event.message.usage.output_tokens == 0  # Should be 0 in message_start

    # content_block_start
    assert isinstance(events[4], ResponseSSEEvent)
    assert isinstance(events[4].sse_event, TextBlockStartEvent)

    # content_block_delta
    assert isinstance(events[5], ResponseSSEEvent)
    assert isinstance(events[5].sse_event, TextDeltaEvent)
    assert events[5].sse_event.text == "Hello world"

    # content_block_stop
    assert isinstance(events[6], ResponseSSEEvent)
    assert isinstance(events[6].sse_event, ContentBlockStopEvent)

    # message_delta
    assert isinstance(events[7], ResponseSSEEvent)
    assert isinstance(events[7].sse_event, MessageDeltaEvent)
    assert events[7].sse_event.stop_reason == StopReason.END_TURN
    assert events[7].sse_event.output_tokens == 5

    # message_stop
    assert isinstance(events[8], ResponseSSEEvent)
    assert isinstance(events[8].sse_event, MessageStopEvent)

    # response_done
    assert isinstance(events[9], ResponseDoneEvent)


def test_convert_to_events_tool_use():
    """Convert message with tool use to events."""
    complete_message = {
        "id": "msg_456",
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_abc",
                "name": "read_file",
                "input": {"path": "test.py"},
            }
        ],
        "model": "claude-3-opus-20240229",
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }

    events = convert_to_events({}, {}, 200, {}, complete_message)

    # Find tool_use events
    tool_start = None
    tool_delta = None
    tool_stop = None

    for event in events:
        if isinstance(event, ResponseSSEEvent):
            sse = event.sse_event
            if isinstance(sse, ToolUseBlockStartEvent):
                tool_start = sse
            elif isinstance(sse, InputJsonDeltaEvent):
                tool_delta = sse
            elif isinstance(sse, ContentBlockStopEvent):
                tool_stop = sse

    assert tool_start is not None
    assert tool_start.id == "toolu_abc"
    assert tool_start.name == "read_file"

    assert tool_delta is not None
    # Input should be complete JSON in a single delta
    assert json.loads(tool_delta.partial_json) == {"path": "test.py"}

    assert tool_stop is not None


def test_convert_to_events_mixed_content():
    """Convert message with text and tool use to events."""
    complete_message = {
        "id": "msg_789",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Let me read that file."},
            {
                "type": "tool_use",
                "id": "toolu_xyz",
                "name": "read_file",
                "input": {"path": "data.json"},
            },
        ],
        "model": "claude-3-opus-20240229",
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 50, "output_tokens": 30},
    }

    events = convert_to_events({}, {}, 200, {}, complete_message)

    # Count content block starts
    block_starts = [
        e for e in events
        if isinstance(e, ResponseSSEEvent) and isinstance(e.sse_event, (TextBlockStartEvent, ToolUseBlockStartEvent))
    ]

    assert len(block_starts) == 2
    assert isinstance(block_starts[0].sse_event, TextBlockStartEvent)
    assert isinstance(block_starts[1].sse_event, ToolUseBlockStartEvent)


def test_convert_to_events_empty_content():
    """Convert message with empty content."""
    complete_message = {
        "id": "msg_empty",
        "type": "message",
        "role": "assistant",
        "content": [],
        "model": "claude-3-opus-20240229",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 5, "output_tokens": 0},
    }

    events = convert_to_events({}, {}, 200, {}, complete_message)

    # Should still have request/response/message_start/message_delta/message_stop/response_done
    assert len(events) >= 6

    # No content blocks
    content_blocks = [
        e for e in events
        if isinstance(e, ResponseSSEEvent) and isinstance(e.sse_event, (TextBlockStartEvent, ToolUseBlockStartEvent))
    ]
    assert len(content_blocks) == 0


def test_convert_to_events_unicode():
    """Convert message with unicode content."""
    complete_message = {
        "id": "msg_unicode",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "Hello \U0001f44b \u4e16\u754c"}],
        "model": "claude-3-opus-20240229",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 5, "output_tokens": 8},
    }

    events = convert_to_events({}, {}, 200, {}, complete_message)

    # Find text delta
    text_delta = None
    for event in events:
        if isinstance(event, ResponseSSEEvent) and isinstance(event.sse_event, TextDeltaEvent):
            text_delta = event.sse_event.text
            break

    assert text_delta == "Hello \U0001f44b \u4e16\u754c"


def test_convert_to_events_no_stop_reason():
    """Convert message without stop_reason (shouldn't happen, but handle gracefully)."""
    complete_message = {
        "id": "msg_nostop",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "Test"}],
        "model": "claude-3-opus-20240229",
        "usage": {"input_tokens": 5, "output_tokens": 3},
    }

    events = convert_to_events({}, {}, 200, {}, complete_message)

    # Should still generate message_delta event
    message_delta = None
    for event in events:
        if isinstance(event, ResponseSSEEvent) and isinstance(event.sse_event, MessageDeltaEvent):
            message_delta = event.sse_event
            break

    assert message_delta is not None
    # stop_reason should be NONE (empty sentinel)
    assert message_delta.stop_reason == StopReason.NONE


def test_convert_to_events_empty_text():
    """Convert text block with empty text."""
    complete_message = {
        "id": "msg_empty_text",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": ""}],
        "model": "claude-3-opus-20240229",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 5, "output_tokens": 0},
    }

    events = convert_to_events({}, {}, 200, {}, complete_message)

    # Should still have content_block_start and stop, but no delta
    content_deltas = [
        e for e in events
        if isinstance(e, ResponseSSEEvent) and isinstance(e.sse_event, (TextDeltaEvent, InputJsonDeltaEvent))
    ]
    assert len(content_deltas) == 0


def test_convert_to_events_unknown_block_type(capsys):
    """Unknown content block type is skipped with warning."""
    complete_message = {
        "id": "msg_unknown",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "unknown_type", "data": "something"}],
        "model": "claude-3-opus-20240229",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 5, "output_tokens": 3},
    }

    events = convert_to_events({}, {}, 200, {}, complete_message)

    # Should not crash
    assert len(events) > 0

    # Check for warning in stderr
    captured = capsys.readouterr()
    assert "unknown content block type" in captured.err


def test_convert_to_events_large_tool_input():
    """Convert tool use with large input."""
    large_input = {"data": "A" * 10000}  # 10KB of data
    complete_message = {
        "id": "msg_large",
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_large",
                "name": "test_tool",
                "input": large_input,
            }
        ],
        "model": "claude-3-opus-20240229",
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 100, "output_tokens": 2500},
    }

    events = convert_to_events({}, {}, 200, {}, complete_message)

    # Find tool delta
    tool_delta = None
    for event in events:
        if isinstance(event, ResponseSSEEvent) and isinstance(event.sse_event, InputJsonDeltaEvent):
            tool_delta = event.sse_event.partial_json
            break

    assert tool_delta is not None
    # Should be able to parse back to original input
    assert json.loads(tool_delta) == large_input


def test_convert_to_events_multiple_text_blocks():
    """Convert message with multiple text blocks."""
    complete_message = {
        "id": "msg_multi",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "text", "text": "First block"},
            {"type": "text", "text": "Second block"},
            {"type": "text", "text": "Third block"},
        ],
        "model": "claude-3-opus-20240229",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 15},
    }

    events = convert_to_events({}, {}, 200, {}, complete_message)

    # Count content block starts
    content_block_starts = [
        e for e in events
        if isinstance(e, ResponseSSEEvent) and isinstance(e.sse_event, TextBlockStartEvent)
    ]

    assert len(content_block_starts) == 3

    # Verify each block has correct index
    for i, event in enumerate(content_block_starts):
        assert event.sse_event.index == i


# ─── Integration Tests ────────────────────────────────────────────────────────


def test_roundtrip_har_load_and_convert(tmp_path):
    """Load HAR and convert to events (full pipeline)."""
    har_path = tmp_path / "test.har"
    har = {
        "log": {
            "version": "1.2",
            "entries": [
                {
                    "request": {
                        "method": "POST",
                        "headers": [{"name": "content-type", "value": "application/json"}],
                        "postData": {
                            "text": json.dumps({
                                "model": "claude-3-opus-20240229",
                                "messages": [{"role": "user", "content": "Test"}],
                            }),
                        },
                    },
                    "response": {
                        "status": 200,
                        "headers": [{"name": "content-type", "value": "application/json"}],
                        "content": {
                            "text": json.dumps({
                                "id": "msg_test",
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "text", "text": "Response"}],
                                "model": "claude-3-opus-20240229",
                                "stop_reason": "end_turn",
                                "usage": {"input_tokens": 10, "output_tokens": 5},
                            }),
                        },
                    },
                }
            ],
        }
    }

    with open(har_path, "w") as f:
        json.dump(har, f)

    # Load HAR
    pairs = load_har(str(har_path))
    assert len(pairs) == 1

    # Convert to events
    events = convert_to_events(*pairs[0])

    # Verify event structure matches typed pipeline events
    assert isinstance(events[0], RequestHeadersEvent)
    assert isinstance(events[1], RequestBodyEvent)
    assert isinstance(events[2], ResponseHeadersEvent)
    assert isinstance(events[-1], ResponseDoneEvent)

    # All response SSE events should be ResponseSSEEvent wrapping an SSEEvent
    response_events = [e for e in events if isinstance(e, ResponseSSEEvent)]
    for event in response_events:
        from cc_dump.event_types import SSEEvent
        assert isinstance(event.sse_event, SSEEvent)
