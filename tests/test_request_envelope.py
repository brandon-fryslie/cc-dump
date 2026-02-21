"""Tests for request envelope metadata (request_id, seq, recv_ns) on pipeline events.

Proves:
- Metadata fields exist with correct defaults on all PipelineEvent types
- Metadata can be set via keyword args (backward compatible)
- Events are frozen — metadata can't be mutated
- EventQueueSink emits monotonic seq and recv_ns within a request_id
- Synthetic response path emits ordered metadata
- Replay path emits metadata
"""

import queue
import time

import pytest

from cc_dump.event_types import (
    ErrorEvent,
    LogEvent,
    MessageStopEvent,
    PipelineEvent,
    ProxyErrorEvent,
    RequestBodyEvent,
    RequestHeadersEvent,
    ResponseDoneEvent,
    ResponseHeadersEvent,
    ResponseNonStreamingEvent,
    ResponseSSEEvent,
    parse_sse_event,
)
from cc_dump.proxy import EventQueueSink


# ─── Default metadata ────────────────────────────────────────────────────────


class TestMetadataDefaults:
    """All PipelineEvent types get request_id='', seq=0, recv_ns=0 by default."""

    @pytest.mark.parametrize(
        "event",
        [
            RequestHeadersEvent(headers={}),
            RequestBodyEvent(body={}),
            ResponseHeadersEvent(status_code=200, headers={}),
            ResponseSSEEvent(sse_event=MessageStopEvent()),
            ResponseNonStreamingEvent(status_code=200, headers={}, body={}),
            ResponseDoneEvent(),
            ErrorEvent(code=500, reason="err"),
            ProxyErrorEvent(error="fail"),
            LogEvent(method="POST", path="/v1/messages", status="200"),
        ],
        ids=lambda e: type(e).__name__,
    )
    def test_defaults(self, event):
        assert event.request_id == ""
        assert event.seq == 0
        assert event.recv_ns == 0
        assert isinstance(event, PipelineEvent)


# ─── Explicit metadata ───────────────────────────────────────────────────────


class TestMetadataExplicit:
    """Metadata can be set via keyword args on construction."""

    def test_response_headers_with_metadata(self):
        evt = ResponseHeadersEvent(
            status_code=200,
            headers={},
            request_id="abc123",
            seq=0,
            recv_ns=999,
        )
        assert evt.request_id == "abc123"
        assert evt.seq == 0
        assert evt.recv_ns == 999

    def test_response_sse_with_metadata(self):
        evt = ResponseSSEEvent(
            sse_event=MessageStopEvent(),
            request_id="def456",
            seq=5,
            recv_ns=12345,
        )
        assert evt.request_id == "def456"
        assert evt.seq == 5
        assert evt.recv_ns == 12345

    def test_response_done_with_metadata(self):
        evt = ResponseDoneEvent(
            request_id="ghi789",
            seq=10,
            recv_ns=67890,
        )
        assert evt.request_id == "ghi789"
        assert evt.seq == 10

    def test_error_with_metadata(self):
        evt = ErrorEvent(
            code=500,
            reason="fail",
            request_id="err01",
            recv_ns=111,
        )
        assert evt.request_id == "err01"

    def test_frozen_metadata(self):
        evt = ResponseDoneEvent(request_id="frozen", seq=1, recv_ns=1)
        with pytest.raises(AttributeError):
            evt.request_id = "changed"
        with pytest.raises(AttributeError):
            evt.seq = 99


# ─── EventQueueSink ordering ─────────────────────────────────────────────────


