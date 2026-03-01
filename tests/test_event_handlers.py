"""Tests for request-scoped streaming behavior in event handlers."""

from dataclasses import dataclass, field

from cc_dump.pipeline.event_types import (
    MessageDeltaEvent,
    MessageInfo,
    MessageRole,
    MessageStartEvent,
    RequestBodyEvent,
    RequestHeadersEvent,
    ResponseCompleteEvent,
    ResponseDoneEvent,
    ResponseHeadersEvent,
    ResponseSSEEvent,
    StopReason,
    TextDeltaEvent,
    Usage,
)
from cc_dump.app.domain_store import DomainStore
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

    def get_focused_stream_id(self):
        return self.focused


@dataclass
class _FakeStats:
    models: list[str] = field(default_factory=list)

    def update_stats(self, **kwargs):
        model = kwargs.get("model")
        if model:
            self.models.append(model)

    def refresh_from_store(self, store, current_turn=None, **kwargs):
        _ = (store, current_turn, kwargs)


@dataclass
class _FakeViewStore:
    values: dict[str, object] = field(default_factory=dict)

    def set(self, key: str, value: object):
        self.values[key] = value


def _mk_widgets(conv, stats, view_store, domain_store=None):
    return {
        "conv": conv,
        "stats": stats,
        "filters": {},
        "refresh_callbacks": {},
        "analytics_store": object(),
        "view_store": view_store,
        "domain_store": domain_store or DomainStore(),
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


def _complete_response(text: str, *, msg_id: str, model: str = "claude-sonnet-4-5-20250929") -> dict:
    return {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": model,
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _walk_blocks(blocks):
    for block in blocks:
        yield block
        yield from _walk_blocks(getattr(block, "children", []))


def _turn_text(blocks) -> str:
    return "".join(
        block.content
        for block in _walk_blocks(blocks)
        if isinstance(getattr(block, "content", None), str)
    )


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
        domain_store = DomainStore()
        widgets = _mk_widgets(conv, stats, view_store, domain_store)
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

        assert len(domain_store._stream_turns[r1]) > 0
        assert len(domain_store._stream_turns[r2]) > 0
        assert set(domain_store._stream_turns.keys()) == {r1, r2}

        # Finalize one request: only that stream is removed/finalized.
        event_handlers.handle_response_done(
            ResponseDoneEvent(request_id=r1, seq=6, recv_ns=11),
            state,
            widgets,
            app_state,
            log_fn,
        )
        assert r1 not in domain_store._stream_turns
        assert r2 in domain_store._stream_turns
        # r1 finalized → blocks moved to completed
        assert domain_store.completed_count >= 3  # 2 request turns + 1 finalized

        event_handlers.handle_response_done(
            ResponseDoneEvent(request_id=r2, seq=6, recv_ns=12),
            state,
            widgets,
            app_state,
            log_fn,
        )
        assert domain_store._stream_turns == {}
        assert domain_store.completed_count >= 4  # both streams finalized

    def test_response_complete_finalizes_stream_before_done(self):
        state = {
            "positions": {},
            "known_hashes": {},
            "next_id": 0,
            "next_color": 0,
            "request_counter": 0,
            "current_session": None,
        }
        app_state = {"current_turn_usage_by_request": {}, "pending_request_headers": {}}
        widgets = _mk_widgets(_FakeConv(), _FakeStats(), _FakeViewStore(), DomainStore())
        log_fn = lambda *args, **kwargs: None

        rid = "req-1"
        event_handlers.handle_request(
            RequestBodyEvent(
                body=_req_body("11111111-2222-3333-4444-555555555555"),
                request_id=rid,
                seq=1,
                recv_ns=1,
            ),
            state,
            widgets,
            app_state,
            log_fn,
        )
        event_handlers.handle_response_headers(
            ResponseHeadersEvent(status_code=200, headers={"content-type": "text/event-stream"}, request_id=rid, seq=2, recv_ns=2),
            state,
            widgets,
            app_state,
            log_fn,
        )
        event_handlers.handle_response_event(
            ResponseSSEEvent(
                sse_event=TextDeltaEvent(index=0, text="stream delta"),
                request_id=rid,
                seq=3,
                recv_ns=3,
            ),
            state,
            widgets,
            app_state,
            log_fn,
        )

        completed_before = widgets["domain_store"].completed_count
        event_handlers.handle_response_complete(
            ResponseCompleteEvent(
                body={
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "canonical final"}],
                    "model": "claude-sonnet-4-5-20250929",
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
                request_id=rid,
                seq=4,
                recv_ns=4,
            ),
            state,
            widgets,
            app_state,
            log_fn,
        )

        ds = widgets["domain_store"]
        assert rid not in ds._stream_turns
        assert ds.completed_count == completed_before + 1
        response_turn = ds.iter_completed_blocks()[-1]
        def _walk(blocks):
            for block in blocks:
                yield block
                yield from _walk(getattr(block, "children", []))
        assert any(getattr(block, "content", "") == "canonical final" for block in _walk(response_turn))

        event_handlers.handle_response_done(
            ResponseDoneEvent(request_id=rid, seq=5, recv_ns=5),
            state,
            widgets,
            app_state,
            log_fn,
        )
        assert ds.completed_count == completed_before + 1

    def test_three_interleaved_streams_finalize_out_of_order_without_cross_talk(self):
        state = {
            "positions": {},
            "known_hashes": {},
            "next_id": 0,
            "next_color": 0,
            "request_counter": 0,
            "current_session": None,
        }
        app_state = {"current_turn_usage_by_request": {}, "pending_request_headers": {}}
        widgets = _mk_widgets(_FakeConv(), _FakeStats(), _FakeViewStore(), DomainStore())
        domain_store = widgets["domain_store"]
        log_fn = lambda *args, **kwargs: None

        requests = [
            ("req-a", "11111111-2222-3333-4444-555555555555"),
            ("req-b", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
            ("req-c", "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"),
        ]
        for idx, (rid, session_id) in enumerate(requests, start=1):
            event_handlers.handle_request_headers(
                RequestHeadersEvent(
                    headers={"content-type": "application/json"},
                    request_id=rid,
                    seq=0,
                    recv_ns=idx,
                ),
                state,
                widgets,
                app_state,
                log_fn,
            )
            event_handlers.handle_request(
                RequestBodyEvent(
                    body=_req_body(session_id),
                    request_id=rid,
                    seq=1,
                    recv_ns=idx + 10,
                ),
                state,
                widgets,
                app_state,
                log_fn,
            )
            event_handlers.handle_response_headers(
                ResponseHeadersEvent(
                    status_code=200,
                    headers={"content-type": "text/event-stream"},
                    request_id=rid,
                    seq=2,
                    recv_ns=idx + 20,
                ),
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
                    recv_ns=idx + 30,
                ),
                state,
                widgets,
                app_state,
                log_fn,
            )
            event_handlers.handle_response_event(
                ResponseSSEEvent(
                    sse_event=TextDeltaEvent(index=0, text=f"temp-{rid}"),
                    request_id=rid,
                    seq=4,
                    recv_ns=idx + 40,
                ),
                state,
                widgets,
                app_state,
                log_fn,
            )

        assert set(domain_store.get_active_stream_ids()) == {"req-a", "req-b", "req-c"}

        # // [LAW:single-enforcer] Out-of-order completion still finalizes per request_id only.
        completion_order = [("req-b", "final-b"), ("req-c", "final-c"), ("req-a", "final-a")]
        for idx, (rid, text) in enumerate(completion_order, start=1):
            event_handlers.handle_response_complete(
                ResponseCompleteEvent(
                    body=_complete_response(text, msg_id=f"msg-final-{rid}"),
                    request_id=rid,
                    seq=10 + idx,
                    recv_ns=100 + idx,
                ),
                state,
                widgets,
                app_state,
                log_fn,
            )
            remaining = {"req-a", "req-b", "req-c"} - {item[0] for item in completion_order[:idx]}
            assert set(domain_store.get_active_stream_ids()) == remaining

        assert domain_store.get_active_stream_ids() == ()
        response_turns = [
            turn
            for turn in domain_store.iter_completed_blocks()
            if _turn_text(turn).startswith("final-")
        ]
        response_payloads = sorted(_turn_text(turn) for turn in response_turns)
        assert response_payloads == ["final-a", "final-b", "final-c"]
        assert all("temp-" not in payload for payload in response_payloads)
