"""Tests for request-scoped streaming behavior in event handlers."""

from dataclasses import dataclass, field

from cc_dump.event_types import (
    MessageDeltaEvent,
    MessageInfo,
    MessageRole,
    MessageStartEvent,
    RequestBodyEvent,
    RequestHeadersEvent,
    ResponseDoneEvent,
    ResponseHeadersEvent,
    ResponseSSEEvent,
    StopReason,
    TextDeltaEvent,
    Usage,
)
from cc_dump.tui import event_handlers


@dataclass
class _FakeConv:
    stream_blocks: dict[str, list] = field(default_factory=dict)
    finalized: list[str] = field(default_factory=list)
    focused: str | None = None

    def add_turn(self, blocks, filters=None):
        _ = (blocks, filters)

    def begin_stream(self, request_id: str, stream_meta: dict | None = None):
        _ = stream_meta
        self.stream_blocks.setdefault(request_id, [])
        if self.focused is None:
            self.focused = request_id

    def append_stream_block(self, request_id: str, block, filters=None):
        _ = filters
        self.stream_blocks.setdefault(request_id, []).append(block)

    def finalize_stream(self, request_id: str):
        self.finalized.append(request_id)
        self.stream_blocks.pop(request_id, None)
        if self.focused == request_id:
            self.focused = next(iter(self.stream_blocks.keys()), None)
        return []

    def rerender(self, filters):
        _ = filters

    def get_active_stream_chips(self):
        return tuple((rid, rid[:8], "unknown") for rid in self.stream_blocks.keys())

    def get_focused_stream_id(self):
        return self.focused


@dataclass
class _FakeStats:
    models: list[str] = field(default_factory=list)

    def update_stats(self, **kwargs):
        model = kwargs.get("model")
        if model:
            self.models.append(model)

    def refresh_from_store(self, store, current_turn=None):
        _ = (store, current_turn)


@dataclass
class _FakeViewStore:
    values: dict[str, object] = field(default_factory=dict)

    def set(self, key: str, value: object):
        self.values[key] = value


def _mk_widgets(conv, stats, view_store):
    return {
        "conv": conv,
        "stats": stats,
        "filters": {},
        "refresh_callbacks": {},
        "analytics_store": object(),
        "view_store": view_store,
    }


def _req_body(session_id: str) -> dict:
    return {
        "model": "claude-sonnet-4-5-20250929",
        "stream": True,
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        "metadata": {
            "user_id": (
                "user_deadbeef_account_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_"
                f"session_{session_id}"
            )
        },
    }


class TestEventHandlersRequestScopedStreaming:
    def test_interleaved_stream_events_are_partitioned_by_request_id(self):
        state = {
            "positions": {},
            "known_hashes": {},
            "next_id": 0,
            "next_color": 0,
            "request_counter": 0,
            "current_session": None,
        }
        app_state = {"current_turn_usage_by_request": {}, "pending_request_headers": {}}
        conv = _FakeConv()
        stats = _FakeStats()
        view_store = _FakeViewStore()
        widgets = _mk_widgets(conv, stats, view_store)
        log_fn = lambda *args, **kwargs: None

        r1 = "req-111"
        r2 = "req-222"

        event_handlers.handle_request_headers(
            RequestHeadersEvent(headers={"content-type": "application/json"}, request_id=r1, seq=0, recv_ns=1),
            state,
            widgets,
            app_state,
            log_fn,
        )
        event_handlers.handle_request(
            RequestBodyEvent(body=_req_body("11111111-2222-3333-4444-555555555555"), request_id=r1, seq=1, recv_ns=2),
            state,
            widgets,
            app_state,
            log_fn,
        )
        event_handlers.handle_request_headers(
            RequestHeadersEvent(headers={"content-type": "application/json"}, request_id=r2, seq=0, recv_ns=3),
            state,
            widgets,
            app_state,
            log_fn,
        )
        event_handlers.handle_request(
            RequestBodyEvent(body=_req_body("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"), request_id=r2, seq=1, recv_ns=4),
            state,
            widgets,
            app_state,
            log_fn,
        )

        for rid in (r1, r2):
            event_handlers.handle_response_headers(
                ResponseHeadersEvent(status_code=200, headers={"content-type": "text/event-stream"}, request_id=rid, seq=2, recv_ns=5),
                state,
                widgets,
                app_state,
                log_fn,
            )
            event_handlers.handle_response_event(
                ResponseSSEEvent(
                    sse_event=MessageStartEvent(
                        MessageInfo(
                            id=f"msg-{rid}",
                            role=MessageRole.ASSISTANT,
                            model="claude-sonnet-4-5-20250929",
                            usage=Usage(input_tokens=1),
                        )
                    ),
                    request_id=rid,
                    seq=3,
                    recv_ns=6,
                ),
                state,
                widgets,
                app_state,
                log_fn,
            )

        # Interleaved text deltas
        event_handlers.handle_response_event(
            ResponseSSEEvent(
                sse_event=TextDeltaEvent(index=0, text="A"),
                request_id=r1,
                seq=4,
                recv_ns=7,
            ),
            state,
            widgets,
            app_state,
            log_fn,
        )
        event_handlers.handle_response_event(
            ResponseSSEEvent(
                sse_event=TextDeltaEvent(index=0, text="B"),
                request_id=r2,
                seq=4,
                recv_ns=8,
            ),
            state,
            widgets,
            app_state,
            log_fn,
        )
        event_handlers.handle_response_event(
            ResponseSSEEvent(
                sse_event=MessageDeltaEvent(stop_reason=StopReason.END_TURN, stop_sequence="", output_tokens=2),
                request_id=r1,
                seq=5,
                recv_ns=9,
            ),
            state,
            widgets,
            app_state,
            log_fn,
        )
        event_handlers.handle_response_event(
            ResponseSSEEvent(
                sse_event=MessageDeltaEvent(stop_reason=StopReason.END_TURN, stop_sequence="", output_tokens=3),
                request_id=r2,
                seq=5,
                recv_ns=10,
            ),
            state,
            widgets,
            app_state,
            log_fn,
        )

        assert len(conv.stream_blocks[r1]) > 0
        assert len(conv.stream_blocks[r2]) > 0
        assert set(conv.stream_blocks.keys()) == {r1, r2}

        # Finalize one request: only that stream is removed/finalized.
        event_handlers.handle_response_done(
            ResponseDoneEvent(request_id=r1, seq=6, recv_ns=11),
            state,
            widgets,
            app_state,
            log_fn,
        )
        assert conv.finalized == [r1]
        assert r1 not in conv.stream_blocks
        assert r2 in conv.stream_blocks

        event_handlers.handle_response_done(
            ResponseDoneEvent(request_id=r2, seq=6, recv_ns=12),
            state,
            widgets,
            app_state,
            log_fn,
        )
        assert conv.finalized == [r1, r2]
        assert conv.stream_blocks == {}