class TestEventQueueSinkMetadata:
    """EventQueueSink emits events with monotonic seq and recv_ns."""

    @staticmethod
    def _make_sse_data(event_type: str, data: dict) -> tuple[str, dict]:
        """Return (event_type, raw_data) pair for sink.on_event()."""
        return event_type, data

    def test_seq_monotonic(self):
        q = queue.Queue()
        sink = EventQueueSink(q, request_id="req-1", seq_start=0)

        # Emit several SSE events (on_done is a no-op — proxy emits ResponseDoneEvent explicitly)
        sink.on_event("message_start", {
            "type": "message_start",
            "message": {"id": "msg_1", "role": "assistant", "model": "test", "usage": {}},
        })
        sink.on_event("content_block_start", {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        })
        sink.on_event("content_block_delta", {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello"},
        })
        sink.on_event("content_block_stop", {
            "type": "content_block_stop",
            "index": 0,
        })
        sink.on_event("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 1},
        })
        sink.on_event("message_stop", {"type": "message_stop"})
        sink.on_done()  # no-op

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        assert len(events) == 6  # 6 SSE events only

        # All share the same request_id
        for evt in events:
            assert evt.request_id == "req-1"

        # seq is strictly monotonic starting from 1
        seqs = [evt.seq for evt in events]
        assert seqs == list(range(1, 7))

        # recv_ns is monotonically non-decreasing
        timestamps = [evt.recv_ns for evt in events]
        for i in range(1, len(timestamps)):
            assert timestamps[i] >= timestamps[i - 1]

    def test_request_id_propagated(self):
        q = queue.Queue()
        sink = EventQueueSink(q, request_id="unique-42")
        sink.on_event("message_stop", {"type": "message_stop"})
        sink.on_done()  # no-op

        evt1 = q.get_nowait()
        assert evt1.request_id == "unique-42"
        assert q.empty()  # on_done is a no-op — no second event

    def test_unknown_event_type_skipped(self):
        """Unknown SSE event types are silently skipped (no metadata emitted)."""
        q = queue.Queue()
        sink = EventQueueSink(q, request_id="req-skip")
        sink.on_event("ping", {})  # unknown type
        sink.on_done()  # no-op

        # Queue should be empty — ping was skipped and on_done is a no-op
        assert q.empty()

    def test_recv_ns_is_recent(self):
        """recv_ns should be a monotonic nanosecond timestamp, not zero."""
        q = queue.Queue()
        before = time.monotonic_ns()
        sink = EventQueueSink(q, request_id="ts-test")
        sink.on_event("message_stop", {"type": "message_stop"})
        after = time.monotonic_ns()

        evt = q.get_nowait()
        assert evt.recv_ns >= before
        assert evt.recv_ns <= after


# ─── Replay path ─────────────────────────────────────────────────────────────


class TestReplayMetadata:
    """Replay events carry metadata."""

    def test_convert_to_events_has_metadata(self):
        from cc_dump.har_replayer import convert_to_events

        events = convert_to_events(
            request_headers={"x-test": "1"},
            request_body={"model": "test"},
            response_status=200,
            response_headers={},
            complete_message={"type": "message", "id": "msg_1", "content": []},
        )

        # Find the ResponseNonStreamingEvent
        resp_events = [e for e in events if isinstance(e, ResponseNonStreamingEvent)]
        assert len(resp_events) == 1

        resp = resp_events[0]
        assert resp.request_id != ""  # UUID hex, not empty
        assert len(resp.request_id) == 32  # UUID hex length
        assert resp.seq == 2
        assert resp.recv_ns > 0

    def test_request_events_have_envelope_metadata(self):
        from cc_dump.har_replayer import convert_to_events

        events = convert_to_events(
            request_headers={},
            request_body={"model": "test"},
            response_status=200,
            response_headers={},
            complete_message={"type": "message", "id": "msg_1", "content": []},
        )

        req_events = [e for e in events if isinstance(e, (RequestHeadersEvent, RequestBodyEvent))]
        assert len(req_events) == 2
        assert req_events[0].request_id
        assert req_events[0].request_id == req_events[1].request_id
        assert req_events[0].seq == 0
        assert req_events[1].seq == 1
        assert req_events[0].recv_ns > 0
        assert req_events[1].recv_ns > 0
