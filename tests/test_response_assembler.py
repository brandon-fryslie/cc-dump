"""Unit tests for response_assembler.py — proxy-boundary SSE assembly."""

import json

from cc_dump.pipeline.response_assembler import (
    ResponseAssembler,
    reconstruct_message_from_events,
    sse_event_to_dict,
    ReconstructedMessage,
)
from cc_dump.pipeline.event_types import (
    parse_sse_event,
    MessageRole,
    StopReason,
)


# ─── reconstruct_message_from_events ─────────────────────────────────────────


def test_reconstruct_text_deltas():
    """Text deltas accumulate into a single content block."""
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_abc",
                "model": "claude-sonnet-4-20250514",
                "role": "assistant",
                "usage": {"input_tokens": 50, "output_tokens": 0},
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
            "delta": {"type": "text_delta", "text": "Hello"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": ", world!"},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 5},
        },
        {"type": "message_stop"},
    ]

    result = reconstruct_message_from_events(events)

    assert result["id"] == "msg_abc"
    assert result["model"] == "claude-sonnet-4-20250514"
    assert result["role"] == "assistant"
    assert result["type"] == "message"
    assert result["stop_reason"] == "end_turn"
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"
    assert result["content"][0]["text"] == "Hello, world!"
    assert result["usage"]["input_tokens"] == 50
    assert result["usage"]["output_tokens"] == 5


def test_reconstruct_tool_use_with_json_deltas():
    """Tool use blocks accumulate input_json_delta into parsed input."""
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_tool",
                "model": "claude-sonnet-4-20250514",
                "role": "assistant",
                "usage": {"input_tokens": 100, "output_tokens": 0},
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_abc123",
                "name": "read_file",
            },
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"path":'},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": ' "/tmp/test.txt"}'},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 20},
        },
        {"type": "message_stop"},
    ]

    result = reconstruct_message_from_events(events)

    assert result["stop_reason"] == "tool_use"
    assert len(result["content"]) == 1
    block = result["content"][0]
    assert block["type"] == "tool_use"
    assert block["id"] == "toolu_abc123"
    assert block["name"] == "read_file"
    assert block["input"] == {"path": "/tmp/test.txt"}


def test_reconstruct_mixed_text_and_tool_use():
    """Mixed content: text block followed by tool_use block."""
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_mixed",
                "model": "claude-sonnet-4-20250514",
                "role": "assistant",
                "usage": {"input_tokens": 10, "output_tokens": 0},
            },
        },
        # text block
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Let me read that file."},
        },
        {"type": "content_block_stop", "index": 0},
        # tool_use block
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_xyz",
                "name": "Read",
            },
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"file": "a.py"}'},
        },
        {"type": "content_block_stop", "index": 1},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 30},
        },
        {"type": "message_stop"},
    ]

    result = reconstruct_message_from_events(events)

    assert len(result["content"]) == 2
    assert result["content"][0]["type"] == "text"
    assert result["content"][0]["text"] == "Let me read that file."
    assert result["content"][1]["type"] == "tool_use"
    assert result["content"][1]["name"] == "Read"
    assert result["content"][1]["input"] == {"file": "a.py"}


def test_reconstruct_stop_reason_propagation():
    """stop_reason and stop_sequence propagate from message_delta."""
    # end_turn
    events_end_turn = [
        {
            "type": "message_start",
            "message": {"id": "m1", "model": "m", "role": "assistant", "usage": {}},
        },
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 1},
        },
    ]
    assert reconstruct_message_from_events(events_end_turn)["stop_reason"] == "end_turn"

    # max_tokens
    events_max = [
        {
            "type": "message_start",
            "message": {"id": "m2", "model": "m", "role": "assistant", "usage": {}},
        },
        {
            "type": "message_delta",
            "delta": {"stop_reason": "max_tokens"},
            "usage": {"output_tokens": 4096},
        },
    ]
    assert reconstruct_message_from_events(events_max)["stop_reason"] == "max_tokens"

    # tool_use
    events_tool = [
        {
            "type": "message_start",
            "message": {"id": "m3", "model": "m", "role": "assistant", "usage": {}},
        },
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 10},
        },
    ]
    assert reconstruct_message_from_events(events_tool)["stop_reason"] == "tool_use"


def test_reconstruct_usage_merges():
    """Usage from message_start and message_delta are merged."""
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "m1",
                "model": "m",
                "role": "assistant",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 0,
                    "cache_read_input_tokens": 50,
                    "cache_creation_input_tokens": 25,
                },
            },
        },
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 42},
        },
    ]

    result = reconstruct_message_from_events(events)

    assert result["usage"]["input_tokens"] == 100
    assert result["usage"]["output_tokens"] == 42
    assert result["usage"]["cache_read_input_tokens"] == 50
    assert result["usage"]["cache_creation_input_tokens"] == 25


def test_reconstruct_empty_events():
    """Empty event list produces empty message skeleton."""
    result = reconstruct_message_from_events([])

    assert result["id"] == ""
    assert result["type"] == "message"
    assert result["content"] == []
    assert result["stop_reason"] is None


