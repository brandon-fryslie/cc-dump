"""Deterministic smoke checks for cc-dump-d6u follow-up ticket (M1-M4).

These tests codify the previously manual checks from
plans/cc-dump-d6u-migrate-subscribers.md.
"""

from __future__ import annotations

import json
import queue
import time
from unittest.mock import MagicMock, patch

from cc_dump.analytics_store import AnalyticsStore
from cc_dump.event_types import (
    RequestBodyEvent,
    RequestHeadersEvent,
    ResponseCompleteEvent,
    ResponseDoneEvent,
    ResponseHeadersEvent,
)
from cc_dump.har_recorder import HARRecordingSubscriber
from cc_dump.har_replayer import convert_to_events
from cc_dump.proxy import EventQueueSink, _build_synthetic_sse_bytes, _fan_out_sse
from cc_dump.response_assembler import ResponseAssembler
from cc_dump.tmux_controller import TmuxController, TmuxState


def _build_live_stream_events(
    *,
    request_body: dict,
    response_text: str,
    request_id: str = "req-smoke-live",
) -> list:
    """Build a live-like event sequence from synthetic SSE bytes.

    // [LAW:one-source-of-truth] Complete response is assembled by ResponseAssembler,
    // matching the live proxy boundary behavior.
    """
    base_events = [
        RequestHeadersEvent(
            headers={"content-type": "application/json"},
            request_id=request_id,
            seq=0,
            recv_ns=time.monotonic_ns(),
        ),
        RequestBodyEvent(
            body=request_body,
            request_id=request_id,
            seq=1,
            recv_ns=time.monotonic_ns(),
        ),
        ResponseHeadersEvent(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            request_id=request_id,
            seq=0,
            recv_ns=time.monotonic_ns(),
        ),
    ]

    sse_bytes = _build_synthetic_sse_bytes(
        response_text=response_text,
        model=str(request_body.get("model", "synthetic")),
    )

    stream_queue: queue.Queue = queue.Queue()
    stream_sink = EventQueueSink(stream_queue, request_id=request_id, seq_start=0)
    assembler = ResponseAssembler()

    # // [LAW:dataflow-not-control-flow] Drive the same sink set and order every run.
    _fan_out_sse(
        sse_bytes.splitlines(keepends=True),
        [stream_sink, assembler],
    )

    stream_events = []
    while not stream_queue.empty():
        stream_events.append(stream_queue.get())

    # // [LAW:single-enforcer] ResponseCompleteEvent is emitted exactly once here.
    complete = ResponseCompleteEvent(
        body=assembler.result or {},
        request_id=request_id,
        seq=len(stream_events) + 1,
        recv_ns=time.monotonic_ns(),
    )
    done = ResponseDoneEvent(
        request_id=request_id,
        seq=len(stream_events) + 2,
        recv_ns=time.monotonic_ns(),
    )

    return [*base_events, *stream_events, complete, done]


def test_m1_live_proxy_analytics_budget_tokens_present():
    """M1: live proxy stream populates analytics token counts."""
    store = AnalyticsStore()
    request = {
        "model": "claude-sonnet-4",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
    }

    for event in _build_live_stream_events(
        request_body=request,
        response_text="streamed response",
    ):
        store.on_event(event)

    latest = store.get_latest_turn_stats()
    assert latest is not None
    assert latest["model"] == "claude-sonnet-4"
    assert latest["output_tokens"] > 0


def test_m2_live_proxy_har_capture_valid_entry(tmp_path):
    """M2: live proxy stream yields valid HAR entry with complete response payload."""
    har_path = tmp_path / "smoke.har"
    subscriber = HARRecordingSubscriber(str(har_path))
    request = {
        "model": "claude-sonnet-4",
        "messages": [{"role": "user", "content": "capture this"}],
        "stream": True,
    }

    for event in _build_live_stream_events(
        request_body=request,
        response_text="captured text",
    ):
        subscriber.on_event(event)
    subscriber.close()

    assert har_path.exists()
    with open(har_path, "r", encoding="utf-8") as f:
        har = json.load(f)
    assert len(har["log"]["entries"]) == 1

    entry = har["log"]["entries"][0]
    response_body = json.loads(entry["response"]["content"]["text"])
    assert response_body["type"] == "message"
    assert response_body["content"][0]["text"] == "captured text"


def test_m3_replay_parity_matches_live_analytics_projection():
    """M3: replay conversion produces analytics-equivalent turn data."""
    request = {
        "model": "claude-sonnet-4",
        "messages": [{"role": "user", "content": "parity please"}],
        "stream": True,
    }
    live_events = _build_live_stream_events(
        request_body=request,
        response_text="parity response",
    )

    live_store = AnalyticsStore()
    for event in live_events:
        live_store.on_event(event)

    complete_event = next(e for e in live_events if isinstance(e, ResponseCompleteEvent))
    replay_events = convert_to_events(
        request_headers={"content-type": "application/json"},
        request_body=request,
        response_status=200,
        response_headers={"content-type": "application/json"},
        complete_message=complete_event.body,
    )

    replay_store = AnalyticsStore()
    for event in replay_events:
        replay_store.on_event(event)

    assert replay_store.get_session_stats() == live_store.get_session_stats()
    assert replay_store.get_latest_turn_stats() == live_store.get_latest_turn_stats()


def test_m4_tmux_auto_zoom_request_then_end_turn():
    """M4: tmux auto-zoom zooms on request and unzooms on end_turn."""
    with patch.dict("os.environ", {}, clear=True):
        controller = TmuxController()

    pane = MagicMock()
    controller.state = TmuxState.CLAUDE_RUNNING
    controller.auto_zoom = True
    controller._our_pane = pane
    controller._claude_pane = MagicMock()

    controller.on_event(RequestBodyEvent(body={}))
    assert controller._is_zoomed is True

    controller.on_event(ResponseCompleteEvent(body={"stop_reason": "end_turn"}))
    assert controller._is_zoomed is False
