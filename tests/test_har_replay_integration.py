"""Integration tests for HAR replay with formatting pipeline."""

import json
import pytest

from cc_dump.har_replayer import load_har, convert_to_events
from cc_dump.formatting import format_request, format_response_event


def test_replay_events_through_formatting(tmp_path, fresh_state):
    """Verify that replayed events can be processed by formatting.py."""
    # Create a HAR file with a simple conversation
    har_path = tmp_path / "test.har"
    har = {
        "log": {
            "version": "1.2",
            "entries": [
                {
                    "request": {
                        "method": "POST",
                        "headers": [],
                        "postData": {
                            "text": json.dumps({
                                "model": "claude-3-opus-20240229",
                                "max_tokens": 1024,
                                "messages": [{"role": "user", "content": "Hello Claude"}],
                                "system": "You are a helpful assistant.",
                            }),
                        },
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "text": json.dumps({
                                "id": "msg_test123",
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "text", "text": "Hello! How can I help you today?"}],
                                "model": "claude-3-opus-20240229",
                                "stop_reason": "end_turn",
                                "usage": {"input_tokens": 25, "output_tokens": 12},
                            }),
                        },
                    },
                }
            ],
        }
    }

    with open(har_path, "w") as f:
        json.dump(har, f)

    # Load and convert
    pairs = load_har(str(har_path))
    events = convert_to_events(*pairs[0])

    # Process events through formatting pipeline
    all_blocks = []

    for event in events:
        kind = event[0]

        if kind == "request":
            blocks = format_request(event[1], fresh_state)
            all_blocks.extend(blocks)
        elif kind == "response_event":
            event_type, event_data = event[1], event[2]
            blocks = format_response_event(event_type, event_data)
            all_blocks.extend(blocks)

    # Verify we got blocks
    assert len(all_blocks) > 0

    # Verify request was formatted
    assert fresh_state["request_counter"] == 1

    # Verify content tracking worked (system prompt should be tracked)
    assert len(fresh_state["positions"]) > 0
    assert len(fresh_state["known_hashes"]) > 0
    assert fresh_state["next_id"] > 0


def test_replay_with_tool_use(tmp_path, fresh_state):
    """Verify tool use messages are replayed correctly."""
    har_path = tmp_path / "test.har"
    har = {
        "log": {
            "version": "1.2",
            "entries": [
                {
                    "request": {
                        "method": "POST",
                        "headers": [],
                        "postData": {
                            "text": json.dumps({
                                "model": "claude-3-opus-20240229",
                                "messages": [{"role": "user", "content": "Read file test.py"}],
                                "tools": [
                                    {
                                        "name": "read_file",
                                        "description": "Read a file",
                                        "input_schema": {
                                            "type": "object",
                                            "properties": {"path": {"type": "string"}},
                                        },
                                    }
                                ],
                            }),
                        },
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "text": json.dumps({
                                "id": "msg_tool",
                                "type": "message",
                                "role": "assistant",
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "toolu_123",
                                        "name": "read_file",
                                        "input": {"path": "test.py"},
                                    }
                                ],
                                "model": "claude-3-opus-20240229",
                                "stop_reason": "tool_use",
                                "usage": {"input_tokens": 50, "output_tokens": 20},
                            }),
                        },
                    },
                }
            ],
        }
    }

    with open(har_path, "w") as f:
        json.dump(har, f)

    # Load and convert
    pairs = load_har(str(har_path))
    events = convert_to_events(*pairs[0])

    # Process events
    all_blocks = []

    for event in events:
        kind = event[0]

        if kind == "request":
            blocks = format_request(event[1], fresh_state)
            all_blocks.extend(blocks)
        elif kind == "response_event":
            event_type, event_data = event[1], event[2]
            blocks = format_response_event(event_type, event_data)
            all_blocks.extend(blocks)

    # Verify tool use was processed
    from cc_dump.formatting import StreamToolUseBlock

    tool_blocks = [b for b in all_blocks if isinstance(b, StreamToolUseBlock)]
    assert len(tool_blocks) == 1
    assert tool_blocks[0].name == "read_file"


