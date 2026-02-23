"""Unit tests for har_recorder.py - HAR 1.2 recording and message reconstruction."""

import json

from cc_dump.pipeline.event_types import (
    RequestHeadersEvent,
    RequestBodyEvent,
    ResponseHeadersEvent,
    ResponseCompleteEvent,
)
from cc_dump.pipeline.har_recorder import (
    HARRecordingSubscriber,
    build_har_request,
    build_har_response,
)
from cc_dump.pipeline.response_assembler import reconstruct_message_from_events


# ─── HAR Request Builder Tests ────────────────────────────────────────────────


def test_build_har_request_basic():
    """HAR request builder creates valid structure."""
    headers = {
        "content-type": "application/json",
        "x-api-key": "sk-ant-test",
    }
    body = {
        "model": "claude-3-opus-20240229",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True,
    }

    har_req = build_har_request(
        "POST", "https://api.anthropic.com/v1/messages", headers, body
    )

    # Verify structure
    assert har_req["method"] == "POST"
    assert har_req["url"] == "https://api.anthropic.com/v1/messages"
    assert har_req["httpVersion"] == "HTTP/1.1"

    # Headers as name/value pairs
    assert isinstance(har_req["headers"], list)
    assert {"name": "content-type", "value": "application/json"} in har_req["headers"]

    # Post data
    assert har_req["postData"]["mimeType"] == "application/json"
    post_body = json.loads(har_req["postData"]["text"])
    assert post_body["stream"] is False  # Synthetic non-streaming


def test_build_har_request_synthetic_stream_false():
    """Request body is modified to stream=false for clarity."""
    body = {"model": "claude-3-opus-20240229", "stream": True}
    har_req = build_har_request(
        "POST", "https://api.anthropic.com/v1/messages", {}, body
    )

    post_body = json.loads(har_req["postData"]["text"])
    assert post_body["stream"] is False


def test_build_har_request_empty_headers():
    """Request with no headers works."""
    har_req = build_har_request("POST", "https://api.anthropic.com/v1/messages", {}, {})
    assert har_req["headers"] == []


# ─── HAR Response Builder Tests ───────────────────────────────────────────────


def test_build_har_response_basic():
    """HAR response builder creates valid structure."""
    complete_message = {
        "id": "msg_123",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "Hello!"}],
        "model": "claude-3-opus-20240229",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    har_resp = build_har_response(200, {}, complete_message, 1234.5)

    # Verify structure
    assert har_resp["status"] == 200
    assert har_resp["statusText"] == "OK"
    assert har_resp["httpVersion"] == "HTTP/1.1"

    # Content
    assert har_resp["content"]["mimeType"] == "application/json"
    response_body = json.loads(har_resp["content"]["text"])
    assert response_body["id"] == "msg_123"
    assert response_body["content"][0]["text"] == "Hello!"


def test_build_har_response_synthetic_headers():
    """Response has synthetic application/json headers."""
    complete_message = {"id": "msg_123", "content": []}
    har_resp = build_har_response(200, {}, complete_message, 0.0)

    # Should have content-type and content-length
    header_names = [h["name"] for h in har_resp["headers"]]
    assert "content-type" in header_names
    assert "content-length" in header_names


# ─── Message Reconstruction Tests ─────────────────────────────────────────────
# These test reconstruct_message_from_events() in response_assembler.py


def test_reconstruct_message_simple_text():
    """Reconstruct simple text message from SSE events."""
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_123",
                "model": "claude-3-opus-20240229",
                "role": "assistant",
                "usage": {"input_tokens": 10, "output_tokens": 0},
            },
        },
        {"type": "content_block_start", "content_block": {"type": "text"}},
        {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "Hello"},
        },
        {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": " world"},
        },
        {"type": "content_block_stop"},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 5},
        },
    ]

    message = reconstruct_message_from_events(events)

    # Verify reconstructed message
    assert message["id"] == "msg_123"
    assert message["type"] == "message"
    assert message["role"] == "assistant"
    assert message["model"] == "claude-3-opus-20240229"
    assert message["stop_reason"] == "end_turn"
    assert message["usage"]["input_tokens"] == 10
    assert message["usage"]["output_tokens"] == 5

    # Content blocks
    assert len(message["content"]) == 1
    assert message["content"][0]["type"] == "text"
    assert message["content"][0]["text"] == "Hello world"


