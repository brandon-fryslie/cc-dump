"""End-to-end integration test: record → replay → verify zero divergence.

This test verifies the critical architectural requirement:
"Zero divergence between 'live display' and 'restore session' code paths."

The test:
1. Creates synthetic events representing a realistic conversation
2. Processes them through the live formatting pipeline
3. Records them to a HAR file via HARRecordingSubscriber
4. Replays the HAR file via har_replayer
5. Processes replayed events through the same formatting pipeline
6. Compares the FormattedBlock outputs for semantic equality

Note: HAR files store synthetic non-streaming responses (architectural decision from
Sprint 1). This means:
- Live events: stream=true, content arrives incrementally as multiple TextDeltaBlocks
- Replay events: stream=false (in HAR), but converted to synthetic streaming with consolidated TextDeltaBlocks

The comparison focuses on semantic equality of the final content, not exact block-for-block
match of streaming delivery chunks.
"""

import json
import copy

import queue
from pathlib import Path

import pytest

from cc_dump.har_recorder import HARRecordingSubscriber
from cc_dump.har_replayer import load_har, convert_to_events
from cc_dump.event_types import (
    PipelineEvent,
    RequestHeadersEvent,
    RequestBodyEvent,
    ResponseHeadersEvent,
    ResponseSSEEvent,
    ResponseDoneEvent,
    parse_sse_event,
)
import cc_dump.formatting as fmt


def _sse_events(event_type: str, raw: dict) -> ResponseSSEEvent:
    """Helper to build a ResponseSSEEvent from raw SSE data."""
    return ResponseSSEEvent(sse_event=parse_sse_event(event_type, raw))


# Sample events representing a realistic API exchange with multiple event types
SAMPLE_EVENTS: list[PipelineEvent] = [
    # Request with system prompt and user message
    RequestHeadersEvent(headers={"content-type": "application/json", "anthropic-version": "2023-06-01"}),
    RequestBodyEvent(body={
        "model": "claude-3-opus-20240229",
        "max_tokens": 4096,
        "stream": True,
        "system": [{"type": "text", "text": "You are a helpful coding assistant."}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "Write a function to sum two numbers."}]}],
    }),

    # Response with text content
    ResponseHeadersEvent(status_code=200, headers={"content-type": "text/event-stream"}),
    _sse_events("message_start", {
        "type": "message_start",
        "message": {
            "id": "msg_01ABC",
            "type": "message",
            "role": "assistant",
            "model": "claude-3-opus-20240229",
            "usage": {"input_tokens": 125, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        }
    }),
    _sse_events("content_block_start", {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""}
    }),
    _sse_events("content_block_delta", {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "Here's a simple function:\n\n"}
    }),
    _sse_events("content_block_delta", {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "def sum(a, b):\n    return a + b"}
    }),
    _sse_events("content_block_stop", {
        "type": "content_block_stop",
        "index": 0,
    }),
    _sse_events("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn"},
        "usage": {"output_tokens": 28}
    }),
    _sse_events("message_stop", {"type": "message_stop"}),
    ResponseDoneEvent(),
]


TOOL_USE_EVENTS: list[PipelineEvent] = [
    # Request with tool definitions
    RequestHeadersEvent(headers={"content-type": "application/json", "anthropic-version": "2023-06-01"}),
    RequestBodyEvent(body={
        "model": "claude-3-opus-20240229",
        "max_tokens": 4096,
        "stream": True,
        "tools": [
            {
                "name": "read_file",
                "description": "Read a file from disk",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"]
                }
            }
        ],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "Read config.json"}]}],
    }),

    # Response with tool use
    ResponseHeadersEvent(status_code=200, headers={"content-type": "text/event-stream"}),
    _sse_events("message_start", {
        "type": "message_start",
        "message": {
            "id": "msg_02XYZ",
            "type": "message",
            "role": "assistant",
            "model": "claude-3-opus-20240229",
            "usage": {"input_tokens": 250, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        }
    }),
    _sse_events("content_block_start", {
        "type": "content_block_start",
        "index": 0,
        "content_block": {
            "type": "tool_use",
            "id": "toolu_123",
            "name": "read_file",
        }
    }),
    _sse_events("content_block_delta", {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": '{"path": "config.json"}'}
    }),
    _sse_events("content_block_stop", {
        "type": "content_block_stop",
        "index": 0,
    }),
    _sse_events("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": "tool_use"},
        "usage": {"output_tokens": 45}
    }),
    _sse_events("message_stop", {"type": "message_stop"}),
    ResponseDoneEvent(),
]


