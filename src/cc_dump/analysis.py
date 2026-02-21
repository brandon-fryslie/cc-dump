"""Context analytics — token estimation, turn budgets, and tool correlation.

Pure computation module with no I/O, no state, and no dependencies on other
cc_dump modules.
"""

import json
import re
from dataclasses import dataclass
from typing import NamedTuple


# ─── Token Estimation ─────────────────────────────────────────────────────────


def estimate_tokens(text: str) -> int:
    """Estimate token count from text using ~4 chars/token heuristic.

    Fast approximation for real-time display (TurnBudget analytics).
    For accuracy-sensitive storage (DB tool invocations), see
    token_counter.count_tokens() which uses tiktoken.
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
    actual_input_tokens: int = 0  # fresh input tokens (not from cache)
    actual_cache_read_tokens: int = 0  # input tokens served from cache
    actual_cache_creation_tokens: int = 0  # input tokens added to cache
    actual_output_tokens: int = 0  # output tokens generated (always fresh)

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


# [LAW:dataflow-not-control-flow] Role token field mapping
_ROLE_TOKEN_FIELDS = {
    "user": "user_text_tokens_est",
    "assistant": "assistant_text_tokens_est",
}


def _estimate_text_block(block: dict) -> int:
    """Estimate tokens for a text content block."""
    text = block.get("text", "")
    return estimate_tokens(text)


def _estimate_tool_use_block(block: dict) -> int:
    """Estimate tokens for a tool_use content block."""
    tool_input = block.get("input", {})
    return estimate_tokens(json.dumps(tool_input))


def _estimate_tool_result_block(block: dict) -> int:
    """Estimate tokens for a tool_result content block."""
    content_val = block.get("content", "")
    if isinstance(content_val, list):
        size = sum(len(json.dumps(p)) for p in content_val)
    elif isinstance(content_val, str):
        size = len(content_val)
    else:
        size = len(json.dumps(content_val))
    return estimate_tokens("x" * size)


# [LAW:dataflow-not-control-flow] Block type estimator dispatch
_BLOCK_TYPE_ESTIMATORS = {
    "text": _estimate_text_block,
    "tool_use": _estimate_tool_use_block,
    "tool_result": _estimate_tool_result_block,
}


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
            field = _ROLE_TOKEN_FIELDS.get(role)
            if field:
                setattr(budget, field, getattr(budget, field) + tokens)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    tokens = estimate_tokens(block)
                    field = _ROLE_TOKEN_FIELDS.get(role)
                    if field:
                        setattr(budget, field, getattr(budget, field) + tokens)
                    continue

                btype = block.get("type", "")

                # [LAW:dataflow-not-control-flow] Special handling for text blocks with role attribution
                if btype == "text":
                    tokens = _estimate_text_block(block)
                    field = _ROLE_TOKEN_FIELDS.get(role)
                    if field:
                        setattr(budget, field, getattr(budget, field) + tokens)
                elif btype == "tool_use":
                    budget.tool_use_tokens_est += _estimate_tool_use_block(block)
                elif btype == "tool_result":
                    budget.tool_result_tokens_est += _estimate_tool_result_block(block)

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
    input_str: str = ""  # Raw input text for token counting
    result_str: str = ""  # Raw result text for token counting
    is_error: bool = False


@dataclass
class ToolEconomicsRow:
    """Per-tool economics data for the panel display."""

    name: str = ""
    calls: int = 0
    input_tokens: int = 0
    result_tokens: int = 0
    cache_read_tokens: int = 0
    norm_cost: float = 0.0
    model: str | None = None  # None for aggregate, model string for breakdown


def correlate_tools(messages: list) -> list[ToolInvocation]:
    """Match tool_use blocks to tool_result blocks by tool_use_id.

    Returns a list of ToolInvocation with raw input/result strings.
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

                # Capture raw input/result strings (token counting happens downstream).
                tool_input = use_block.get("input", {})
                input_str = json.dumps(tool_input)

                content_val = block.get("content", "")
                if isinstance(content_val, list):
                    result_str = json.dumps(content_val)
                elif isinstance(content_val, str):
                    result_str = content_val
                else:
                    result_str = json.dumps(content_val)

                invocations.append(
                    ToolInvocation(
                        tool_use_id=tool_use_id,
                        name=use_block.get("name", "?"),
                        input_str=input_str,
                        result_str=result_str,
                        is_error=block.get("is_error", False),
                    )
                )

    return invocations


