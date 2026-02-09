"""Panel rendering logic - pure functions for building display text.

This module contains all the display formatting logic for panels. It's separated
so it can be hot-reloaded without affecting the live widget instances.
"""

import cc_dump.analysis


def _fmt_tokens(n: int) -> str:
    """Format token count: 1.2k, 68.9k, etc."""
    if n >= 1000:
        return "{:.1f}k".format(n / 1000)
    return str(n)


def render_stats_panel(
    request_count: int,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    models_seen: set,
) -> str:
    """Render the stats panel display text."""
    parts = []
    parts.append("Requests: {}".format(request_count))
    parts.append("In: {:,}".format(input_tokens))
    parts.append("Out: {:,}".format(output_tokens))
    if cache_read_tokens > 0:
        total_input = input_tokens + cache_read_tokens
        hit_pct = (100 * cache_read_tokens / total_input) if total_input > 0 else 0
        parts.append("Cache: {:,} ({:.0f}%)".format(cache_read_tokens, hit_pct))
    if cache_creation_tokens > 0:
        parts.append("Cache Create: {:,}".format(cache_creation_tokens))
    models = ", ".join(sorted(models_seen)) if models_seen else "-"
    parts.append("Models: {}".format(models))

    return " | ".join(parts)


def _format_economics_row_input(row) -> str:
    """Format input tokens with cache percentage.

    Args:
        row: ToolEconomicsRow with input_tokens and cache_read_tokens

    Returns:
        Formatted string like "1.2k (35%)" or "68" or "--"
    """
    if row.input_tokens > 0:
        total_input = row.input_tokens + row.cache_read_tokens
        if row.cache_read_tokens > 0 and total_input > 0:
            cache_pct = 100 * row.cache_read_tokens / total_input
            return "{} ({:.0f}%)".format(_fmt_tokens(row.input_tokens), cache_pct)
        else:
            return _fmt_tokens(row.input_tokens)
    else:
        return "--"


def _format_economics_row_output(row) -> str:
    """Format output tokens."""
    return _fmt_tokens(row.result_tokens) if row.result_tokens > 0 else "--"


def _format_economics_row_cost(row) -> str:
    """Format normalized cost."""
    return "{:,.0f}".format(row.norm_cost) if row.norm_cost > 0 else "--"


def render_economics_panel(rows: list) -> str:
    """Render the tool economics panel display text.

    Args:
        rows: List of ToolEconomicsRow from get_tool_economics()
              If any row has model != None, renders breakdown layout.
              Otherwise renders aggregate layout.
    """
    if not rows:
        return "Tool Economics: (no tool calls yet)"

    # Detect breakdown mode by checking if any row has a model
    is_breakdown = any(row.model is not None for row in rows)

    # [LAW:dataflow-not-control-flow] Layout config drives rendering
    if is_breakdown:
        title = "Tool Economics (by model):"
        header_fmt = "  {:<12} {:<11} {:>5}  {:>14}  {:>8}  {:>10}"
        header_cols = ("Tool", "Model", "Calls", "Input (Cached)", "Output", "Norm Cost")
        row_fmt = "  {:<12} {:<11} {:>5}  {:>14}  {:>8}  {:>10}"

        def row_fields(row):
            return (
                row.name[:12],
                cc_dump.analysis.format_model_short(row.model or "")[:11],
                row.calls,
                _format_economics_row_input(row),
                _format_economics_row_output(row),
                _format_economics_row_cost(row),
            )
    else:
        title = "Tool Economics (session total):"
        header_fmt = "  {:<12} {:>5}  {:>14}  {:>8}  {:>10}"
        header_cols = ("Tool", "Calls", "Input (Cached)", "Output", "Norm Cost")
        row_fmt = "  {:<12} {:>5}  {:>14}  {:>8}  {:>10}"

        def row_fields(row):
            return (
                row.name[:12],
                row.calls,
                _format_economics_row_input(row),
                _format_economics_row_output(row),
                _format_economics_row_cost(row),
            )

    # Single rendering loop
    lines = [title, header_fmt.format(*header_cols)]
    for row in rows:
        lines.append(row_fmt.format(*row_fields(row)))

    return "\n".join(lines)


def render_timeline_panel(budgets: list[cc_dump.analysis.TurnBudget]) -> str:
    """Render the timeline panel display text."""
    if not budgets:
        return "Timeline: (no turns yet)"

    lines = []
    lines.append("Timeline:")
    lines.append(
        "  {:>4}  {:>7}  {:>7}  {:>7}  {:>6}  {:>7}  {:>7}".format(
            "Turn", "System", "Tools", "Conv", "Cache%", "Fresh", "\u0394"
        )
    )
    prev_total = 0
    for i, b in enumerate(budgets):
        sys_tok = b.system_tokens_est + b.tool_defs_tokens_est
        conv_tok = b.conversation_tokens_est
        tool_tok = b.tool_use_tokens_est + b.tool_result_tokens_est

        total_actual = b.actual_input_tokens + b.actual_cache_read_tokens
        cache_pct = (
            "{:.0f}%".format(100 * b.actual_cache_read_tokens / total_actual)
            if total_actual > 0
            else "--"
        )
        fresh = (
            _fmt_tokens(b.actual_input_tokens) if b.actual_input_tokens > 0 else "--"
        )

        current_total = b.total_est
        delta = current_total - prev_total if prev_total > 0 else 0
        delta_str = "+{}".format(_fmt_tokens(delta)) if delta > 0 else "--"
        prev_total = current_total

        lines.append(
            "  {:>4}  {:>7}  {:>7}  {:>7}  {:>6}  {:>7}  {:>7}".format(
                i + 1,
                _fmt_tokens(sys_tok),
                _fmt_tokens(tool_tok),
                _fmt_tokens(conv_tok),
                cache_pct,
                fresh,
                delta_str,
            )
        )

    return "\n".join(lines)
