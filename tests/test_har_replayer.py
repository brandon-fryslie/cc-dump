"""Unit tests for har_replayer.py - HAR loading and event reconstruction."""

import json
import pytest

from cc_dump.har_replayer import load_har, convert_to_events


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
    assert events[0] == ("request_headers", req_headers)
    assert events[1] == ("request", req_body)
    assert events[2] == ("response_headers", resp_status, resp_headers)

    # message_start
    assert events[3][0] == "response_event"
    assert events[3][1] == "message_start"
    assert events[3][2]["message"]["id"] == "msg_123"
    assert events[3][2]["message"]["usage"]["output_tokens"] == 0  # Should be 0 in message_start

    # content_block_start
    assert events[4][0] == "response_event"
    assert events[4][1] == "content_block_start"
    assert events[4][2]["content_block"]["type"] == "text"

    # content_block_delta
    assert events[5][0] == "response_event"
    assert events[5][1] == "content_block_delta"
    assert events[5][2]["delta"]["type"] == "text_delta"
    assert events[5][2]["delta"]["text"] == "Hello world"

    # content_block_stop
    assert events[6][0] == "response_event"
    assert events[6][1] == "content_block_stop"

    # message_delta
    assert events[7][0] == "response_event"
    assert events[7][1] == "message_delta"
    assert events[7][2]["delta"]["stop_reason"] == "end_turn"
    assert events[7][2]["usage"]["output_tokens"] == 5

    # message_stop
    assert events[8][0] == "response_event"
    assert events[8][1] == "message_stop"

    # response_done
    assert events[9] == ("response_done",)


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
        if event[0] == "response_event":
            if event[1] == "content_block_start":
                if event[2]["content_block"]["type"] == "tool_use":
                    tool_start = event[2]
            elif event[1] == "content_block_delta":
                if event[2]["delta"]["type"] == "input_json_delta":
                    tool_delta = event[2]
            elif event[1] == "content_block_stop":
                tool_stop = event[2]

    assert tool_start is not None
    assert tool_start["content_block"]["id"] == "toolu_abc"
    assert tool_start["content_block"]["name"] == "read_file"

    assert tool_delta is not None
    # Input should be complete JSON in a single delta
    assert json.loads(tool_delta["delta"]["partial_json"]) == {"path": "test.py"}

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

    # Count content blocks
    content_block_starts = [
        e for e in events if e[0] == "response_event" and e[1] == "content_block_start"
    ]

    assert len(content_block_starts) == 2
    assert content_block_starts[0][2]["content_block"]["type"] == "text"
    assert content_block_starts[1][2]["content_block"]["type"] == "tool_use"


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
        e for e in events if e[0] == "response_event" and e[1] == "content_block_start"
    ]
    assert len(content_blocks) == 0


def test_convert_to_events_unicode():
    """Convert message with unicode content."""
    complete_message = {
        "id": "msg_unicode",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "Hello 👋 世界"}],
        "model": "claude-3-opus-20240229",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 5, "output_tokens": 8},
    }

    events = convert_to_events({}, {}, 200, {}, complete_message)

    # Find text delta
    text_delta = None
    for event in events:
        if (
            event[0] == "response_event"
            and event[1] == "content_block_delta"
            and event[2]["delta"]["type"] == "text_delta"
        ):
            text_delta = event[2]["delta"]["text"]
            break

    assert text_delta == "Hello 👋 世界"


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
        if event[0] == "response_event" and event[1] == "message_delta":
            message_delta = event[2]
            break

    assert message_delta is not None
    # stop_reason should not be in delta if not in message
    assert "stop_reason" not in message_delta["delta"]


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
        e for e in events if e[0] == "response_event" and e[1] == "content_block_delta"
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
        if (
            event[0] == "response_event"
            and event[1] == "content_block_delta"
            and event[2]["delta"]["type"] == "input_json_delta"
        ):
            tool_delta = event[2]["delta"]["partial_json"]
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

    # Count content blocks
    content_block_starts = [
        e for e in events if e[0] == "response_event" and e[1] == "content_block_start"
    ]

    assert len(content_block_starts) == 3

    # Verify each block has correct index
    for i, event in enumerate(content_block_starts):
        assert event[2]["index"] == i


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

    # Verify event structure matches what formatting.py expects
    assert events[0][0] == "request_headers"
    assert events[1][0] == "request"
    assert events[2][0] == "response_headers"
    assert events[-1] == ("response_done",)

    # All response events should be ("response_event", event_type, event_data)
    response_events = [e for e in events if e[0] == "response_event"]
    for event in response_events:
        assert len(event) == 3
        assert isinstance(event[1], str)  # event_type
        assert isinstance(event[2], dict)  # event_data