def test_replay_multiple_turns(tmp_path, fresh_state):
    """Verify multiple turns are replayed in order."""
    har_path = tmp_path / "test.har"
    har = {
        "log": {
            "version": "1.2",
            "entries": [
                # First turn
                {
                    "request": {
                        "method": "POST",
                        "headers": [],
                        "postData": {
                            "text": json.dumps({
                                "model": "claude-3-opus-20240229",
                                "messages": [{"role": "user", "content": "First message"}],
                            }),
                        },
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "text": json.dumps({
                                "id": "msg_1",
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "text", "text": "First response"}],
                                "model": "claude-3-opus-20240229",
                                "stop_reason": "end_turn",
                                "usage": {"input_tokens": 10, "output_tokens": 5},
                            }),
                        },
                    },
                },
                # Second turn
                {
                    "request": {
                        "method": "POST",
                        "headers": [],
                        "postData": {
                            "text": json.dumps({
                                "model": "claude-3-opus-20240229",
                                "messages": [
                                    {"role": "user", "content": "First message"},
                                    {"role": "assistant", "content": "First response"},
                                    {"role": "user", "content": "Second message"},
                                ],
                            }),
                        },
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "text": json.dumps({
                                "id": "msg_2",
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "text", "text": "Second response"}],
                                "model": "claude-3-opus-20240229",
                                "stop_reason": "end_turn",
                                "usage": {"input_tokens": 20, "output_tokens": 5},
                            }),
                        },
                    },
                },
            ],
        }
    }

    with open(har_path, "w") as f:
        json.dump(har, f)

    # Load and convert all pairs
    pairs = load_har(str(har_path))
    assert len(pairs) == 2

    # Process all events
    for pair in pairs:
        events = convert_to_events(*pair)
        for event in events:
            kind = event[0]
            if kind == "request":
                format_request(event[1], fresh_state)

    # Verify both requests were processed
    assert fresh_state["request_counter"] == 2


def test_replay_system_prompt_tracking(tmp_path, fresh_state):
    """Verify system prompt tracking works with replayed events."""
    har_path = tmp_path / "test.har"

    # First request with system prompt A
    system_a = "You are a helpful assistant."

    # Second request with system prompt B (changed)
    system_b = "You are a coding assistant."

    har = {
        "log": {
            "version": "1.2",
            "entries": [
                {
                    "request": {
                        "method": "POST",
                        "headers": [],
                        "postData": {
                            "text": json.dumps({
                                "model": "claude-3-opus-20240229",
                                "messages": [{"role": "user", "content": "Test"}],
                                "system": system_a,
                            }),
                        },
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "text": json.dumps({
                                "id": "msg_1",
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "text", "text": "Response"}],
                                "model": "claude-3-opus-20240229",
                                "stop_reason": "end_turn",
                                "usage": {"input_tokens": 10, "output_tokens": 5},
                            }),
                        },
                    },
                },
                {
                    "request": {
                        "method": "POST",
                        "headers": [],
                        "postData": {
                            "text": json.dumps({
                                "model": "claude-3-opus-20240229",
                                "messages": [{"role": "user", "content": "Test"}],
                                "system": system_b,
                            }),
                        },
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "text": json.dumps({
                                "id": "msg_2",
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "text", "text": "Response"}],
                                "model": "claude-3-opus-20240229",
                                "stop_reason": "end_turn",
                                "usage": {"input_tokens": 10, "output_tokens": 5},
                            }),
                        },
                    },
                },
            ],
        }
    }

    with open(har_path, "w") as f:
        json.dump(har, f)

    # Load and process
    pairs = load_har(str(har_path))

    # Process both requests
    for pair in pairs:
        events = convert_to_events(*pair)
        for event in events:
            if event[0] == "request":
                format_request(event[1], fresh_state)

    # Verify both system prompts were tracked
    assert "system:0" in fresh_state["positions"]
    assert fresh_state["next_id"] == 2  # Two different system prompts

    # Verify different hashes
    pos = fresh_state["positions"]["system:0"]
    assert "sp-1" in pos["id"] or "sp-2" in pos["id"]