def format_events(events: list[PipelineEvent], state: dict) -> list:
    """Process events through formatting pipeline and return all blocks.

    This mimics what event_handlers.py does when processing live events.

    Args:
        events: List of typed PipelineEvent objects
        state: Content tracking state dict

    Returns:
        List of all FormattedBlock objects produced
    """
    all_blocks = []

    for event in events:
        if isinstance(event, RequestBodyEvent):
            blocks = fmt.format_request(event.body, state)
            all_blocks.extend(blocks)

        elif isinstance(event, RequestHeadersEvent):
            blocks = fmt.format_request_headers(event.headers)
            all_blocks.extend(blocks)

        elif isinstance(event, ResponseHeadersEvent):
            blocks = fmt.format_response_headers(event.status_code, event.headers)
            all_blocks.extend(blocks)

        elif isinstance(event, ResponseSSEEvent):
            blocks = fmt.format_response_event(event.sse_event)
            all_blocks.extend(blocks)

    return all_blocks


def normalize_blocks_for_comparison(blocks: list) -> list:
    """Normalize blocks to filter out known acceptable divergences.

    The HAR format stores synthetic non-streaming responses, which causes some
    expected differences:
    - stream=true vs stream=false in MetadataBlock
    - HttpHeadersBlock for responses may differ (live: text/event-stream, replay: application/json)
    - TextDeltaBlock count may differ (live: multiple chunks, replay: consolidated)

    This function normalizes blocks for semantic comparison.

    Args:
        blocks: List of FormattedBlock objects

    Returns:
        Normalized list for semantic comparison
    """
    normalized = []
    pending_text_deltas = []

    for block in blocks:
        # Skip response headers (known divergence: live SSE vs replay JSON)
        if isinstance(block, fmt.HttpHeadersBlock) and block.header_type == 'response':
            continue

        # Consolidate consecutive TextDeltaBlocks
        if isinstance(block, fmt.TextDeltaBlock):
            pending_text_deltas.append(block)
            continue
        else:
            # Flush any pending TextDeltaBlocks as a single merged block
            if pending_text_deltas:
                # Merge all delta text
                merged_text = ''.join(b.text for b in pending_text_deltas)
                # Create single merged block with combined text
                merged_block = fmt.TextDeltaBlock(text=merged_text)
                normalized.append(merged_block)
                pending_text_deltas = []

        # Include all other blocks
        normalized.append(block)

    # Flush any remaining TextDeltaBlocks
    if pending_text_deltas:
        merged_text = ''.join(b.text for b in pending_text_deltas)
        normalized.append(fmt.TextDeltaBlock(text=merged_text))

    return normalized


def compare_blocks(live_blocks: list, replay_blocks: list) -> None:
    """Compare two lists of blocks for semantic equality.

    Handles expected divergences from HAR format decisions while ensuring
    that the actual content and structure are preserved.

    Args:
        live_blocks: Blocks from live processing
        replay_blocks: Blocks from replay processing

    Raises:
        AssertionError: If blocks differ in semantically important ways
    """
    # Normalize to filter acceptable divergences
    live_norm = normalize_blocks_for_comparison(live_blocks)
    replay_norm = normalize_blocks_for_comparison(replay_blocks)

    # Compare block types
    assert len(live_norm) == len(replay_norm), \
        f"Block count mismatch: live={len(live_norm)}, replay={len(replay_norm)}"

    for i, (live_block, replay_block) in enumerate(zip(live_norm, replay_norm)):
        # Types must match
        assert type(live_block) == type(replay_block), \
            f"Block {i}: type mismatch: {type(live_block).__name__} != {type(replay_block).__name__}"

        # For MetadataBlock, allow stream flag to differ (known HAR format decision)
        if isinstance(live_block, fmt.MetadataBlock):
            # Compare all fields except stream
            assert live_block.model == replay_block.model
            assert live_block.max_tokens == replay_block.max_tokens
            assert live_block.tool_count == replay_block.tool_count
            # stream flag may differ (live: true, replay: false in HAR)
            continue

        # For all other blocks, require exact equality
        assert repr(live_block) == repr(replay_block), \
            f"Block {i}: content mismatch:\nLive: {live_block!r}\nReplay: {replay_block!r}"


def test_record_replay_text_response(tmp_path, fresh_state):
    """Record and replay text response produces semantically identical FormattedBlocks."""
    har_path = tmp_path / "test.har"

    # 1. Process events through live pipeline
    live_blocks = format_events(SAMPLE_EVENTS, copy.deepcopy(fresh_state))

    # 2. Record events to HAR
    recorder = HARRecordingSubscriber(str(har_path), "test-session")
    for event in SAMPLE_EVENTS:
        recorder.on_event(event)
    recorder.close()

    # 3. Replay from HAR
    pairs = load_har(str(har_path))
    assert len(pairs) == 1

    req_headers, req_body, resp_status, resp_headers, complete_message = pairs[0]
    replayed_events = convert_to_events(req_headers, req_body, resp_status, resp_headers, complete_message)

    # 4. Process replayed events through same pipeline
    replayed_blocks = format_events(replayed_events, copy.deepcopy(fresh_state))

    # 5. Compare blocks (semantic equality)
    compare_blocks(live_blocks, replayed_blocks)


