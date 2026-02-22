"""Tests for AnalyticsStore."""

import pytest

from cc_dump.analytics_store import AnalyticsStore, TurnRecord, ToolInvocationRecord
from cc_dump.analysis import ToolEconomicsRow
from cc_dump.event_types import (
    RequestBodyEvent,
    ResponseCompleteEvent,
)


def _complete(body: dict) -> ResponseCompleteEvent:
    """Build a ResponseCompleteEvent with sensible defaults."""
    return ResponseCompleteEvent(body=body)


# ─── Basic Event Handling Tests ────────────────────────────────────────────────


def test_store_accumulates_turn():
    """Store accumulates request/response events into a turn."""
    store = AnalyticsStore()

    # Simulate a request/response cycle
    request = {
        "model": "claude-sonnet-4",
        "messages": [{"role": "user", "content": "Hello"}],
    }

    store.on_event(RequestBodyEvent(body=request))
    store.on_event(_complete({
        "model": "claude-sonnet-4",
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "stop_reason": "end_turn",
    }))

    # Verify turn was recorded
    assert len(store._turns) == 1
    turn = store._turns[0]
    assert turn.sequence_num == 1
    assert turn.model == "claude-sonnet-4"
    assert turn.stop_reason == "end_turn"
    assert turn.input_tokens == 100
    assert turn.output_tokens == 50


def test_store_populates_token_counts():
    """Store populates token counts for tool invocations."""
    store = AnalyticsStore()

    # Simulate a request with a tool use
    request = {
        "model": "claude-sonnet-4",
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool_abc123",
                        "name": "Read",
                        "input": {"file_path": "/path/to/file.txt"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool_abc123",
                        "content": "This is the file content with multiple words that will be tokenized.",
                    }
                ],
            },
        ],
    }

    store.on_event(RequestBodyEvent(body=request))
    store.on_event(_complete({
        "model": "claude-sonnet-4",
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "stop_reason": "end_turn",
    }))

    # Verify tool invocation was recorded
    assert len(store._turns) == 1
    turn = store._turns[0]
    assert len(turn.tool_invocations) == 1

    inv = turn.tool_invocations[0]
    assert inv.tool_name == "Read"
    assert inv.input_tokens > 0
    assert inv.result_tokens > 0

    # Token counts should be reasonable
    assert 3 <= inv.input_tokens <= 15
    assert 10 <= inv.result_tokens <= 25


def test_store_handles_empty_tool_inputs():
    """Token counting handles empty/minimal strings gracefully."""
    store = AnalyticsStore()

    request = {
        "model": "claude-sonnet-4",
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool_xyz",
                        "name": "Bash",
                        "input": {},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tool_xyz", "content": ""}
                ],
            },
        ],
    }

    store.on_event(RequestBodyEvent(body=request))
    store.on_event(_complete({
        "model": "claude-sonnet-4",
        "usage": {},
        "stop_reason": "",
    }))

    assert len(store._turns[0].tool_invocations) == 1
    inv = store._turns[0].tool_invocations[0]
    assert inv.input_tokens >= 0
    assert inv.result_tokens == 0


def test_store_handles_multiple_tools():
    """Token counting works for multiple tool invocations in one turn."""
    store = AnalyticsStore()

    request = {
        "model": "claude-sonnet-4",
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tool_1", "name": "Read", "input": {"file": "a.txt"}},
                    {"type": "tool_use", "id": "tool_2", "name": "Write", "input": {"file": "b.txt", "content": "hello world"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tool_1", "content": "short"},
                    {"type": "tool_result", "tool_use_id": "tool_2", "content": "longer result with more text"},
                ],
            },
        ],
    }

    store.on_event(RequestBodyEvent(body=request))
    store.on_event(_complete({
        "model": "claude-sonnet-4",
        "usage": {},
        "stop_reason": "",
    }))

    assert len(store._turns[0].tool_invocations) == 2

    # Find each tool
    invs = sorted(store._turns[0].tool_invocations, key=lambda x: x.tool_name)
    read_inv = invs[0]
    write_inv = invs[1]

    assert read_inv.tool_name == "Read"
    assert read_inv.input_tokens > 0
    assert read_inv.result_tokens > 0

    assert write_inv.tool_name == "Write"
    assert write_inv.input_tokens > 0
    assert write_inv.result_tokens > 0

    # Write tool should have more input tokens (has content field)
    assert write_inv.input_tokens > read_inv.input_tokens


# ─── Query Method Tests ────────────────────────────────────────────────────────


