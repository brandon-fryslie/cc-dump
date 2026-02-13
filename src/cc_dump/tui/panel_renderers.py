"""Panel rendering logic - pure functions for building display text.

This module contains all the display formatting logic for panels. It's separated
so it can be hot-reloaded without affecting the live widget instances.
"""

import cc_dump.analysis
import cc_dump.palette
from rich.text import Text


def _fmt_tokens(n: int) -> str:
    """Format token count: 1.2k, 68.9k, etc."""
    if n >= 1000:
        return "{:.1f}k".format(n / 1000)
    return str(n)


def render_stats_panel(
    turn_count: int,
    context_total: int,
    context_window: int,
    cache_pct: float,
    output_total: int,
    cost_estimate: float,
    model_display: str,
) -> Text:
    """Render the stats panel display text with color-coded context usage.

    Args:
        turn_count: Number of API round-trips (requests)
        context_total: Total input tokens in latest turn (input + cache_read + cache_creation)
        context_window: Model context window size (e.g., 200_000)
        cache_pct: Cache hit percentage (0-100)
        output_total: Cumulative output tokens across session
        cost_estimate: Estimated session cost in USD
        model_display: Model display name (e.g., "sonnet")

    Returns:
        Rich Text object with color-coded context percentage
    """
    # Build the display text with separators
    parts = []

    # Turn count
    parts.append("Turn {}".format(turn_count))

    # Context usage with percentage (will be colored)
    context_pct = (100.0 * context_total / context_window) if context_window > 0 else 0.0
    ctx_str = "Ctx: {} / {} ({:.0f}%)".format(
        _fmt_tokens(context_total),
        _fmt_tokens(context_window),
        context_pct
    )

    # Cache hit rate
    parts.append("Cache: {:.0f}%".format(cache_pct))

    # Cumulative output
    parts.append("Out: {}".format(_fmt_tokens(output_total)))

    # Cost estimate
    if cost_estimate >= 0.01:
        parts.append("~${:.2f}".format(cost_estimate))
    else:
        parts.append("~$<0.01")

    # Model
    parts.append(model_display)

    # [LAW:dataflow-not-control-flow] Color selection driven by data, not control flow
    # Traffic-light colors for context percentage
    if context_pct < 60.0:
        ctx_color = "green"
    elif context_pct < 80.0:
        ctx_color = "yellow"
    else:
        ctx_color = "red"

    # Build Rich Text with colored context section
    result = Text()
    result.append(parts[0])  # Turn N
    result.append(" | ")
    result.append(ctx_str, style=ctx_color)  # Colored context usage
    result.append(" | ")
    result.append(" | ".join(parts[1:]))  # Rest of the fields

    return result


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


def render_info_panel(info: dict) -> Text:
    """Render the server info panel display.

    // [LAW:dataflow-not-control-flow] All rows always rendered; empty values shown as "--".

    Args:
        info: Dict with server info fields:
            - proxy_url: Full proxy URL (e.g., "http://127.0.0.1:12345")
            - proxy_mode: "reverse" or "forward"
            - target: Upstream target URL (or None)
            - session_name: Session name string
            - session_id: Session ID hex string (or None)
            - recording_path: HAR recording path (or None)
            - recording_dir: Directory containing recordings
            - replay_file: Replay source file (or None)
            - python_version: Python version string
            - textual_version: Textual framework version
            - pid: Process ID

    Returns:
        Rich Text object with labeled rows
    """
    p = cc_dump.palette.PALETTE

    # // [LAW:one-source-of-truth] Row definitions: (label, value)
    # Every row is rendered. None/empty → "--". All values are click-to-copy.
    proxy_url = info.get("proxy_url", "--")
    rows = [
        ("Proxy URL", proxy_url),
        ("Proxy Mode", info.get("proxy_mode", "--")),
        ("Target", info.get("target") or "--"),
        ("Session", info.get("session_name", "--")),
        ("Session ID", info.get("session_id") or "--"),
        ("Recording", info.get("recording_path") or "disabled"),
        ("Recordings Dir", info.get("recording_dir", "--")),
        ("Replay From", info.get("replay_file") or "--"),
        ("Python", info.get("python_version", "--")),
        ("Textual", info.get("textual_version", "--")),
        ("PID", str(info.get("pid", "--"))),
    ]

    text = Text()
    text.append("Server Info", style=f"bold {p.info}")
    text.append("\n")

    label_width = max(len(label) for label, _ in rows)

    for label, value in rows:
        text.append("  ")
        text.append("{:<{}}".format(label + ":", label_width + 1), style="bold")
        text.append(" ")
        text.append(value, style=f"{p.info}")
        text.append("\n")

    # Usage hint at bottom
    text.append("\n  ")
    text.append("Usage: ", style="bold")
    text.append("ANTHROPIC_BASE_URL=", style="dim")
    text.append(proxy_url, style=f"bold {p.info}")
    text.append(" claude", style="dim")

    return text
