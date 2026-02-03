"""Context analytics — token estimation, turn budgets, and tool correlation.

Pure computation module with no I/O, no state, and no dependencies on other
cc_dump modules.
"""

import json
from dataclasses import dataclass
from typing import NamedTuple


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

    # Actual token counts (filled from message_start and message_delta usage data)
    actual_input_tokens: int = 0        # fresh input tokens (not from cache)
    actual_cache_read_tokens: int = 0   # input tokens served from cache
    actual_cache_creation_tokens: int = 0  # input tokens added to cache
    actual_output_tokens: int = 0       # output tokens generated (always fresh)

    @property
    def cache_hit_ratio(self) -> float:
        """Fraction of input that was served from cache."""
        total = self.actual_input_tokens + self.actual_cache_read_tokens
        if total == 0:
            return 0.0
        return self.actual_cache_read_tokens / total

    @property
    def fresh_input_tokens(self) -> int:
        """Input tokens that were not cached (had to be processed fresh)."""
        return self.actual_input_tokens

    @property
    def total_input_tokens(self) -> int:
        """Total input tokens (fresh + cached)."""
        return self.actual_input_tokens + self.actual_cache_read_tokens

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
    input_str: str = ""    # Raw input text for token counting
    result_str: str = ""   # Raw result text for token counting
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


@dataclass
class ToolEconomicsRow:
    """Per-tool economics data for the panel display."""
    name: str = ""
    calls: int = 0
    input_tokens: int = 0
    result_tokens: int = 0
    cache_read_tokens: int = 0
    norm_cost: float = 0.0


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
                    input_str=input_str,
                    result_str=result_str,
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


# ─── Model Economics ─────────────────────────────────────────────────────────


class ModelPricing(NamedTuple):
    """Per-model pricing in $/MTok."""

    base_input: float
    cache_write_5m: float
    cache_hit: float
    output: float


# Normalization unit: 1 Haiku base input token = 1 unit
HAIKU_BASE_UNIT = 1.0  # $/MTok

MODEL_PRICING: dict[str, ModelPricing] = {
    "opus": ModelPricing(base_input=5.0, cache_write_5m=6.25, cache_hit=0.50, output=25.0),
    "sonnet": ModelPricing(base_input=3.0, cache_write_5m=3.75, cache_hit=0.30, output=15.0),
    "haiku": ModelPricing(base_input=1.0, cache_write_5m=1.25, cache_hit=0.10, output=5.0),
}

FALLBACK_PRICING = MODEL_PRICING["sonnet"]


def classify_model(model_str: str) -> tuple[str, ModelPricing]:
    """Map a full model string to (display_key, pricing).

    Matches on substring: "opus", "sonnet", "haiku".
    Unknown models fall back to sonnet pricing.
    """
    if not model_str:
        return ("unknown", FALLBACK_PRICING)

    lower = model_str.lower()
    for family, pricing in MODEL_PRICING.items():
        if family in lower:
            return (family, pricing)

    return ("unknown", FALLBACK_PRICING)


@dataclass
class ModelEconomics:
    """Aggregated real token data for a single model family."""

    model_key: str = ""
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    @property
    def total_input(self) -> int:
        """Total input = fresh + cache_read + cache_creation."""
        return self.input_tokens + self.cache_read_tokens + self.cache_creation_tokens

    @property
    def cache_hit_pct(self) -> float:
        """Cache hit percentage of total input."""
        total = self.total_input
        if total == 0:
            return 0.0
        return 100.0 * self.cache_read_tokens / total

    def norm_cost(self, pricing: ModelPricing) -> float:
        """Normalized cost where 1 Haiku base input token = 1 unit."""
        return (
            self.input_tokens * (pricing.base_input / HAIKU_BASE_UNIT)
            + self.cache_creation_tokens * (pricing.cache_write_5m / HAIKU_BASE_UNIT)
            + self.cache_read_tokens * (pricing.cache_hit / HAIKU_BASE_UNIT)
            + self.output_tokens * (pricing.output / HAIKU_BASE_UNIT)
        )