def test_get_session_stats_empty():
    """Empty store returns zeros."""
    store = AnalyticsStore()
    stats = store.get_session_stats()

    assert stats["input_tokens"] == 0
    assert stats["output_tokens"] == 0
    assert stats["cache_read_tokens"] == 0
    assert stats["cache_creation_tokens"] == 0


def test_get_session_stats_with_data():
    """Session stats sum across all turns."""
    store = AnalyticsStore()

    # Create turns with different token counts
    store._turns = [
        TurnRecord(
            sequence_num=1,
            model="claude-sonnet-4",
            stop_reason="end_turn",
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=200,
            cache_creation_tokens=50,
            request_json="{}",
        ),
        TurnRecord(
            sequence_num=2,
            model="claude-sonnet-4",
            stop_reason="end_turn",
            input_tokens=150,
            output_tokens=75,
            cache_read_tokens=300,
            cache_creation_tokens=25,
            request_json="{}",
        ),
    ]

    stats = store.get_session_stats()

    assert stats["input_tokens"] == 250
    assert stats["output_tokens"] == 125
    assert stats["cache_read_tokens"] == 500
    assert stats["cache_creation_tokens"] == 75


def test_get_latest_turn_stats_empty():
    """Empty store returns None."""
    store = AnalyticsStore()
    assert store.get_latest_turn_stats() is None


def test_get_latest_turn_stats_with_data():
    """Latest turn stats returns most recent turn."""
    store = AnalyticsStore()

    store._turns = [
        TurnRecord(
            sequence_num=1,
            model="claude-sonnet-4",
            stop_reason="end_turn",
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=200,
            cache_creation_tokens=50,
            request_json="{}",
        ),
        TurnRecord(
            sequence_num=2,
            model="claude-haiku-4",
            stop_reason="end_turn",
            input_tokens=150,
            output_tokens=75,
            cache_read_tokens=300,
            cache_creation_tokens=25,
            request_json="{}",
        ),
    ]

    latest = store.get_latest_turn_stats()

    assert latest["sequence_num"] == 2
    assert latest["model"] == "claude-haiku-4"
    assert latest["input_tokens"] == 150
    assert latest["output_tokens"] == 75


# ─── Unified Analytics Dashboard Snapshot Tests ───────────────────────────────


def test_get_dashboard_snapshot_empty():
    """Empty store yields zeroed summary and no timeline/model rows."""
    store = AnalyticsStore()
    snapshot = store.get_dashboard_snapshot()

    summary = snapshot["summary"]
    assert summary["turn_count"] == 0
    assert summary["input_tokens"] == 0
    assert summary["output_tokens"] == 0
    assert summary["cache_read_tokens"] == 0
    assert summary["cache_creation_tokens"] == 0
    assert summary["total_tokens"] == 0
    assert summary["cost_usd"] == 0.0
    assert summary["cache_savings_usd"] == 0.0
    assert summary["active_model_count"] == 0
    assert snapshot["timeline"] == []
    assert snapshot["models"] == []


def test_get_dashboard_snapshot_aggregates_real_usage_fields():
    """Snapshot aggregates summary/timeline/models from canonical turn usage fields."""
    store = setup_test_store()
    snapshot = store.get_dashboard_snapshot()

    summary = snapshot["summary"]
    # setup_test_store totals:
    # input=1500, output=700, cache_read=3000, cache_creation=0
    assert summary["turn_count"] == 2
    assert summary["input_tokens"] == 1500
    assert summary["output_tokens"] == 700
    assert summary["cache_read_tokens"] == 3000
    assert summary["cache_creation_tokens"] == 0
    assert summary["input_total"] == 4500
    assert summary["total_tokens"] == 5200
    assert summary["cache_pct"] == pytest.approx(66.666, abs=0.1)
    assert summary["cache_savings_usd"] > 0.0
    assert summary["active_model_count"] == 2
    assert summary["latest_model_label"] == "Haiku 4"

    timeline = snapshot["timeline"]
    assert len(timeline) == 2
    assert timeline[0]["sequence_num"] == 1
    assert timeline[0]["delta_input"] == 0
    # Turn 2 input_total = 1500, turn 1 input_total = 3000 -> delta -1500
    assert timeline[1]["delta_input"] == -1500

    models = snapshot["models"]
    assert len(models) == 2
    labels = {row["model_label"] for row in models}
    assert "Sonnet 4" in labels
    assert "Haiku 4" in labels
    assert all(row["turns"] == 1 for row in models)
    assert pytest.approx(sum(row["token_share_pct"] for row in models), abs=0.01) == 100.0