def test_reconstruct_malformed_tool_json():
    """Malformed tool input JSON falls back to empty dict."""
    events = [
        {
            "type": "message_start",
            "message": {"id": "m1", "model": "m", "role": "assistant", "usage": {}},
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "t1", "name": "broken"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": "{not valid json"},
        },
        {"type": "content_block_stop", "index": 0},
    ]

    result = reconstruct_message_from_events(events)

    assert result["content"][0]["input"] == {}


# ─── ResponseAssembler (StreamSink protocol) ─────────────────────────────────


def test_assembler_text_stream():
    """Assembler produces complete message from text stream events."""
    assembler = ResponseAssembler()

    events = [
        ("message_start", {
            "type": "message_start",
            "message": {
                "id": "msg_asm1",
                "model": "claude-sonnet-4-20250514",
                "role": "assistant",
                "usage": {"input_tokens": 10, "output_tokens": 0},
            },
        }),
        ("content_block_start", {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }),
        ("content_block_delta", {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hi there"},
        }),
        ("content_block_stop", {
            "type": "content_block_stop",
            "index": 0,
        }),
        ("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 3},
        }),
        ("message_stop", {"type": "message_stop"}),
    ]

    for event_type, event in events:
        assembler.on_event(event_type, event)
    assembler.on_done()

    assert assembler.result is not None
    assert assembler.result["id"] == "msg_asm1"
    assert assembler.result["content"][0]["text"] == "Hi there"
    assert assembler.result["stop_reason"] == "end_turn"


def test_assembler_tool_use_stream():
    """Assembler produces complete message from tool_use stream."""
    assembler = ResponseAssembler()

    events = [
        ("message_start", {
            "type": "message_start",
            "message": {
                "id": "msg_asm2",
                "model": "claude-sonnet-4-20250514",
                "role": "assistant",
                "usage": {"input_tokens": 50, "output_tokens": 0},
            },
        }),
        ("content_block_start", {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_test",
                "name": "Bash",
            },
        }),
        ("content_block_delta", {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"comm'},
        }),
        ("content_block_delta", {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": 'and": "ls"}'},
        }),
        ("content_block_stop", {
            "type": "content_block_stop",
            "index": 0,
        }),
        ("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 15},
        }),
        ("message_stop", {"type": "message_stop"}),
    ]

    for event_type, event in events:
        assembler.on_event(event_type, event)
    assembler.on_done()

    assert assembler.result is not None
    assert assembler.result["stop_reason"] == "tool_use"
    block = assembler.result["content"][0]
    assert block["type"] == "tool_use"
    assert block["name"] == "Bash"
    assert block["input"] == {"command": "ls"}


def test_assembler_no_events():
    """Assembler with no events returns None."""
    assembler = ResponseAssembler()
    assembler.on_done()
    assert assembler.result is None


def test_assembler_on_raw_is_noop():
    """on_raw does not affect assembly."""
    assembler = ResponseAssembler()
    assembler.on_raw(b"data: {}\n\n")
    assembler.on_done()
    assert assembler.result is None


def test_assembler_result_before_done_is_none():
    """Result is None before on_done is called."""
    assembler = ResponseAssembler()
    assembler.on_event("message_start", {
        "type": "message_start",
        "message": {"id": "m", "model": "m", "role": "assistant", "usage": {}},
    })
    assert assembler.result is None


# ─── sse_event_to_dict roundtrip ─────────────────────────────────────────────


def test_sse_event_to_dict_text_roundtrip():
    """Typed text SSE events survive roundtrip through sse_event_to_dict."""
    raw_events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_rt",
                "model": "claude-sonnet-4-20250514",
                "role": "assistant",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 0,
                    "cache_read_input_tokens": 5,
                    "cache_creation_input_tokens": 0,
                },
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
            "delta": {"type": "text_delta", "text": "roundtrip"},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 1},
        },
        {"type": "message_stop"},
    ]

    # Parse to typed, convert back to dict, reconstruct
    typed_events = [parse_sse_event(e["type"], e) for e in raw_events]
    dict_events = [sse_event_to_dict(te) for te in typed_events]
    result = reconstruct_message_from_events(dict_events)

    assert result["id"] == "msg_rt"
    assert result["content"][0]["text"] == "roundtrip"
    assert result["stop_reason"] == "end_turn"


def test_sse_event_to_dict_tool_use_roundtrip():
    """Typed tool_use SSE events survive roundtrip through sse_event_to_dict."""
    raw_events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_rt2",
                "model": "claude-sonnet-4-20250514",
                "role": "assistant",
                "usage": {"input_tokens": 1, "output_tokens": 0,
                          "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "toolu_rt", "name": "Grep"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"pattern": "foo"}'},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 10},
        },
        {"type": "message_stop"},
    ]

    typed_events = [parse_sse_event(e["type"], e) for e in raw_events]
    dict_events = [sse_event_to_dict(te) for te in typed_events]
    result = reconstruct_message_from_events(dict_events)

    assert result["content"][0]["type"] == "tool_use"
    assert result["content"][0]["name"] == "Grep"
    assert result["content"][0]["input"] == {"pattern": "foo"}
    assert result["stop_reason"] == "tool_use"