def test_reconstruct_message_tool_use():
    """Reconstruct message with tool use block."""
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_456",
                "model": "claude-3-opus-20240229",
                "role": "assistant",
                "usage": {"input_tokens": 100, "output_tokens": 0},
            },
        },
        {
            "type": "content_block_start",
            "content_block": {
                "type": "tool_use",
                "id": "toolu_abc",
                "name": "read_file",
            },
        },
        {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": '{"path": "'},
        },
        {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": 'test.py"}'},
        },
        {"type": "content_block_stop"},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 20},
        },
    ]

    message = reconstruct_message_from_events(events)

    # Verify tool use block
    assert len(message["content"]) == 1
    assert message["content"][0]["type"] == "tool_use"
    assert message["content"][0]["id"] == "toolu_abc"
    assert message["content"][0]["name"] == "read_file"
    assert message["content"][0]["input"] == {"path": "test.py"}
    assert message["stop_reason"] == "tool_use"


def test_reconstruct_message_mixed_content():
    """Reconstruct message with both text and tool use."""
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_789",
                "model": "claude-3-opus-20240229",
                "role": "assistant",
                "usage": {"input_tokens": 50, "output_tokens": 0},
            },
        },
        {"type": "content_block_start", "content_block": {"type": "text"}},
        {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "Let me read that file."},
        },
        {"type": "content_block_stop"},
        {
            "type": "content_block_start",
            "content_block": {
                "type": "tool_use",
                "id": "toolu_xyz",
                "name": "read_file",
            },
        },
        {
            "type": "content_block_delta",
            "delta": {
                "type": "input_json_delta",
                "partial_json": '{"path": "data.json"}',
            },
        },
        {"type": "content_block_stop"},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 30},
        },
    ]

    message = reconstruct_message_from_events(events)

    # Two content blocks
    assert len(message["content"]) == 2
    assert message["content"][0]["type"] == "text"
    assert message["content"][0]["text"] == "Let me read that file."
    assert message["content"][1]["type"] == "tool_use"
    assert message["content"][1]["name"] == "read_file"
    assert message["content"][1]["input"]["path"] == "data.json"


def test_reconstruct_message_unicode():
    """Reconstruct message with unicode content."""
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_unicode",
                "model": "claude-3-opus-20240229",
                "role": "assistant",
                "usage": {"input_tokens": 5, "output_tokens": 0},
            },
        },
        {"type": "content_block_start", "content_block": {"type": "text"}},
        {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "Hello \U0001f44b \u4e16\u754c"},
        },
        {"type": "content_block_stop"},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 8},
        },
    ]

    message = reconstruct_message_from_events(events)

    assert message["content"][0]["text"] == "Hello \U0001f44b \u4e16\u754c"


def test_reconstruct_message_empty():
    """Empty event list returns empty message."""
    message = reconstruct_message_from_events([])

    assert message["type"] == "message"
    assert message["role"] == "assistant"
    assert message["content"] == []


def test_reconstruct_message_malformed_tool_json():
    """Malformed tool JSON doesn't crash, defaults to empty object."""
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_bad",
                "model": "claude-3-opus-20240229",
                "role": "assistant",
                "usage": {"input_tokens": 10, "output_tokens": 0},
            },
        },
        {
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "id": "toolu_bad", "name": "test"},
        },
        {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": "{invalid json"},
        },
        {"type": "content_block_stop"},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 5},
        },
    ]

    message = reconstruct_message_from_events(events)

    # Should have tool block with empty input (fallback)
    assert message["content"][0]["type"] == "tool_use"
    assert message["content"][0]["input"] == {}


# ─── HARRecordingSubscriber Tests ─────────────────────────────────────────────


