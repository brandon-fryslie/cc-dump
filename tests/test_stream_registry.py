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


def _body_with_task_result_lineage(session_id: str, task_tool_use_id: str) -> dict:
    body = _body_with_session(session_id)
    body["messages"] = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": task_tool_use_id,
                    "name": "Task",
                    "input": {"description": "do work", "prompt": "run"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": task_tool_use_id,
                    "content": "task output",
                }
            ],
        },
    ]
    return body


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

    def test_task_tool_use_promotes_request_session_to_main(self):
        reg = StreamRegistry()
        first = reg.register_request("req-sub-first", _body_with_session("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))
        assert first.agent_kind == "main"

        second = reg.register_request("req-main", _body_with_session("11111111-2222-3333-4444-555555555555"))
        assert second.agent_kind == "subagent"

        promoted = reg.note_task_tool_use("req-main", "toolu_task_1")
        assert promoted.agent_kind == "main"
        assert promoted.lane_id == "main"

        relabeled_first = reg.get("req-sub-first")
        assert relabeled_first is not None
        assert relabeled_first.agent_kind == "subagent"

    def test_task_result_lineage_promotes_main_session(self):
        reg = StreamRegistry()
        _ = reg.register_request("req-sub-first", _body_with_session("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))

        main = reg.register_request(
            "req-main",
            _body_with_task_result_lineage(
                "11111111-2222-3333-4444-555555555555",
                "toolu_task_1",
            ),
        )
        assert main.agent_kind == "main"
        assert main.lane_id == "main"

        sub = reg.get("req-sub-first")
        assert sub is not None
        assert sub.agent_kind == "subagent"

    def test_task_tool_use_before_request_registration_promotes_when_session_arrives(self):
        reg = StreamRegistry()
        _ = reg.register_request(
            "req-sub-first",
            _body_with_session("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        )
        pending = reg.note_task_tool_use("req-main", "toolu_task_1")
        assert pending.agent_kind == "unknown"

        promoted = reg.register_request(
            "req-main",
            _body_with_session("11111111-2222-3333-4444-555555555555"),
        )
        assert promoted.agent_kind == "main"
        assert promoted.lane_id == "main"

        sub = reg.get("req-sub-first")
        assert sub is not None
        assert sub.agent_kind == "subagent"
