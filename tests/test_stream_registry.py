"""Tests for request-scoped stream registry."""

from cc_dump.tui.stream_registry import StreamRegistry


def _body_with_session(session_id: str) -> dict:
    return {
        "metadata": {
            "user_id": (
                "user_deadbeef_account_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_"
                f"session_{session_id}"
            )
        }
    }


class TestStreamRegistry:
    def test_register_request_extracts_session_id(self):
        reg = StreamRegistry()
        ctx = reg.register_request("req-1", _body_with_session("11111111-2222-3333-4444-555555555555"))
        assert ctx.session_id == "11111111-2222-3333-4444-555555555555"

    def test_register_request_no_session_gives_empty(self):
        reg = StreamRegistry()
        ctx = reg.register_request("req-1", {"metadata": {}})
        assert ctx.session_id == ""

    def test_ensure_context_creates_empty_context(self):
        reg = StreamRegistry()
        ctx = reg.ensure_context("req-unknown")
        assert ctx.request_id == "req-unknown"
        assert ctx.session_id == ""

    def test_mark_streaming_updates_state(self):
        reg = StreamRegistry()
        ctx = reg.mark_streaming("req-1")
        assert ctx.state == "streaming"

    def test_mark_done_updates_state(self):
        reg = StreamRegistry()
        ctx = reg.mark_done("req-1")
        assert ctx.state == "done"

    def test_get_returns_registered_context(self):
        reg = StreamRegistry()
        reg.register_request("req-1", _body_with_session("11111111-2222-3333-4444-555555555555"))
        ctx = reg.get("req-1")
        assert ctx is not None
        assert ctx.session_id == "11111111-2222-3333-4444-555555555555"

    def test_get_returns_none_for_unknown(self):
        reg = StreamRegistry()
        assert reg.get("req-unknown") is None

    def test_session_hint_used_when_no_inline_session(self):
        reg = StreamRegistry()
        ctx = reg.register_request("req-1", {}, session_hint="hint-session-id")
        assert ctx.session_id == "hint-session-id"