def _complete_msg(msg_id="msg_test", text="Hello", model="claude-3-opus-20240229"):
    """Build a complete Claude message dict."""
    return {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": model,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def test_har_subscriber_initialization(tmp_path):
    """Subscriber initializes without creating a file (lazy init)."""
    har_path = tmp_path / "test.har"
    subscriber = HARRecordingSubscriber(str(har_path))

    assert subscriber.path == str(har_path)

    # File should NOT exist until first entry is committed
    assert not har_path.exists()

    subscriber.close()

    # File should still not exist after closing with 0 entries
    assert not har_path.exists()


def test_har_subscriber_accumulates_events(tmp_path):
    """Subscriber accumulates events from event stream and writes to file."""
    har_path = tmp_path / "test.har"
    subscriber = HARRecordingSubscriber(str(har_path))

    complete_message = _complete_msg()

    # Simulate event sequence
    subscriber.on_event(RequestHeadersEvent(headers={"content-type": "application/json"}))
    subscriber.on_event(
        RequestBodyEvent(body={"model": "claude-3-opus-20240229", "stream": True})
    )
    subscriber.on_event(ResponseHeadersEvent(status_code=200, headers={}))
    subscriber.on_event(ResponseCompleteEvent(body=complete_message))

    # Close and read file
    subscriber.close()

    with open(har_path, "r") as f:
        har = json.load(f)

    # Should have one entry
    assert len(har["log"]["entries"]) == 1
    entry = har["log"]["entries"][0]

    # Verify entry structure
    assert "startedDateTime" in entry
    assert "time" in entry
    assert "request" in entry
    assert "response" in entry

    # Verify request
    assert entry["request"]["method"] == "POST"
    post_body = json.loads(entry["request"]["postData"]["text"])
    assert post_body["stream"] is False  # Synthetic

    # Verify response
    response_body = json.loads(entry["response"]["content"]["text"])
    assert response_body["id"] == "msg_test"
    assert response_body["content"][0]["text"] == "Hello"


def test_har_subscriber_writes_file(tmp_path):
    """Subscriber writes valid HAR file on close."""
    har_path = tmp_path / "test.har"
    subscriber = HARRecordingSubscriber(str(har_path))

    complete_message = _complete_msg(msg_id="msg_file", text="Test")

    # Add a complete request/response cycle
    subscriber.on_event(RequestHeadersEvent(headers={}))
    subscriber.on_event(RequestBodyEvent(body={"model": "claude-3-opus-20240229"}))
    subscriber.on_event(ResponseHeadersEvent(status_code=200, headers={}))
    subscriber.on_event(ResponseCompleteEvent(body=complete_message))

    # Close and write file
    subscriber.close()

    # Verify file exists and is valid JSON
    assert har_path.exists()
    with open(har_path, "r") as f:
        har = json.load(f)

    # Verify HAR structure
    assert har["log"]["version"] == "1.2"
    assert har["log"]["creator"]["name"] == "cc-dump"
    assert len(har["log"]["entries"]) == 1

    # Verify entry is valid
    entry = har["log"]["entries"][0]
    assert entry["request"]["method"] == "POST"
    assert entry["response"]["status"] == 200


def test_har_subscriber_multiple_requests(tmp_path):
    """Subscriber handles multiple request/response cycles."""
    har_path = tmp_path / "test.har"
    subscriber = HARRecordingSubscriber(str(har_path))

    # First request
    subscriber.on_event(RequestHeadersEvent(headers={}))
    subscriber.on_event(
        RequestBodyEvent(
            body={
                "model": "claude-3-opus-20240229",
                "messages": [{"role": "user", "content": "First"}],
            }
        )
    )
    subscriber.on_event(ResponseHeadersEvent(status_code=200, headers={}))
    subscriber.on_event(ResponseCompleteEvent(body=_complete_msg(msg_id="msg_1", text="Response 1")))

    # Second request
    subscriber.on_event(RequestHeadersEvent(headers={}))
    subscriber.on_event(
        RequestBodyEvent(
            body={
                "model": "claude-3-opus-20240229",
                "messages": [{"role": "user", "content": "Second"}],
            }
        )
    )
    subscriber.on_event(ResponseHeadersEvent(status_code=200, headers={}))
    subscriber.on_event(ResponseCompleteEvent(body=_complete_msg(msg_id="msg_2", text="Response 2")))

    # Close and read file
    subscriber.close()

    with open(har_path, "r") as f:
        har = json.load(f)

    # Should have two entries
    entries = har["log"]["entries"]
    assert len(entries) == 2
    assert (
        json.loads(entries[0]["response"]["content"]["text"])["content"][0]["text"]
        == "Response 1"
    )
    assert (
        json.loads(entries[1]["response"]["content"]["text"])["content"][0]["text"]
        == "Response 2"
    )


def test_har_subscriber_interleaved_requests_by_request_id(tmp_path):
    """Interleaved concurrent requests are reconstructed by request_id."""
    har_path = tmp_path / "test.har"
    subscriber = HARRecordingSubscriber(str(har_path))

    req1 = "req-1"
    req2 = "req-2"

    # Request setup interleaved.
    subscriber.on_event(RequestHeadersEvent(headers={"x-req": "1"}, request_id=req1))
    subscriber.on_event(
        RequestBodyEvent(
            body={
                "model": "claude-3-opus-20240229",
                "messages": [{"role": "user", "content": "first"}],
            },
            request_id=req1,
        )
    )
    subscriber.on_event(RequestHeadersEvent(headers={"x-req": "2"}, request_id=req2))
    subscriber.on_event(
        RequestBodyEvent(
            body={
                "model": "claude-3-opus-20240229",
                "messages": [{"role": "user", "content": "second"}],
            },
            request_id=req2,
        )
    )

    # Response metadata interleaved.
    subscriber.on_event(ResponseHeadersEvent(status_code=200, headers={"x-resp": "1"}, request_id=req1))
    subscriber.on_event(ResponseHeadersEvent(status_code=200, headers={"x-resp": "2"}, request_id=req2))

    # Complete responses in reverse order.
    subscriber.on_event(ResponseCompleteEvent(body=_complete_msg(msg_id="msg_2", text="resp second"), request_id=req2))
    subscriber.on_event(ResponseCompleteEvent(body=_complete_msg(msg_id="msg_1", text="resp first"), request_id=req1))

    subscriber.close()

    with open(har_path, "r") as f:
        har = json.load(f)

    entries = har["log"]["entries"]
    assert len(entries) == 2

    # Match request content -> response content pairs; they must remain aligned.
    pairs = []
    for entry in entries:
        req_body = json.loads(entry["request"]["postData"]["text"])
        req_text = req_body["messages"][0]["content"]
        resp_body = json.loads(entry["response"]["content"]["text"])
        resp_text = resp_body["content"][0]["text"]
        pairs.append((req_text, resp_text))

    assert ("first", "resp first") in pairs
    assert ("second", "resp second") in pairs


def test_har_subscriber_error_handling(tmp_path):
    """Subscriber logs errors but doesn't crash."""
    har_path = tmp_path / "test.har"
    subscriber = HARRecordingSubscriber(str(har_path))

    # Send malformed event
    subscriber.on_event(("invalid_event_type", None, None, None))

    # Should not crash (may log to stderr but should continue)


def test_har_subscriber_incomplete_stream(tmp_path):
    """Subscriber handles incomplete streams gracefully (missing ResponseCompleteEvent)."""
    har_path = tmp_path / "test.har"
    subscriber = HARRecordingSubscriber(str(har_path))

    # Start a request but never complete it
    subscriber.on_event(RequestHeadersEvent(headers={}))
    subscriber.on_event(RequestBodyEvent(body={"model": "claude-3-opus-20240229"}))
    subscriber.on_event(ResponseHeadersEvent(status_code=200, headers={}))
    # No ResponseCompleteEvent

    # Close should still work
    subscriber.close()

    # No file should exist — no complete entries were committed
    assert not har_path.exists()

    # But events WERE received — diagnostic counters should reflect this
    assert subscriber._events_received["REQUEST_HEADERS"] == 1
    assert subscriber._events_received["REQUEST"] == 1


def test_har_subscriber_bounds_pending_requests(tmp_path, monkeypatch, capsys):
    """Incomplete pending requests are bounded by configured max."""
    monkeypatch.setenv("CC_DUMP_HAR_MAX_PENDING", "2")
    har_path = tmp_path / "test.har"
    subscriber = HARRecordingSubscriber(str(har_path))

    subscriber.on_event(RequestHeadersEvent(headers={"x-id": "1"}, request_id="req-1"))
    subscriber.on_event(RequestHeadersEvent(headers={"x-id": "2"}, request_id="req-2"))
    subscriber.on_event(RequestHeadersEvent(headers={"x-id": "3"}, request_id="req-3"))

    assert list(subscriber._pending_by_request.keys()) == ["req-2", "req-3"]
    captured = capsys.readouterr()
    assert "evicted incomplete pending request req-1" in captured.err


def test_har_subscriber_large_content(tmp_path):
    """Subscriber handles large content blocks."""
    har_path = tmp_path / "test.har"
    subscriber = HARRecordingSubscriber(str(har_path))

    large_text = "A" * 10000  # 10KB of text
    complete_message = _complete_msg(msg_id="msg_large", text=large_text)

    subscriber.on_event(RequestHeadersEvent(headers={}))
    subscriber.on_event(RequestBodyEvent(body={"model": "claude-3-opus-20240229"}))
    subscriber.on_event(ResponseHeadersEvent(status_code=200, headers={}))
    subscriber.on_event(ResponseCompleteEvent(body=complete_message))

    subscriber.close()

    # Verify file was written
    assert har_path.exists()
    with open(har_path, "r") as f:
        har = json.load(f)

    response_text = json.loads(har["log"]["entries"][0]["response"]["content"]["text"])
    assert response_text["content"][0]["text"] == large_text


def test_har_subscriber_progressive_saving(tmp_path):
    """Entries are written to disk BEFORE close() is called.

    This is the key invariant of progressive saving - entries appear on disk
    immediately after ResponseCompleteEvent, not buffered until close().
    """
    har_path = tmp_path / "test.har"
    subscriber = HARRecordingSubscriber(str(har_path))

    # First request/response cycle
    subscriber.on_event(RequestHeadersEvent(headers={}))
    subscriber.on_event(
        RequestBodyEvent(
            body={
                "model": "claude-3-opus-20240229",
                "messages": [{"role": "user", "content": "First"}],
            }
        )
    )
    subscriber.on_event(ResponseHeadersEvent(status_code=200, headers={}))
    subscriber.on_event(ResponseCompleteEvent(body=_complete_msg(msg_id="msg_1", text="Response 1")))

    # Verify first entry is on disk BEFORE close() - this is progressive saving
    assert har_path.exists()
    with open(har_path, "r") as f:
        har = json.load(f)
    assert len(har["log"]["entries"]) == 1
    assert (
        json.loads(har["log"]["entries"][0]["response"]["content"]["text"])["content"][
            0
        ]["text"]
        == "Response 1"
    )

    # Second request/response cycle
    subscriber.on_event(RequestHeadersEvent(headers={}))
    subscriber.on_event(
        RequestBodyEvent(
            body={
                "model": "claude-3-opus-20240229",
                "messages": [{"role": "user", "content": "Second"}],
            }
        )
    )
    subscriber.on_event(ResponseHeadersEvent(status_code=200, headers={}))
    subscriber.on_event(ResponseCompleteEvent(body=_complete_msg(msg_id="msg_2", text="Response 2")))

    # Verify second entry is on disk BEFORE close()
    with open(har_path, "r") as f:
        har = json.load(f)
    assert len(har["log"]["entries"]) == 2
    assert (
        json.loads(har["log"]["entries"][1]["response"]["content"]["text"])["content"][
            0
        ]["text"]
        == "Response 2"
    )

    # Finally close - this should be instant (no buffered writes)
    subscriber.close()

    # Verify file still valid after close
    with open(har_path, "r") as f:
        har = json.load(f)
    assert len(har["log"]["entries"]) == 2


def test_har_subscriber_close_deletes_empty_file_if_opened(tmp_path, capsys):
    """If file was somehow opened but has 0 entries, close() deletes it and logs FATAL."""
    har_path = tmp_path / "test.har"
    subscriber = HARRecordingSubscriber(str(har_path))

    # Force-open the file without committing any entries (simulates a bug)
    subscriber._open_file()
    assert har_path.exists()

    subscriber.close()

    # File should be deleted
    assert not har_path.exists()

    # FATAL message should be in stderr
    captured = capsys.readouterr()
    assert "FATAL" in captured.err
    assert "empty HAR file" in captured.err
    assert "test.har" in captured.err


def test_har_subscriber_no_file_no_events(tmp_path):
    """Session with zero events creates no file and no warnings."""
    har_path = tmp_path / "test.har"
    subscriber = HARRecordingSubscriber(str(har_path))
    subscriber.close()
    assert not har_path.exists()
    assert subscriber._events_received == {}


def test_har_subscriber_side_channel_metadata_annotation(tmp_path):
    """Side-channel markers annotate HAR entry with category metadata."""
    har_path = tmp_path / "test.har"
    subscriber = HARRecordingSubscriber(str(har_path))
    marker = (
        '<<CC_DUMP_SIDE_CHANNEL:{"run_id":"run-1","purpose":"block_summary",'
        '"source_session_id":"sess-1","prompt_version":"v1","policy_version":"redaction-v1"}>>\n'
    )

    subscriber.on_event(RequestHeadersEvent(headers={"content-type": "application/json"}))
    subscriber.on_event(
        RequestBodyEvent(
            body={
                "model": "claude-3-opus-20240229",
                "messages": [{"role": "user", "content": marker + "Summarize"}],
            }
        )
    )
    subscriber.on_event(ResponseHeadersEvent(status_code=200, headers={}))
    subscriber.on_event(ResponseCompleteEvent(body=_complete_msg(msg_id="msg_sc", text="ok")))
    subscriber.close()

    with open(har_path, "r") as f:
        har = json.load(f)
    entry = har["log"]["entries"][0]
    assert "cc-dump side-channel run=run-1 purpose=block_summary" in entry["comment"]
    assert "prompt_version=v1" in entry["comment"]
    assert "policy_version=redaction-v1" in entry["comment"]
    assert entry["_cc_dump"]["category"] == "side_channel"
    assert entry["_cc_dump"]["run_id"] == "run-1"
    assert entry["_cc_dump"]["purpose"] == "block_summary"
    assert entry["_cc_dump"]["prompt_version"] == "v1"
    assert entry["_cc_dump"]["policy_version"] == "redaction-v1"
    assert entry["_cc_dump"]["source_session_id"] == "sess-1"