def test_get_dashboard_snapshot_merges_current_turn():
    """In-progress current_turn is merged as synthetic tail row."""
    store = setup_test_store()
    snapshot = store.get_dashboard_snapshot(
        current_turn={
            "model": "claude-sonnet-4",
            "input_tokens": 200,
            "output_tokens": 100,
            "cache_read_tokens": 300,
            "cache_creation_tokens": 10,
        }
    )

    summary = snapshot["summary"]
    assert summary["turn_count"] == 3
    assert summary["input_tokens"] == 1700
    assert summary["output_tokens"] == 800
    assert summary["cache_read_tokens"] == 3300
    assert summary["cache_creation_tokens"] == 10

    tail = snapshot["timeline"][-1]
    assert tail["sequence_num"] == 3
    assert tail["model"] == "claude-sonnet-4"
    assert tail["input_total"] == 500


# ─── Tool Economics Query Tests ────────────────────────────────────────────────


def setup_test_store() -> AnalyticsStore:
    """Create a store with test data."""
    store = AnalyticsStore()

    # Turn 1: Sonnet model with Read and Bash tools
    store._turns.append(
        TurnRecord(
            sequence_num=1,
            model="claude-sonnet-4",
            stop_reason="end_turn",
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=2000,
            cache_creation_tokens=0,
            request_json="{}",
            tool_invocations=[
                ToolInvocationRecord(
                    tool_name="Read",
                    tool_use_id="tool_1",
                    input_tokens=600,
                    result_tokens=1000,
                    is_error=False,
                ),
                ToolInvocationRecord(
                    tool_name="Bash",
                    tool_use_id="tool_2",
                    input_tokens=400,
                    result_tokens=500,
                    is_error=False,
                ),
            ],
        )
    )

    # Turn 2: Haiku model with Write tool
    store._turns.append(
        TurnRecord(
            sequence_num=2,
            model="claude-haiku-4",
            stop_reason="end_turn",
            input_tokens=500,
            output_tokens=200,
            cache_read_tokens=1000,
            cache_creation_tokens=0,
            request_json="{}",
            tool_invocations=[
                ToolInvocationRecord(
                    tool_name="Write",
                    tool_use_id="tool_3",
                    input_tokens=500,
                    result_tokens=200,
                    is_error=False,
                ),
            ],
        )
    )

    return store


def test_get_tool_economics_empty():
    """Empty store returns empty list."""
    store = AnalyticsStore()
    assert store.get_tool_economics() == []


def test_get_tool_economics_aggregation():
    """Test basic aggregation of tool invocations."""
    store = setup_test_store()
    rows = store.get_tool_economics()

    # Should have 3 distinct tools
    assert len(rows) == 3

    # Find each tool in results
    read_row = next((r for r in rows if r.name == "Read"), None)
    bash_row = next((r for r in rows if r.name == "Bash"), None)
    write_row = next((r for r in rows if r.name == "Write"), None)

    assert read_row is not None
    assert bash_row is not None
    assert write_row is not None

    # Check basic counts
    assert read_row.calls == 1
    assert read_row.input_tokens == 600
    assert read_row.result_tokens == 1000

    assert bash_row.calls == 1
    assert bash_row.input_tokens == 400
    assert bash_row.result_tokens == 500

    assert write_row.calls == 1
    assert write_row.input_tokens == 500
    assert write_row.result_tokens == 200


def test_get_tool_economics_cache_attribution():
    """Test proportional cache attribution."""
    store = setup_test_store()
    rows = store.get_tool_economics()

    # Find tools from turn 1 (which has cache_read_tokens = 2000)
    read_row = next((r for r in rows if r.name == "Read"), None)
    bash_row = next((r for r in rows if r.name == "Bash"), None)

    # Read: 600 input / 1000 total = 60% share of cache
    # Expected cache: 2000 * 0.6 = 1200
    assert read_row.cache_read_tokens == 1200

    # Bash: 400 input / 1000 total = 40% share of cache
    # Expected cache: 2000 * 0.4 = 800
    assert bash_row.cache_read_tokens == 800

    # Write is from turn 2 (cache_read_tokens = 1000, single tool gets all)
    write_row = next((r for r in rows if r.name == "Write"), None)
    assert write_row.cache_read_tokens == 1000


def test_get_tool_economics_sorting():
    """Results should be sorted by norm_cost descending."""
    store = setup_test_store()
    rows = store.get_tool_economics()

    # Costs should be descending
    for i in range(len(rows) - 1):
        assert rows[i].norm_cost >= rows[i + 1].norm_cost


