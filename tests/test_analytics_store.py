"""Tests for AnalyticsStore."""

import pytest

import cc_dump.app.analytics_store as analytics_store_mod
from cc_dump.app.analytics_store import AnalyticsStore, ToolInvocationRecord, TurnRecord
from cc_dump.pipeline.event_types import (
    RequestBodyEvent,
    RequestHeadersEvent,
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


# ─── Shared multi-turn test store ─────────────────────────────────────────────


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


# ─── OpenAI Usage Key Normalization ──────────────────────────────────────────


def test_openai_usage_keys_normalized():
    """OpenAI prompt_tokens/completion_tokens normalized to input/output."""
    store = AnalyticsStore()

    store.on_event(
        RequestBodyEvent(
            body={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
            request_id="req-oai",
            provider="openai",
        )
    )
    store.on_event(
        ResponseCompleteEvent(
            body={
                "id": "chatcmpl-test",
                "model": "gpt-4o",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hello!"},
                        "finish_reason": "stop",
                    },
                ],
                "usage": {
                    "prompt_tokens": 42,
                    "completion_tokens": 15,
                    "total_tokens": 57,
                },
            },
            request_id="req-oai",
        )
    )

    assert len(store._turns) == 1
    turn = store._turns[0]
    assert turn.input_tokens == 42
    assert turn.output_tokens == 15
    assert turn.provider == "openai"


def test_openai_stop_reason_from_choices():
    """OpenAI stop_reason extracted from choices[0].finish_reason."""
    store = AnalyticsStore()

    store.on_event(
        RequestBodyEvent(
            body={"model": "gpt-4o", "messages": []},
            request_id="req-stop",
            provider="openai",
        )
    )
    store.on_event(
        ResponseCompleteEvent(
            body={
                "model": "gpt-4o",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Done"},
                        "finish_reason": "stop",
                    },
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            },
            request_id="req-stop",
        )
    )

    assert store._turns[0].stop_reason == "stop"


def test_openai_tool_correlation_in_analytics():
    """OpenAI tool_calls/role='tool' messages produce tool invocation records."""
    store = AnalyticsStore()

    store.on_event(
        RequestBodyEvent(
            body={
                "model": "gpt-4o",
                "messages": [
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"city": "NYC"}',
                                },
                            },
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call_1",
                        "content": "Sunny, 72F",
                    },
                    {"role": "user", "content": "Thanks!"},
                ],
            },
            request_id="req-tool",
            provider="openai",
        )
    )
    store.on_event(
        ResponseCompleteEvent(
            body={
                "model": "gpt-4o",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "You're welcome!"},
                        "finish_reason": "stop",
                    },
                ],
                "usage": {"prompt_tokens": 50, "completion_tokens": 10},
            },
            request_id="req-tool",
        )
    )

    assert len(store._turns) == 1
    turn = store._turns[0]
    assert len(turn.tool_invocations) == 1
    assert turn.tool_invocations[0].tool_name == "get_weather"


def test_turn_record_captures_linkage_and_retry_metadata():
    """Ingestion records request/session linkage, retry, and command metadata on the turn."""
    store = AnalyticsStore()
    request_id = "req-metrics"
    request = {
        "model": "claude-sonnet-4",
        "metadata": {
            "user_id": (
                "user_deadbeef_account_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_"
                "session_11111111-2222-3333-4444-555555555555"
            )
        },
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool_cmd",
                        "name": "Bash",
                        "input": {"command": "git status"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool_cmd",
                        "content": "on branch main",
                    }
                ],
            },
        ],
    }

    store.on_event(
        RequestHeadersEvent(
            headers={"x-stainless-retry-count": "2"},
            request_id=request_id,
            recv_ns=1_000_000,
        )
    )
    store.on_event(RequestBodyEvent(body=request, request_id=request_id, recv_ns=1_100_000))
    store.on_event(
        ResponseCompleteEvent(
            body={
                "model": "claude-sonnet-4",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 20,
                    "cache_creation_input_tokens": 1,
                },
                "stop_reason": "max_tokens",
            },
            request_id=request_id,
            recv_ns=6_100_000,
        )
    )

    assert len(store._turns) == 1
    turn = store._turns[0]
    assert turn.request_id == request_id
    assert turn.session_id == "11111111-2222-3333-4444-555555555555"
    assert turn.sequence_num == 1
    assert turn.provider == "anthropic"
    assert turn.purpose == "primary"
    assert turn.transport_retry_count == 2
    assert turn.retry_ordinal == 0
    assert turn.was_interrupted is True
    assert turn.latency_ms == pytest.approx(5.1)
    assert len(turn.tool_invocations) == 1
    assert turn.tool_invocations[0].tool_name == "Bash"
    assert turn.command_count == 1
    assert list(turn.command_families) == ["git"]


def test_retry_ordinal_derives_from_request_fingerprint():
    """Repeated identical requests increment retry ordinal deterministically."""
    store = AnalyticsStore()
    request = {
        "model": "claude-haiku-4-5",
        "messages": [{"role": "user", "content": "Retry me"}],
    }

    store.on_event(RequestBodyEvent(body=request, request_id="req-1", recv_ns=1_000))
    store.on_event(
        ResponseCompleteEvent(
            body={
                "model": "claude-haiku-4-5",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "stop_reason": "end_turn",
            },
            request_id="req-1",
            recv_ns=2_000,
        )
    )

    store.on_event(RequestBodyEvent(body=request, request_id="req-2", recv_ns=3_000))
    store.on_event(
        ResponseCompleteEvent(
            body={
                "model": "claude-haiku-4-5",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "stop_reason": "end_turn",
            },
            request_id="req-2",
            recv_ns=4_000,
        )
    )

    turns = store._turns
    assert len(turns) == 2
    assert turns[0].retry_ordinal == 0
    assert turns[1].retry_ordinal == 1
    assert turns[0].retry_key == turns[1].retry_key


def test_request_meta_prunes_unmatched_header_entries(monkeypatch):
    monkeypatch.setattr(analytics_store_mod, "_REQUEST_META_LIMIT", 3)
    store = AnalyticsStore()

    for idx in range(5):
        store.on_event(
            RequestHeadersEvent(
                headers={},
                request_id=f"req-{idx}",
                recv_ns=idx + 1,
            )
        )

    assert len(store._request_meta) == 3
    assert set(store._request_meta.keys()) == {"req-2", "req-3", "req-4"}


def test_retry_ordinals_prune_unique_fingerprints(monkeypatch):
    monkeypatch.setattr(analytics_store_mod, "_RETRY_ORDINAL_LIMIT", 2)
    store = AnalyticsStore()

    for idx in range(4):
        request_id = f"req-{idx}"
        store.on_event(
            RequestBodyEvent(
                body={
                    "model": "claude-haiku-4-5",
                    "messages": [{"role": "user", "content": f"prompt-{idx}"}],
                },
                request_id=request_id,
            )
        )
        store.on_event(
            ResponseCompleteEvent(
                body={
                    "model": "claude-haiku-4-5",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                    "stop_reason": "end_turn",
                },
                request_id=request_id,
            )
        )

    assert len(store._retry_ordinals) == 2
    expected_retry_keys = {store._turns[-2].retry_key, store._turns[-1].retry_key}
    assert set(store._retry_ordinals.keys()) == expected_retry_keys
