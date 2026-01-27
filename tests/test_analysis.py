"""Unit tests for analysis.py - token estimation, budgets, tool correlation."""

import pytest

from cc_dump.analysis import (
    TurnBudget,
    ToolAggregates,
    ToolInvocation,
    aggregate_tools,
    compute_turn_budget,
    correlate_tools,
    estimate_tokens,
    tool_result_breakdown,
)


# ─── Token Estimation Tests ──────────────────────────────────────────────────


def test_estimate_tokens_empty():
    """Empty string returns 1 (min)."""
    assert estimate_tokens("") == 1


def test_estimate_tokens_short():
    """Short text returns expected token count."""
    # "hello" is 5 chars, 5 // 4 = 1, but max(1, 1) = 1
    assert estimate_tokens("hello") == 1
    # "hello world" is 11 chars, 11 // 4 = 2
    assert estimate_tokens("hello world") == 2


def test_estimate_tokens_long():
    """1000 chars returns ~250 tokens."""
    text = "a" * 1000
    assert estimate_tokens(text) == 250


def test_estimate_tokens_unicode():
    """Unicode text uses byte length for estimation."""
    # Each emoji can be multiple bytes
    text = "👋" * 100  # Each emoji is ~4 bytes in UTF-8
    # The function uses len(text) which is character count, not byte count
    # 100 chars // 4 = 25
    assert estimate_tokens(text) == 25


# ─── Turn Budget Tests ────────────────────────────────────────────────────────


def test_compute_turn_budget_minimal():
    """Empty request works without crashing."""
    budget = compute_turn_budget({})
    # Empty request defaults system to "", which estimates as 1 token minimum
    assert budget.total_est == 1
    assert budget.system_tokens_est == 1
    assert budget.user_text_tokens_est == 0


def test_compute_turn_budget_with_system():
    """System prompt counted."""
    request = {
        "system": "You are a helpful assistant.",
        "messages": [],
    }
    budget = compute_turn_budget(request)
    # "You are a helpful assistant." is 30 chars, 30 // 4 = 7
    assert budget.system_tokens_est == 7
    assert budget.total_est == 7


def test_compute_turn_budget_with_system_list():
    """System prompt as list of blocks counted."""
    request = {
        "system": [
            {"text": "First block."},
            {"text": "Second block."},
        ],
        "messages": [],
    }
    budget = compute_turn_budget(request)
    # "First block." = 12 chars = 3 tokens
    # "Second block." = 13 chars = 3 tokens
    # Total = 6 tokens
    assert budget.system_tokens_est == 6
    assert budget.total_est == 6


def test_compute_turn_budget_with_tools():
    """Tool definitions counted."""
    request = {
        "tools": [
            {"name": "read_file", "description": "Read a file"},
            {"name": "write_file", "description": "Write a file"},
        ],
        "messages": [],
    }
    budget = compute_turn_budget(request)
    # Tools are JSON-serialized for estimation
    assert budget.tool_defs_tokens_est > 0
    assert budget.total_est > 0


def test_compute_turn_budget_with_messages():
    """User/assistant text counted."""
    request = {
        "messages": [
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "assistant", "content": "I'm doing well, thank you!"},
        ],
    }
    budget = compute_turn_budget(request)
    # "Hello, how are you?" = 19 chars = 4 tokens
    assert budget.user_text_tokens_est == 4
    # "I'm doing well, thank you!" = 27 chars = 6 tokens
    assert budget.assistant_text_tokens_est == 6
    # total = 4 + 6 + 1 (default empty system) = 11
    assert budget.total_est == 11


