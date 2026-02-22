"""Panel rendering logic - pure functions for building display text.

This module contains all the display formatting logic for panels. It's separated
so it can be hot-reloaded without affecting the live widget instances.
"""

import cc_dump.analysis
import cc_dump.palette
import cc_dump.tui.input_modes
from rich.text import Text
from collections.abc import Callable

# [LAW:one-source-of-truth] Shared compact token formatter lives in analysis.py.
_fmt_tokens = cc_dump.analysis.fmt_tokens


def _dashboard_tabs(active: str) -> str:
    tabs = ["summary", "timeline", "models"]
    labels = []
    for tab in tabs:
        labels.append(tab.upper() if tab == active else tab)
    return "Analytics: {}  (Tab/, cycle)".format(" | ".join(labels))


def render_analytics_summary(snapshot: dict) -> str:
    """Render dashboard summary view from canonical snapshot data."""
    summary = snapshot.get("summary", {})
    turn_count = int(summary.get("turn_count", 0))
    if turn_count == 0:
        return _dashboard_tabs("summary") + "\nSummary: (no turns yet)"

    input_tokens = int(summary.get("input_tokens", 0))
    output_tokens = int(summary.get("output_tokens", 0))
    cache_read_tokens = int(summary.get("cache_read_tokens", 0))
    cache_creation_tokens = int(summary.get("cache_creation_tokens", 0))
    input_total = int(summary.get("input_total", 0))
    total_tokens = int(summary.get("total_tokens", 0))
    cache_pct = float(summary.get("cache_pct", 0.0))
    cost_usd = float(summary.get("cost_usd", 0.0))
    cache_savings_usd = float(summary.get("cache_savings_usd", 0.0))
    active_model_count = int(summary.get("active_model_count", 0))
    latest_model_label = str(summary.get("latest_model_label", "Unknown"))
    main_turns = int(summary.get("main_turns", 0))
    subagent_turns = int(summary.get("subagent_turns", 0))
    active_subagent_streams = int(summary.get("active_subagent_streams", 0))
    fresh_tokens = input_tokens

    lines = [
        _dashboard_tabs("summary"),
        "Summary:",
        "  Turns: {}  Total: {}  Cost: ${:.4f}".format(
            turn_count, _fmt_tokens(total_tokens), cost_usd
        ),
        "  Input: {} fresh + {} cached = {}  |  Output: {}".format(
            _fmt_tokens(fresh_tokens),
            _fmt_tokens(cache_read_tokens),
            _fmt_tokens(input_total),
            _fmt_tokens(output_tokens),
        ),
        "  Cache: {:.0f}% hit  |  Writes: {}  |  Savings: ${:.4f}".format(
            cache_pct, _fmt_tokens(cache_creation_tokens), cache_savings_usd
        ),
        "  Models: {} active  |  Latest: {}".format(
            active_model_count,
            latest_model_label,
        ),
        "  Lanes: {} main turns | {} subagent turns | {} active subagent streams".format(
            main_turns,
            subagent_turns,
            active_subagent_streams,
        ),
    ]
    return "\n".join(lines)


