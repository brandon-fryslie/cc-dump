"""Context analytics — token estimation, turn budgets, and tool correlation.

Pure computation module with no I/O, no state, and no dependencies on other
cc_dump modules.
"""

import json
from dataclasses import dataclass


# ─── Token Estimation ─────────────────────────────────────────────────────────


def estimate_tokens(text: str) -> int:
    """Estimate token count from text using ~4 chars/token heuristic.

    This is the single source of truth for byte→token conversion.
    Swap to tiktoken later without touching other code.
    """
    return max(1, len(text) // 4)


# ─── Turn Budget ──────────────────────────────────────────────────────────────


@dataclass
class TurnBudget:
    """Per-turn token budget breakdown by category."""

    system_tokens_est: int = 0
    tool_defs_tokens_est: int = 0
    user_text_tokens_est: int = 0
    assistant_text_tokens_est: int = 0
    tool_use_tokens_est: int = 0
    tool_result_tokens_est: int = 0
    total_est: int = 0

    # Actual token counts (filled from message_start usage data)
    actual_input_tokens: int = 0
    actual_cache_read_tokens: int = 0
    actual_cache_creation_tokens: int = 0

    @property
    def cache_hit_ratio(self) -> float:
        """Fraction of input that was served from cache."""
        total = self.actual_input_tokens + self.actual_cache_read_tokens
        if total == 0:
            return 0.0
        return self.actual_cache_read_tokens / total

    @property
    def fresh_tokens(self) -> int:
        """Tokens that were not cached (had to be processed fresh)."""
        return self.actual_input_tokens

    @property
    def conversation_tokens_est(self) -> int:
        """Estimated tokens for user+assistant text combined."""
        return self.user_text_tokens_est + self.assistant_text_tokens_est


def compute_turn_budget(request_body: dict) -> TurnBudget:
    """Analyze a full API request body and compute token budget breakdown."""
    budget = TurnBudget()

    # System prompt tokens
    system = request_body.get("system", "")
    if isinstance(system, str):
        budget.system_tokens_est = estimate_tokens(system)
    elif isinstance(system, list):
        total = 0
        for block in system:
            text = block.get("text", "") if isinstance(block, dict) else str(block)
            total += estimate_tokens(text)
        budget.system_tokens_est = total

    # Tool definitions
    tools = request_body.get("tools", [])
    if tools:
        budget.tool_defs_tokens_est = estimate_tokens(json.dumps(tools))

    # Messages
    messages = request_body.get("messages", [])
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if isinstance(content, str):
            tokens = estimate_tokens(content)
            if role == "user":
                budget.user_text_tokens_est += tokens
            elif role == "assistant":
                budget.assistant_text_tokens_est += tokens
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    tokens = estimate_tokens(block)
                    if role == "user":
                        budget.user_text_tokens_est += tokens
                    elif role == "assistant":
                        budget.assistant_text_tokens_est += tokens
                    continue

                btype = block.get("type", "")
                if btype == "text":
                    text = block.get("text", "")
                    tokens = estimate_tokens(text)
                    if role == "user":
                        budget.user_text_tokens_est += tokens
                    elif role == "assistant":
                        budget.assistant_text_tokens_est += tokens
                elif btype == "tool_use":
                    tool_input = block.get("input", {})
                    budget.tool_use_tokens_est += estimate_tokens(json.dumps(tool_input))
                elif btype == "tool_result":
                    content_val = block.get("content", "")
                    if isinstance(content_val, list):
                        size = sum(len(json.dumps(p)) for p in content_val)
                    elif isinstance(content_val, str):
                        size = len(content_val)
                    else:
                        size = len(json.dumps(content_val))
                    budget.tool_result_tokens_est += estimate_tokens("x" * size)

    budget.total_est = (
        budget.system_tokens_est
        + budget.tool_defs_tokens_est
        + budget.user_text_tokens_est
        + budget.assistant_text_tokens_est
        + budget.tool_use_tokens_est
        + budget.tool_result_tokens_est
    )

    return budget


# ─── Tool Correlation ─────────────────────────────────────────────────────────


@dataclass
class ToolInvocation:
    """A matched tool_use → tool_result pair."""

    tool_use_id: str = ""
    name: str = ""
    input_bytes: int = 0
    result_bytes: int = 0
    input_tokens_est: int = 0
    result_tokens_est: int = 0
    is_error: bool = False


@dataclass
class ToolAggregates:
    """Aggregate stats for a single tool name across a session."""

    name: str = ""
    calls: int = 0
    input_tokens_est: int = 0
    result_tokens_est: int = 0

    @property
    def total_tokens_est(self) -> int:
        return self.input_tokens_est + self.result_tokens_est


def correlate_tools(messages: list) -> list[ToolInvocation]:
    """Match tool_use blocks to tool_result blocks by tool_use_id.

    Returns a list of ToolInvocation with per-tool byte/token estimates.
    """
    # Collect tool_use blocks by id
    uses: dict[str, dict] = {}
    for msg in messages:
        content = msg.get("content", "")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                tool_id = block.get("id", "")
                if tool_id:
                    uses[tool_id] = block

    # Match tool_result blocks
    invocations = []
    for msg in messages:
        content = msg.get("content", "")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                tool_use_id = block.get("tool_use_id", "")
                use_block = uses.get(tool_use_id)
                if not use_block:
                    continue

                # Compute sizes
                tool_input = use_block.get("input", {})
                input_str = json.dumps(tool_input)
                input_bytes = len(input_str)

                content_val = block.get("content", "")
                if isinstance(content_val, list):
                    result_str = json.dumps(content_val)
                elif isinstance(content_val, str):
                    result_str = content_val
                else:
                    result_str = json.dumps(content_val)
                result_bytes = len(result_str)

                invocations.append(ToolInvocation(
                    tool_use_id=tool_use_id,
                    name=use_block.get("name", "?"),
                    input_bytes=input_bytes,
                    result_bytes=result_bytes,
                    input_tokens_est=estimate_tokens(input_str),
                    result_tokens_est=estimate_tokens(result_str),
                    is_error=block.get("is_error", False),
                ))

    return invocations


def aggregate_tools(invocations: list[ToolInvocation]) -> list[ToolAggregates]:
    """Group invocations by tool name and compute aggregates.

    Returns list sorted by total_tokens_est descending.
    """
    by_name: dict[str, ToolAggregates] = {}
    for inv in invocations:
        if inv.name not in by_name:
            by_name[inv.name] = ToolAggregates(name=inv.name)
        agg = by_name[inv.name]
        agg.calls += 1
        agg.input_tokens_est += inv.input_tokens_est
        agg.result_tokens_est += inv.result_tokens_est

    return sorted(by_name.values(), key=lambda a: a.total_tokens_est, reverse=True)


def tool_result_breakdown(messages: list) -> dict[str, int]:
    """Compute per-tool-name token estimate for tool_results only.

    Returns {tool_name: tokens_est} for use in the budget summary line.
    """
    invocations = correlate_tools(messages)
    breakdown: dict[str, int] = {}
    for inv in invocations:
        breakdown[inv.name] = breakdown.get(inv.name, 0) + inv.result_tokens_est
    return breakdown