def test_compute_turn_budget_with_nested_content():
    """Messages with content blocks counted correctly."""
    request = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is the weather?"},
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me check."},
                    {"type": "tool_use", "id": "1", "name": "get_weather", "input": {"city": "NYC"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "1", "content": "Sunny, 72F"},
                ],
            },
        ],
    }
    budget = compute_turn_budget(request)
    # User text: "What is the weather?" = 20 chars = 5 tokens
    assert budget.user_text_tokens_est == 5
    # Assistant text: "Let me check." = 14 chars = 3 tokens
    assert budget.assistant_text_tokens_est == 3
    # Tool use input: {"city": "NYC"} serialized
    assert budget.tool_use_tokens_est > 0
    # Tool result: "Sunny, 72F" = 10 chars = 2 tokens
    assert budget.tool_result_tokens_est == 2
    assert budget.total_est > 10


def test_compute_turn_budget_with_tool_result_list():
    """Tool result as list counted correctly."""
    request = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "1",
                        "content": [
                            {"type": "text", "text": "Result 1"},
                            {"type": "text", "text": "Result 2"},
                        ],
                    },
                ],
            },
        ],
    }
    budget = compute_turn_budget(request)
    # Content is a list, so JSON serialized
    assert budget.tool_result_tokens_est > 0


# ─── TurnBudget Property Tests ────────────────────────────────────────────────


def test_turn_budget_cache_hit_ratio_zero_total():
    """Cache hit ratio is 0 when no tokens."""
    budget = TurnBudget()
    assert budget.cache_hit_ratio == 0.0


def test_turn_budget_cache_hit_ratio_full():
    """Cache hit ratio is 1.0 when all from cache."""
    budget = TurnBudget(
        actual_input_tokens=0,
        actual_cache_read_tokens=100,
    )
    assert budget.cache_hit_ratio == 1.0


def test_turn_budget_cache_hit_ratio_half():
    """Cache hit ratio is 0.5 when half from cache."""
    budget = TurnBudget(
        actual_input_tokens=100,
        actual_cache_read_tokens=100,
    )
    assert budget.cache_hit_ratio == 0.5


def test_turn_budget_fresh_input_tokens():
    """Fresh input tokens property returns actual_input_tokens."""
    budget = TurnBudget(actual_input_tokens=42)
    assert budget.fresh_input_tokens == 42


def test_turn_budget_conversation_tokens_est():
    """Conversation tokens is sum of user and assistant."""
    budget = TurnBudget(
        user_text_tokens_est=10,
        assistant_text_tokens_est=20,
    )
    assert budget.conversation_tokens_est == 30


# ─── Tool Correlation Tests ───────────────────────────────────────────────────


def test_correlate_tools_empty():
    """Empty messages returns empty list."""
    assert correlate_tools([]) == []


def test_correlate_tools_no_tools():
    """Messages without tools returns empty list."""
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
    ]
    assert correlate_tools(messages) == []


def test_correlate_tools_matched():
    """tool_use matched to tool_result."""
    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool_1",
                    "name": "get_weather",
                    "input": {"city": "NYC"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool_1",
                    "content": "Sunny, 72F",
                },
            ],
        },
    ]
    invocations = correlate_tools(messages)
    assert len(invocations) == 1
    inv = invocations[0]
    assert inv.tool_use_id == "tool_1"
    assert inv.name == "get_weather"
    assert inv.input_bytes > 0
    assert inv.result_bytes > 0
    assert inv.input_tokens_est > 0
    assert inv.result_tokens_est > 0
    assert inv.is_error is False


def test_correlate_tools_with_error():
    """Tool result with is_error flag captured."""
    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool_1",
                    "name": "fail_tool",
                    "input": {},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool_1",
                    "content": "Error: failed",
                    "is_error": True,
                },
            ],
        },
    ]
    invocations = correlate_tools(messages)
    assert len(invocations) == 1
    assert invocations[0].is_error is True


def test_correlate_tools_unmatched():
    """Orphan use/result handled (not matched)."""
    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool_1",
                    "name": "orphan",
                    "input": {},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool_2",  # Different ID - orphan
                    "content": "result",
                },
            ],
        },
    ]
    invocations = correlate_tools(messages)
    # Unmatched tool_result is skipped
    assert len(invocations) == 0