def test_record_replay_tool_use(tmp_path, fresh_state):
    """Record and replay tool use produces semantically identical FormattedBlocks."""
    har_path = tmp_path / "test_tools.har"

    # 1. Process events through live pipeline
    live_blocks = format_events(TOOL_USE_EVENTS, copy.deepcopy(fresh_state))

    # 2. Record events to HAR
    recorder = HARRecordingSubscriber(str(har_path), "test-session")
    for event in TOOL_USE_EVENTS:
        recorder.on_event(event)
    recorder.close()

    # 3. Replay from HAR
    pairs = load_har(str(har_path))
    assert len(pairs) == 1

    req_headers, req_body, resp_status, resp_headers, complete_message = pairs[0]
    replayed_events = convert_to_events(req_headers, req_body, resp_status, resp_headers, complete_message)

    # 4. Process replayed events through same pipeline
    replayed_blocks = format_events(replayed_events, copy.deepcopy(fresh_state))

    # 5. Compare blocks (semantic equality)
    compare_blocks(live_blocks, replayed_blocks)


def _make_typed_events(raw_events: list[tuple]) -> list[PipelineEvent]:
    """Convert raw event tuples to typed PipelineEvent objects for inline test data."""
    result: list[PipelineEvent] = []
    for raw in raw_events:
        kind = raw[0]
        if kind == "request_headers":
            result.append(RequestHeadersEvent(headers=raw[1]))
        elif kind == "request":
            result.append(RequestBodyEvent(body=raw[1]))
        elif kind == "response_headers":
            result.append(ResponseHeadersEvent(status_code=raw[1], headers=raw[2]))
        elif kind == "response_event":
            result.append(_sse_events(raw[1], raw[2]))
        elif kind == "response_done":
            result.append(ResponseDoneEvent())
    return result


def test_record_replay_content_tracking_state(tmp_path):
    """Content tracking state (system prompt hashing) is identical in replay."""
    har_path = tmp_path / "test_state.har"

    # Create two requests with same system prompt (should get same tag)
    events_1 = _make_typed_events([
        ("request_headers", {}),
        ("request", {
            "model": "claude-3-opus-20240229",
            "system": [{"type": "text", "text": "You are a helpful assistant."}],
            "messages": [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}],
        }),
        ("response_headers", 200, {}),
        ("response_event", "message_start", {
            "type": "message_start",
            "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-3-opus-20240229", "usage": {}}
        }),
        ("response_event", "message_stop", {"type": "message_stop"}),
        ("response_done",),
    ])

    events_2 = _make_typed_events([
        ("request_headers", {}),
        ("request", {
            "model": "claude-3-opus-20240229",
            "system": [{"type": "text", "text": "You are a helpful assistant."}],  # Same prompt
            "messages": [{"role": "user", "content": [{"type": "text", "text": "Goodbye"}]}],
        }),
        ("response_headers", 200, {}),
        ("response_event", "message_start", {
            "type": "message_start",
            "message": {"id": "msg_2", "type": "message", "role": "assistant", "model": "claude-3-opus-20240229", "usage": {}}
        }),
        ("response_event", "message_stop", {"type": "message_stop"}),
        ("response_done",),
    ])

    # 1. Process live with state tracking
    state_live = {
        "positions": {},
        "known_hashes": {},
        "next_id": 0,
        "next_color": 0,
        "request_counter": 0,
    }

    live_blocks_1 = format_events(events_1, state_live)
    live_blocks_2 = format_events(events_2, state_live)

    # 2. Record both to HAR
    recorder = HARRecordingSubscriber(str(har_path), "test-session")
    for event in events_1 + events_2:
        recorder.on_event(event)
    recorder.close()

    # 3. Replay from HAR
    pairs = load_har(str(har_path))
    assert len(pairs) == 2

    state_replay = {
        "positions": {},
        "known_hashes": {},
        "next_id": 0,
        "next_color": 0,
        "request_counter": 0,
    }

    # Process first request
    req_headers, req_body, resp_status, resp_headers, complete_message = pairs[0]
    replayed_events_1 = convert_to_events(req_headers, req_body, resp_status, resp_headers, complete_message)
    replay_blocks_1 = format_events(replayed_events_1, state_replay)

    # Process second request
    req_headers, req_body, resp_status, resp_headers, complete_message = pairs[1]
    replayed_events_2 = convert_to_events(req_headers, req_body, resp_status, resp_headers, complete_message)
    replay_blocks_2 = format_events(replayed_events_2, state_replay)

    # 4. Compare blocks (semantic equality)
    compare_blocks(live_blocks_1, replay_blocks_1)
    compare_blocks(live_blocks_2, replay_blocks_2)

    # 5. Verify state accumulated identically
    # The system prompt should get the same hash and tag in both live and replay
    assert state_live["known_hashes"] == state_replay["known_hashes"]
    assert state_live["next_id"] == state_replay["next_id"]
    assert state_live["next_color"] == state_replay["next_color"]


