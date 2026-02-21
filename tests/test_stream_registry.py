"""Tests for request-scoped stream registry and lane classification."""

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
    def test_first_session_is_main(self):
        reg = StreamRegistry()
        ctx = reg.register_request("req-1", _body_with_session("11111111-2222-3333-4444-555555555555"))
        assert ctx.agent_kind == "main"
        assert ctx.agent_label == "main"
        assert ctx.lane_id == "main"

    def test_second_distinct_session_is_subagent(self):
        reg = StreamRegistry()
        _ = reg.register_request("req-1", _body_with_session("11111111-2222-3333-4444-555555555555"))
        ctx = reg.register_request("req-2", _body_with_session("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))
        assert ctx.agent_kind == "subagent"
        assert ctx.agent_label == "subagent 1"
        assert ctx.lane_id == "subagent-1"

    def test_same_session_reuses_lane(self):
        reg = StreamRegistry()
        first = reg.register_request("req-1", _body_with_session("11111111-2222-3333-4444-555555555555"))
        second = reg.register_request("req-2", _body_with_session("11111111-2222-3333-4444-555555555555"))
        assert second.lane_id == first.lane_id
        assert second.agent_kind == first.agent_kind
        assert second.agent_label == first.agent_label

    def test_missing_session_is_unknown(self):
        reg = StreamRegistry()
        ctx = reg.register_request("deadbeefcafebabe", {"metadata": {}})
        assert ctx.agent_kind == "unknown"
        assert ctx.agent_label.startswith("unknown ")
        assert ctx.lane_id.startswith("unknown-")

    def test_ensure_then_register_upgrades_unknown(self):
        reg = StreamRegistry()
        unknown = reg.ensure_context("req-1")
        assert unknown.agent_kind == "unknown"
        updated = reg.register_request("req-1", _body_with_session("11111111-2222-3333-4444-555555555555"))
        assert updated.agent_kind == "main"