def tool_result_breakdown(messages: list) -> dict[str, int]:
    """Compute per-tool-name token estimate for tool_results only.

    Returns {tool_name: tokens_est} for use in the budget summary line.
    """
    invocations = correlate_tools(messages)
    breakdown: dict[str, int] = {}
    for inv in invocations:
        breakdown[inv.name] = breakdown.get(inv.name, 0) + estimate_tokens(inv.result_str)
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
    "opus": ModelPricing(
        base_input=5.0, cache_write_5m=6.25, cache_hit=0.50, output=25.0
    ),
    "sonnet": ModelPricing(
        base_input=3.0, cache_write_5m=3.75, cache_hit=0.30, output=15.0
    ),
    "haiku": ModelPricing(
        base_input=1.0, cache_write_5m=1.25, cache_hit=0.10, output=5.0
    ),
}

FALLBACK_PRICING = MODEL_PRICING["sonnet"]


# ─── Model Context Windows ────────────────────────────────────────────────────

# [LAW:one-source-of-truth] Model context window limits
MODEL_CONTEXT_WINDOW: dict[str, int] = {
    "opus": 200_000,
    "sonnet": 200_000,
    "haiku": 200_000,
}

FALLBACK_CONTEXT_WINDOW = 200_000


def get_context_window(model_str: str) -> int:
    """Get context window size for a model string.

    Args:
        model_str: Full model identifier (e.g., "claude-sonnet-4-20250514")

    Returns:
        Context window size in tokens (200k for all current Claude 4.x models)
    """
    if not model_str:
        return FALLBACK_CONTEXT_WINDOW

    # [LAW:one-source-of-truth] Reuse classify_model for family detection
    family, _ = classify_model(model_str)
    return MODEL_CONTEXT_WINDOW.get(family, FALLBACK_CONTEXT_WINDOW)


def compute_session_cost(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    model_str: str,
) -> float:
    """Compute estimated session cost in USD.

    Args:
        input_tokens: Fresh input tokens (not from cache)
        output_tokens: Output tokens generated
        cache_read_tokens: Input tokens served from cache
        cache_creation_tokens: Input tokens added to cache
        model_str: Full model identifier

    Returns:
        Estimated cost in USD
    """
    _, pricing = classify_model(model_str)

    # Convert $/MTok to $/token by dividing by 1,000,000
    cost_usd = (
        (input_tokens * pricing.base_input / 1_000_000)
        + (cache_creation_tokens * pricing.cache_write_5m / 1_000_000)
        + (cache_read_tokens * pricing.cache_hit / 1_000_000)
        + (output_tokens * pricing.output / 1_000_000)
    )

    return cost_usd


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


# [LAW:one-source-of-truth] Family display labels used by model formatters.
_MODEL_FAMILY_DISPLAY = {
    "opus": "Opus",
    "sonnet": "Sonnet",
    "haiku": "Haiku",
}


def _extract_model_version(model: str, family: str) -> str:
    """Extract short version token from model identifier.

    Examples:
        "claude-sonnet-4-6-20260114" -> "4.6"
        "claude-opus-4-20251101" -> "4"
        "sonnet" -> ""
    """
    if not model or not family or family == "unknown":
        return ""
    pattern = rf"{re.escape(family)}-(\d+)(?:-(\d{{1,2}}))?(?:-|$)"
    match = re.search(pattern, model.lower())
    if match is None:
        return ""
    major = str(int(match.group(1)))
    minor = match.group(2)
    if minor:
        return f"{major}.{int(minor)}"
    return major


def format_model_short(model: str) -> str:
    """Format model string as short display name.

    Examples:
        "claude-opus-4-6-20260114" -> "Opus 4.6"
        "claude-sonnet-4-20250514" -> "Sonnet 4"
        "claude-haiku-4-20250514" -> "Haiku 4"
        "sonnet" -> "Sonnet"
        "" -> "Unknown"
        "some-long-unknown-model-name-12345678" -> "some-long-unknown-mo"
    """
    if not model:
        return "Unknown"

    # [LAW:one-source-of-truth] Reuse classify_model for family detection
    family, _ = classify_model(model)
    display_name = _MODEL_FAMILY_DISPLAY.get(family)
    if display_name:
        version = _extract_model_version(model, family)
        return f"{display_name} {version}" if version else display_name

    # Fallback: truncate to 20 chars for truly unknown models
    return model[:20]


def format_model_ultra_short(model: str) -> str:
    """Format model string as minimal display name.

    Examples:
        "claude-opus-4-20250514" -> "opus"
        "claude-sonnet-4-20250514" -> "sonnet"
        "claude-haiku-4-20250514" -> "haiku"
        "" -> "unknown"
        "some-long-unknown-model-name-12345678" -> "unknown"

    Returns lowercase family name only (opus/sonnet/haiku), or "unknown" for
    unrecognized models.
    """
    if not model:
        return "unknown"

    # [LAW:one-source-of-truth] Reuse classify_model for family detection
    family, _ = classify_model(model)

    # Return lowercase family name, or "unknown" for unrecognized models
    return family if family != "unknown" else "unknown"
