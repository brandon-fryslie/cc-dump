"""Tests for AnalyticsStore."""

import pytest

from cc_dump.analytics_store import AnalyticsStore, TurnRecord, ToolInvocationRecord
from cc_dump.analysis import ToolEconomicsRow


# ─── Basic Event Handling Tests ────────────────────────────────────────────────


def test_store_accumulates_turn():
    """Store accumulates request/response events into a turn."""
    store = AnalyticsStore()

    # Simulate a request/response cycle
    request = {
        "model": "claude-sonnet-4",
        "messages": [{"role": "user", "content": "Hello"}],
    }

    store.on_event(("request", request))
    store.on_event(
        (
            "response_event",
            "message_start",
            {
                "message": {
                    "model": "claude-sonnet-4",
                    "usage": {"input_tokens": 100, "output_tokens": 0},
                }
            },
        )
    )
    store.on_event(
        (
            "response_event",
            "message_delta",
            {"delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 50}},
        )
    )
    store.on_event(("response_done",))

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

    store.on_event(("request", request))
    store.on_event(
        (
            "response_event",
            "message_start",
            {
                "message": {
                    "model": "claude-sonnet-4",
                    "usage": {"input_tokens": 100, "output_tokens": 0},
                }
            },
        )
    )
    store.on_event(
        (
            "response_event",
            "message_delta",
            {"delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 50}},
        )
    )
    store.on_event(("response_done",))

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

    store.on_event(("request", request))
    store.on_event(
        (
            "response_event",
            "message_start",
            {"message": {"model": "claude-sonnet-4", "usage": {}}},
        )
    )
    store.on_event(("response_done",))

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

    store.on_event(("request", request))
    store.on_event(
        ("response_event", "message_start", {"message": {"model": "claude-sonnet-4", "usage": {}}})
    )
    store.on_event(("response_done",))

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
