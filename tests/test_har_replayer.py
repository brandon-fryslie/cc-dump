"""Unit tests for har_replayer.py - HAR loading and event reconstruction."""

import json
import pytest

from cc_dump.har_replayer import load_har, convert_to_events
from cc_dump.event_types import (
    RequestHeadersEvent,
    RequestBodyEvent,
    ResponseCompleteEvent,
    ResponseNonStreamingEvent,
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


def test_convert_to_events_produces_four_events():
    """convert_to_events produces request headers, request body, non-streaming response, and complete event."""
    req_headers = {"content-type": "application/json"}
    req_body = {"model": "claude-3-opus-20240229", "messages": [{"role": "user", "content": "Hello"}]}
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

    assert len(events) == 4
    assert isinstance(events[0], RequestHeadersEvent)
    assert events[0].headers == req_headers
    assert isinstance(events[1], RequestBodyEvent)
    assert events[1].body == req_body
    assert isinstance(events[2], ResponseNonStreamingEvent)
    assert events[2].status_code == resp_status
    assert events[2].headers == resp_headers
    assert events[2].body == complete_message
    assert isinstance(events[3], ResponseCompleteEvent)
    assert events[3].body == complete_message


def test_convert_to_events_preserves_body_exactly():
    """Response body is passed through without transformation."""
    complete_message = {
        "id": "msg_456",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Hello \U0001f44b \u4e16\u754c"},
            {"type": "tool_use", "id": "toolu_abc", "name": "read_file", "input": {"path": "test.py"}},
            {"type": "unknown_type", "data": "something"},
        ],
        "model": "claude-3-opus-20240229",
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }

    events = convert_to_events({}, {}, 200, {}, complete_message)

    assert events[2].body is complete_message
    assert events[3].body is complete_message


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

    # Verify event structure
    assert len(events) == 4
    assert isinstance(events[0], RequestHeadersEvent)
    assert isinstance(events[1], RequestBodyEvent)
    assert isinstance(events[2], ResponseNonStreamingEvent)
    assert isinstance(events[3], ResponseCompleteEvent)
    assert events[2].body["id"] == "msg_test"
    assert events[3].body["id"] == "msg_test"
