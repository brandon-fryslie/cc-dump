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
    ToolUseBlockStartEvent,
    Usage,
)
from cc_dump.domain_store import DomainStore
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


class TestEventHandlersRequestScopedStreaming:
    def test_request_hint_keeps_main_out_of_subagent_lane(self):
        main_session = "11111111-2222-3333-4444-555555555555"
        sub_session = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        state = {
            "positions": {},
            "known_hashes": {},
            "next_id": 0,
            "next_color": 0,
            "request_counter": 0,
            "current_session": main_session,
        }
        app_state = {"current_turn_usage_by_request": {}, "pending_request_headers": {}}
        widgets = _mk_widgets(_FakeConv(), _FakeStats(), _FakeViewStore(), DomainStore())
        log_fn = lambda *args, **kwargs: None

        event_handlers.handle_request(
            RequestBodyEvent(body=_req_body(sub_session), request_id="req-sub", seq=1, recv_ns=1),
            state,
            widgets,
            app_state,
            log_fn,
        )
        event_handlers.handle_request(
            RequestBodyEvent(body=_req_body(main_session), request_id="req-main", seq=1, recv_ns=2),
            state,
            widgets,
            app_state,
            log_fn,
        )

        reg = app_state["stream_registry"]
        sub_ctx = reg.get("req-sub")
        main_ctx = reg.get("req-main")
        assert sub_ctx is not None
        assert main_ctx is not None
        assert sub_ctx.agent_kind == "subagent"
        assert main_ctx.agent_kind == "main"

    def test_task_tool_use_event_promotes_main_lane(self):
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

        event_handlers.handle_request(
            RequestBodyEvent(
                body=_req_body("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
                request_id="req-sub-first",
                seq=1,
                recv_ns=1,
            ),
            state,
            widgets,
            app_state,
            log_fn,
        )
        event_handlers.handle_request(
            RequestBodyEvent(
                body=_req_body("11111111-2222-3333-4444-555555555555"),
                request_id="req-main",
                seq=1,
                recv_ns=2,
            ),
            state,
            widgets,
            app_state,
            log_fn,
        )
        event_handlers.handle_response_event(
            ResponseSSEEvent(
                sse_event=ToolUseBlockStartEvent(index=0, id="toolu_task_1", name="Task"),
                request_id="req-main",
                seq=2,
                recv_ns=3,
            ),
            state,
            widgets,
            app_state,
            log_fn,
        )

        reg = app_state["stream_registry"]
        sub_ctx = reg.get("req-sub-first")
        main_ctx = reg.get("req-main")
        assert sub_ctx is not None
        assert main_ctx is not None
        assert sub_ctx.agent_kind == "subagent"
        assert main_ctx.agent_kind == "main"

    def test_task_promotion_restamps_active_stream_blocks_and_chips(self):
        state = {
            "positions": {},
            "known_hashes": {},
            "next_id": 0,
            "next_color": 0,
            "request_counter": 0,
            "current_session": None,
        }
        app_state = {"current_turn_usage_by_request": {}, "pending_request_headers": {}}
        view_store = _FakeViewStore()
        domain_store = DomainStore()
        widgets = _mk_widgets(_FakeConv(), _FakeStats(), view_store, domain_store)
        log_fn = lambda *args, **kwargs: None

        req_sub = "req-sub-first"
        req_main = "req-main"
        sub_session = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        main_session = "11111111-2222-3333-4444-555555555555"

        event_handlers.handle_request(
            RequestBodyEvent(body=_req_body(sub_session), request_id=req_sub, seq=1, recv_ns=1),
            state,
            widgets,
            app_state,
            log_fn,
        )
        event_handlers.handle_request(
            RequestBodyEvent(body=_req_body(main_session), request_id=req_main, seq=1, recv_ns=2),
            state,
            widgets,
            app_state,
            log_fn,
        )

        for rid in (req_sub, req_main):
            event_handlers.handle_response_headers(
                ResponseHeadersEvent(status_code=200, headers={"content-type": "text/event-stream"}, request_id=rid, seq=2, recv_ns=3),
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
                    recv_ns=4,
                ),
                state,
                widgets,
                app_state,
                log_fn,
            )

        # Promotion trigger: Task tool_use from req_main.
        event_handlers.handle_response_event(
            ResponseSSEEvent(
                sse_event=ToolUseBlockStartEvent(index=0, id="toolu_task_1", name="Task"),
                request_id=req_main,
                seq=4,
                recv_ns=5,
            ),
            state,
            widgets,
            app_state,
            log_fn,
        )

        sub_blocks = domain_store.get_stream_blocks(req_sub)
        main_blocks = domain_store.get_stream_blocks(req_main)
        assert len(sub_blocks) > 0
        assert len(main_blocks) > 0

        # Existing active blocks are restamped without waiting for finalize.
        assert all(getattr(block, "agent_kind", "") == "subagent" for block in sub_blocks)
        assert all(getattr(block, "agent_kind", "") == "main" for block in main_blocks)

        chips = dict((rid, (label, kind)) for rid, label, kind in domain_store.get_active_stream_chips())
        assert chips[req_sub][1] == "subagent"
        assert chips[req_main][1] == "main"

        # Footer view-store mirrors updated chips.
        footer_active = view_store.values.get("streams:active")
        assert isinstance(footer_active, tuple)
        footer_map = dict((rid, kind) for rid, _label, kind in footer_active)
        assert footer_map[req_sub] == "subagent"
        assert footer_map[req_main] == "main"

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