def test_multiple_turns_in_single_har(tmp_path, fresh_state):
    """Multiple conversation turns in single HAR file replay correctly."""
    har_path = tmp_path / "test_multi.har"

    # Combine multiple turns
    all_events = list(SAMPLE_EVENTS) + list(TOOL_USE_EVENTS)

    # 1. Process live
    live_blocks = format_events(all_events, copy.deepcopy(fresh_state))

    # 2. Record
    recorder = HARRecordingSubscriber(str(har_path), "test-session")
    for event in all_events:
        recorder.on_event(event)
    recorder.close()

    # 3. Replay
    pairs = load_har(str(har_path))
    assert len(pairs) == 2  # Two complete request/response pairs

    replayed_blocks = []
    replay_state = copy.deepcopy(fresh_state)
    for req_headers, req_body, resp_status, resp_headers, complete_message in pairs:
        replayed_events = convert_to_events(req_headers, req_body, resp_status, resp_headers, complete_message)
        replayed_blocks.extend(format_events(replayed_events, replay_state))

    # 4. Compare (semantic equality)
    compare_blocks(live_blocks, replayed_blocks)


def test_har_is_source_of_truth(tmp_path):
    """HAR file contains all information needed to reconstruct display.

    This test verifies the architectural requirement that HAR is the
    single source of truth - no data is lost during record/replay cycle.
    """
    har_path = tmp_path / "source_of_truth.har"

    # Create events with rich metadata
    events = _make_typed_events([
        ("request_headers", {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": "sk-ant-xxx",  # Should be captured
        }),
        ("request", {
            "model": "claude-3-opus-20240229",
            "max_tokens": 4096,
            "temperature": 0.7,  # Parameter should be preserved
            "system": [
                {"type": "text", "text": "You are an expert."},
                {"type": "text", "text": "Follow best practices."}  # Multiple system blocks
            ],
            "messages": [
                {"role": "user", "content": [
                    {"type": "text", "text": "Help me"},
                    {"type": "text", "text": "with this problem"}  # Multiple content blocks
                ]}
            ],
        }),
        ("response_headers", 200, {
            "content-type": "text/event-stream",
            "request-id": "req_123",  # Response metadata
        }),
        ("response_event", "message_start", {
            "type": "message_start",
            "message": {
                "id": "msg_abc",
                "type": "message",
                "role": "assistant",
                "model": "claude-3-opus-20240229",
                "usage": {
                    "input_tokens": 100,
                    "cache_read_input_tokens": 50,  # Cache metrics
                    "cache_creation_input_tokens": 25,
                }
            }
        }),
        ("response_event", "content_block_start", {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""}
        }),
        ("response_event", "content_block_delta", {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "I can help! \U0001f389"}  # Unicode
        }),
        ("response_event", "content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("response_event", "message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 12}
        }),
        ("response_event", "message_stop", {"type": "message_stop"}),
        ("response_done",),
    ])

    # Record
    recorder = HARRecordingSubscriber(str(har_path), "test-session")
    for event in events:
        recorder.on_event(event)
    recorder.close()

    # Load HAR and inspect
    with open(har_path, "r") as f:
        har = json.load(f)

    entry = har["log"]["entries"][0]

    # Verify request data preserved
    request_body = json.loads(entry["request"]["postData"]["text"])
    assert request_body["temperature"] == 0.7
    assert len(request_body["system"]) == 2
    assert len(request_body["messages"][0]["content"]) == 2

    # Verify request headers preserved
    req_headers = {h["name"]: h["value"] for h in entry["request"]["headers"]}
    assert "x-api-key" in req_headers

    # Verify response data preserved
    response_body = json.loads(entry["response"]["content"]["text"])
    assert response_body["id"] == "msg_abc"
    assert response_body["usage"]["cache_read_input_tokens"] == 50
    assert "\U0001f389" in response_body["content"][0]["text"]  # Unicode preserved

    # Verify response headers preserved
    resp_headers = {h["name"]: h["value"] for h in entry["response"]["headers"]}
    # Note: synthetic response has application/json, not text/event-stream
    assert resp_headers["content-type"] == "application/json"