def test_correlate_tools_result_as_list():
    """Tool result content as list handled."""
    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool_1",
                    "name": "multi_result",
                    "input": {},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool_1",
                    "content": [
                        {"type": "text", "text": "Part 1"},
                        {"type": "text", "text": "Part 2"},
                    ],
                },
            ],
        },
    ]
    invocations = correlate_tools(messages)
    assert len(invocations) == 1
    # Content list is JSON serialized for size
    assert invocations[0].result_bytes > 0


# ─── Tool Aggregation Tests ───────────────────────────────────────────────────


def test_aggregate_tools_empty():
    """Empty list returns empty aggregates."""
    assert aggregate_tools([]) == []


def test_aggregate_tools_single_tool():
    """Single tool aggregated correctly."""
    invocations = [
        ToolInvocation(
            tool_use_id="1",
            name="read_file",
            input_tokens_est=10,
            result_tokens_est=100,
        ),
    ]
    aggregates = aggregate_tools(invocations)
    assert len(aggregates) == 1
    agg = aggregates[0]
    assert agg.name == "read_file"
    assert agg.calls == 1
    assert agg.input_tokens_est == 10
    assert agg.result_tokens_est == 100
    assert agg.total_tokens_est == 110


def test_aggregate_tools_multiple_calls_same_tool():
    """Multiple invocations of same tool aggregated."""
    invocations = [
        ToolInvocation(name="read_file", input_tokens_est=10, result_tokens_est=50),
        ToolInvocation(name="read_file", input_tokens_est=20, result_tokens_est=100),
    ]
    aggregates = aggregate_tools(invocations)
    assert len(aggregates) == 1
    agg = aggregates[0]
    assert agg.name == "read_file"
    assert agg.calls == 2
    assert agg.input_tokens_est == 30
    assert agg.result_tokens_est == 150
    assert agg.total_tokens_est == 180


def test_aggregate_tools_sorting():
    """Aggregates sorted by total_tokens_est descending."""
    invocations = [
        ToolInvocation(name="small", input_tokens_est=5, result_tokens_est=5),
        ToolInvocation(name="large", input_tokens_est=100, result_tokens_est=200),
        ToolInvocation(name="medium", input_tokens_est=20, result_tokens_est=30),
    ]
    aggregates = aggregate_tools(invocations)
    assert len(aggregates) == 3
    # Sorted by total descending
    assert aggregates[0].name == "large"
    assert aggregates[1].name == "medium"
    assert aggregates[2].name == "small"


# ─── Tool Result Breakdown Tests ──────────────────────────────────────────────


def test_tool_result_breakdown_empty():
    """Empty messages returns empty dict."""
    assert tool_result_breakdown([]) == {}


def test_tool_result_breakdown_no_tools():
    """Messages without tools returns empty dict."""
    messages = [{"role": "user", "content": "Hello"}]
    assert tool_result_breakdown(messages) == {}


def test_tool_result_breakdown_single_tool():
    """Single tool result breakdown."""
    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "1",
                    "name": "get_weather",
                    "input": {},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "1",
                    "content": "Sunny, 72F",
                },
            ],
        },
    ]
    breakdown = tool_result_breakdown(messages)
    assert "get_weather" in breakdown
    assert breakdown["get_weather"] > 0


def test_tool_result_breakdown_multiple_tools():
    """Multiple tool results aggregated by name."""
    messages = [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "1", "name": "read_file", "input": {}},
                {"type": "tool_use", "id": "2", "name": "read_file", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "1", "content": "File content A"},
                {"type": "tool_result", "tool_use_id": "2", "content": "File content B"},
            ],
        },
    ]
    breakdown = tool_result_breakdown(messages)
    assert "read_file" in breakdown
    # Should be sum of both results
    assert breakdown["read_file"] > 0