def _sparkline(values: list[int]) -> str:
    if not values:
        return ""
    glyphs = "▁▂▃▄▅▆▇█"
    high = max(values)
    if high <= 0:
        return glyphs[0] * len(values)
    # [LAW:dataflow-not-control-flow] Each sample always maps through the same transform.
    return "".join(glyphs[min((value * (len(glyphs) - 1)) // high, len(glyphs) - 1)] for value in values)


def render_analytics_timeline(snapshot: dict, max_rows: int = 12) -> str:
    """Render dashboard timeline view from canonical snapshot data."""
    rows = snapshot.get("timeline", [])
    if not rows:
        return _dashboard_tabs("timeline") + "\nTimeline: (no turns yet)"

    tail = rows[-max_rows:]
    trend = _sparkline([int(row.get("input_total", 0)) for row in tail])
    lines = [
        _dashboard_tabs("timeline"),
        "Timeline:",
        f"  Trend In: {trend}",
        "  {:>4}  {:<11}  {:>7}  {:>7}  {:>6}  {:>7}".format(
            "Turn",
            "Model",
            "In",
            "Out",
            "Cache%",
            "\u0394In",
        ),
    ]
    for row in tail:
        delta_input = int(row.get("delta_input", 0))
        delta_str = (
            ("+" if delta_input >= 0 else "") + _fmt_tokens(delta_input)
            if delta_input != 0
            else "--"
        )
        lines.append(
            "  {:>4}  {:<11}  {:>7}  {:>7}  {:>6}  {:>7}".format(
                int(row.get("sequence_num", 0)),
                cc_dump.analysis.format_model_ultra_short(str(row.get("model", "")))[:11],
                _fmt_tokens(int(row.get("input_total", 0))),
                _fmt_tokens(int(row.get("output_tokens", 0))),
                "{:.0f}%".format(float(row.get("cache_pct", 0.0))),
                delta_str,
            )
        )
    return "\n".join(lines)


def render_analytics_models(snapshot: dict) -> str:
    """Render dashboard model breakdown view from canonical snapshot data."""
    rows = snapshot.get("models", [])
    if not rows:
        return _dashboard_tabs("models") + "\nModels: (no turns yet)"

    lines = [
        _dashboard_tabs("models"),
        "Models:",
        "  {:<13} {:>5}  {:>8}  {:>8}  {:>6}  {:>6}  {:>9}".format(
            "Model",
            "Turns",
            "Input",
            "Output",
            "Cache%",
            "Share",
            "Cost",
        ),
    ]
    for row in rows:
        lines.append(
            "  {:<13} {:>5}  {:>8}  {:>8}  {:>6}  {:>6}  {:>9}".format(
                str(row.get("model_label", "Unknown"))[:13],
                int(row.get("turns", 0)),
                _fmt_tokens(int(row.get("input_total", 0))),
                _fmt_tokens(int(row.get("output_tokens", 0))),
                "{:.0f}%".format(float(row.get("cache_pct", 0.0))),
                "{:.0f}%".format(float(row.get("token_share_pct", 0.0))),
                "${:.3f}".format(float(row.get("cost_usd", 0.0))),
            )
        )
    return "\n".join(lines)


# [LAW:dataflow-not-control-flow] Mode-to-renderer dispatch for unified analytics dashboard.
_ANALYTICS_VIEW_RENDERERS = {
    "summary": render_analytics_summary,
    "timeline": render_analytics_timeline,
    "models": render_analytics_models,
}  # type: dict[str, Callable[[dict], str]]


def render_analytics_panel(snapshot: dict, view_mode: str) -> str:
    """Render unified analytics dashboard by view mode."""
    renderer = _ANALYTICS_VIEW_RENDERERS.get(view_mode, render_analytics_summary)
    return renderer(snapshot)


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

    # [LAW:dataflow-not-control-flow] Color selection driven by data, not control flow.
    # Use theme semantic colors rather than fixed color names.
    tc = cc_dump.tui.rendering.get_theme_colors()
    if context_pct < 60.0:
        ctx_color = tc.success
    elif context_pct < 80.0:
        ctx_color = tc.warning
    else:
        ctx_color = tc.error

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


def _format_age(age_s: float) -> str:
    """Format an age in seconds to a human-readable string.

    Tiered formatting:
    - <60s: per-second ("42s ago")
    - <3600s: per-minute ("~3 min ago")
    - <43200s: 30-min resolution ("~2.5hr ago")
    - >=43200s: capped ("12+ hours ago")
    """
    if age_s < 60:
        return "{:.0f}s ago".format(age_s)
    if age_s < 3600:
        return "~{:.0f} min ago".format(age_s / 60)
    if age_s < 43200:
        hours = round(age_s / 1800) / 2
        return "~{:g}hr ago".format(hours)
    return "12+ hours ago"


def render_session_panel(
    connected: bool,
    session_id: str | None,
    last_message_time: float | None,
) -> tuple[Text, tuple[int, int] | None]:
    """Render the session panel display text.

    // [LAW:dataflow-not-control-flow] All fields always rendered; connected drives indicator style.

    Args:
        connected: Whether a Claude Code client is considered connected
        session_id: Current session UUID (or None)
        last_message_time: monotonic time of last message (or None)

    Returns:
        Tuple of (Rich Text, session_id_span or None).
        session_id_span is (start, end) char offsets of the session ID text for click detection.
    """
    import time

    p = cc_dump.palette.PALETTE

    # Indicator + age inline
    result = Text()
    indicator = "\u25cf" if connected else "\u25cb"
    indicator_style = f"bold {p.info}" if connected else "dim"
    label = "Connected" if connected else "Disconnected"
    result.append(indicator, style=indicator_style)
    result.append(" ")
    result.append(label, style=indicator_style)

    # Age in parens after connection status
    age_str = "--"
    if last_message_time is not None:
        age_s = time.monotonic() - last_message_time
        age_str = _format_age(age_s)
    result.append(" (")
    result.append(age_str, style="" if last_message_time is not None else "dim")
    result.append(")")

    # Session ID — full, with span tracking for click-to-copy
    result.append(" | Session: ")
    session_display = session_id or "--"
    span_start = len(result)
    result.append(session_display, style=f"{p.info}" if session_id else "dim")
    span_end = len(result)

    session_id_span = (span_start, span_end) if session_id else None

    return result, session_id_span


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


def render_keys_panel() -> Text:
    """Render the keyboard shortcuts panel display.

    // [LAW:one-source-of-truth] KEY_GROUPS from input_modes is the sole data source.

    Returns:
        Rich Text object with grouped key shortcuts
    """
    p = cc_dump.palette.PALETTE
    key_groups = cc_dump.tui.input_modes.KEY_GROUPS

    text = Text()
    text.append("Keys", style=f"bold {p.info}")
    text.append("\n")

    for group_title, keys in key_groups:
        text.append(" ")
        text.append(group_title, style="bold underline")
        text.append("\n")
        for key_display, description in keys:
            text.append("  ")
            text.append("{:>6}".format(key_display), style=f"bold {p.info}")
            text.append("  ")
            text.append(description, style="dim")
            text.append("\n")

    return text