def test_get_tool_economics_breakdown_mode():
    """Breakdown mode groups by (tool, model)."""
    store = setup_test_store()
    rows = store.get_tool_economics(group_by_model=True)

    # Should have 3 rows (each tool appears once per model)
    assert len(rows) == 3

    # Check each row has a model field
    for row in rows:
        assert row.model is not None


# ─── State Management Tests ────────────────────────────────────────────────────


def test_get_state_restore_state():
    """State can be extracted and restored."""
    store = setup_test_store()
    store._seq = 5

    state = store.get_state()

    # Verify eliminated fields are NOT in serialized state
    assert "current_response_events" not in state
    assert "current_text" not in state

    # Create new store and restore
    new_store = AnalyticsStore()
    new_store.restore_state(state)

    # Verify state matches
    assert new_store._seq == 5
    assert len(new_store._turns) == 2

    # Check turn data
    turn1 = new_store._turns[0]
    assert turn1.sequence_num == 1
    assert turn1.model == "claude-sonnet-4"
    assert len(turn1.tool_invocations) == 2

    # Check tool invocation data
    read_inv = next(inv for inv in turn1.tool_invocations if inv.tool_name == "Read")
    assert read_inv.input_tokens == 600
    assert read_inv.result_tokens == 1000


def test_get_state_restore_state_handles_old_format():
    """restore_state gracefully ignores old state dicts with eliminated fields."""
    store = AnalyticsStore()
    old_state = {
        "turns": [],
        "seq": 3,
        "current_request": None,
        "current_response_events": [{"some": "data"}],
        "current_text": ["hello"],
        "current_usage": {},
        "current_stop": "",
        "current_model": "",
    }
    store.restore_state(old_state)
    assert store._seq == 3
    assert "_current_response_events" not in vars(store)
    assert "_current_text" not in vars(store)


def test_side_channel_purpose_summary_aggregates_marker_tagged_turns():
    store = AnalyticsStore()
    marker = '<<CC_DUMP_SIDE_CHANNEL:{"run_id":"r1","purpose":"block_summary","source_session_id":"s1"}>>\n'
    request = {
        "model": "claude-haiku-4-5",
        "messages": [{"role": "user", "content": marker + "Summarize this"}],
    }
    store.on_event(RequestBodyEvent(body=request, request_id="req-1"))
    store.on_event(
        ResponseCompleteEvent(
            body={
                "model": "claude-haiku-4-5",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 20,
                    "cache_creation_input_tokens": 2,
                },
                "stop_reason": "end_turn",
            },
            request_id="req-1",
        )
    )

    by_purpose = store.get_side_channel_purpose_summary()
    assert "block_summary" in by_purpose
    row = by_purpose["block_summary"]
    assert row["turns"] == 1
    assert row["input_tokens"] == 10
    assert row["cache_read_tokens"] == 20
    assert row["cache_creation_tokens"] == 2
    assert row["output_tokens"] == 5
    assert row["prompt_versions"] == {"v1": 1}


def test_side_channel_summary_excludes_primary_turns():
    store = AnalyticsStore()
    request = {"model": "claude-sonnet-4", "messages": [{"role": "user", "content": "Hello"}]}
    store.on_event(RequestBodyEvent(body=request, request_id="req-p"))
    store.on_event(
        ResponseCompleteEvent(
            body={
                "model": "claude-sonnet-4",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "stop_reason": "end_turn",
            },
            request_id="req-p",
        )
    )
    assert store.get_side_channel_purpose_summary() == {}


def test_side_channel_summary_normalizes_unknown_purpose():
    store = AnalyticsStore()
    marker = '<<CC_DUMP_SIDE_CHANNEL:{"run_id":"r9","purpose":"weird_custom_label","source_session_id":"s1"}>>\n'
    request = {
        "model": "claude-haiku-4-5",
        "messages": [{"role": "user", "content": marker + "Do work"}],
    }
    store.on_event(RequestBodyEvent(body=request, request_id="req-9"))
    store.on_event(
        ResponseCompleteEvent(
            body={
                "model": "claude-haiku-4-5",
                "usage": {"input_tokens": 3, "output_tokens": 2},
                "stop_reason": "end_turn",
            },
            request_id="req-9",
        )
    )
    summary = store.get_side_channel_purpose_summary()
    assert "utility_custom" in summary
    assert summary["utility_custom"]["turns"] == 1
