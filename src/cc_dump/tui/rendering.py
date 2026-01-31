"""Rich rendering for FormattedBlock structures in the TUI.

Converts structured IR from formatting.py into Rich Text objects for display.
"""

from typing import Callable

from rich.text import Text

from cc_dump.formatting import (
    FormattedBlock, SeparatorBlock, HeaderBlock, HttpHeadersBlock, MetadataBlock,
    SystemLabelBlock, TrackedContentBlock, RoleBlock, TextContentBlock,
    ToolUseBlock, ToolResultBlock, ImageBlock, UnknownTypeBlock,
    StreamInfoBlock, StreamToolUseBlock, TextDeltaBlock, StopReasonBlock,
    ErrorBlock, ProxyErrorBlock, LogBlock, NewlineBlock, TurnBudgetBlock,
    make_diff_lines,
)

import cc_dump.palette


def _build_role_styles() -> dict[str, str]:
    p = cc_dump.palette.PALETTE
    return {
        "user": f"bold {p.user}",
        "assistant": f"bold {p.assistant}",
        "system": f"bold {p.system}",
    }


def _build_tag_styles() -> list[tuple[str, str]]:
    p = cc_dump.palette.PALETTE
    return [p.fg_on_bg(i) for i in range(min(p.count, 12))]


def _build_msg_colors() -> list[str]:
    p = cc_dump.palette.PALETTE
    return [p.msg_color(i) for i in range(6)]


def _build_filter_indicators() -> dict[str, tuple[str, str]]:
    p = cc_dump.palette.PALETTE
    return {
        "headers": ("▌", p.filter_color("headers")),
        "tools": ("▌", p.filter_color("tools")),
        "system": ("▌", p.filter_color("system")),
        "expand": ("▌", p.filter_color("expand")),
        "metadata": ("▌", p.filter_color("metadata")),
    }


ROLE_STYLES = _build_role_styles()
TAG_STYLES = _build_tag_styles()
MSG_COLORS = _build_msg_colors()
FILTER_INDICATORS = _build_filter_indicators()


# Type alias for render function signature
BlockRenderer = Callable[[FormattedBlock, dict], Text | None]


def _add_filter_indicator(text: Text, filter_name: str) -> Text:
    """Add a colored indicator to show which filter controls this content."""
    if filter_name not in FILTER_INDICATORS:
        return text

    symbol, color = FILTER_INDICATORS[filter_name]
    indicator = Text()
    indicator.append(symbol + " ", style=f"bold {color}")
    indicator.append(text)
    return indicator


def _render_separator(block: SeparatorBlock, filters: dict) -> Text | None:
    """Render a separator line."""
    if not filters.get("headers", False):
        return None
    char = "\u2500" if block.style == "heavy" else "\u2504"
    return Text(char * 70, style="dim")


def _render_header(block: HeaderBlock, filters: dict) -> Text | None:
    """Render a request/response header."""
    if not filters.get("headers", False):
        return None
    p = cc_dump.palette.PALETTE
    if block.header_type == "request":
        t = Text()
        t.append(" {} ".format(block.label), style=f"bold {p.info}")
        t.append(" ({})".format(block.timestamp), style="dim")
        return _add_filter_indicator(t, "headers")
    else:
        t = Text()
        t.append(" RESPONSE ", style=f"bold {p.success}")
        t.append(" ({})".format(block.timestamp), style="dim")
        return _add_filter_indicator(t, "headers")


def _render_http_headers(block: HttpHeadersBlock, filters: dict) -> Text | None:
    """Render HTTP request or response headers."""
    if not filters.get("headers", False):
        return None

    p = cc_dump.palette.PALETTE
    t = Text()
    if block.header_type == "response":
        t.append("  HTTP {} ".format(block.status_code), style=f"bold {p.info}")
    else:
        t.append("  HTTP Headers ", style=f"bold {p.info}")

    # Render headers sorted alphabetically
    for key in sorted(block.headers.keys()):
        value = block.headers[key]
        t.append("\n    {}: ".format(key), style=f"dim {p.info}")
        t.append(value, style="dim")

    return _add_filter_indicator(t, "headers")


def _render_metadata(block: MetadataBlock, filters: dict) -> Text | None:
    """Render metadata block with model, max_tokens, stream, etc."""
    if not filters.get("metadata", False):
        return None
    parts = []
    parts.append("model: ")
    parts.append(("{}".format(block.model), "bold"))
    parts.append(" | max_tokens: {}".format(block.max_tokens))
    parts.append(" | stream: {}".format(block.stream))
    if block.tool_count:
        parts.append(" | tools: {}".format(block.tool_count))

    t = Text()
    t.append("  ", style="dim")
    for part in parts:
        if isinstance(part, tuple):
            t.append(part[0], style=part[1])
        else:
            t.append(part)
    t.stylize("dim")
    return _add_filter_indicator(t, "metadata")


def _render_turn_budget_block(block: TurnBudgetBlock, filters: dict) -> Text | None:
    """Render turn budget block (wrapper for filter check)."""
    if not filters.get("expand", False):
        return None
    return _render_turn_budget(block)


def _render_system_label(block: SystemLabelBlock, filters: dict) -> Text | None:
    """Render system label."""
    if not filters.get("system", False):
        return None
    t = Text("SYSTEM:", style=f"bold {cc_dump.palette.PALETTE.system}")
    return _add_filter_indicator(t, "system")


def _render_tracked_content_block(block: TrackedContentBlock, filters: dict) -> Text | None:
    """Render tracked content block (wrapper for filter check)."""
    # System content is controlled by "system" filter
    if not filters.get("system", False):
        return None
    return _render_tracked_content(block, filters)


def _render_role(block: RoleBlock, filters: dict) -> Text | None:
    """Render role label (USER, ASSISTANT, SYSTEM)."""
    role_lower = block.role.lower()
    if role_lower == "system" and not filters.get("system", False):
        return None
    style = ROLE_STYLES.get(role_lower, "bold magenta")
    t = Text(block.role.upper(), style=style)
    if block.timestamp:
        t.append(f"  {block.timestamp}", style="dim")
    return t


def _render_text_content(block: TextContentBlock, filters: dict) -> Text | None:
    """Render text content with proper indentation."""
    if not block.text:
        return None
    return _indent_text(block.text, block.indent)


def _render_tool_use(block: ToolUseBlock, filters: dict) -> Text | None:
    """Render tool use block."""
    if not filters.get("tools", False):
        return None
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    t = Text("  ")
    t.append("[tool_use]", style="bold {}".format(color))
    t.append(" {}".format(block.name))
    if block.detail:
        t.append(" {}".format(block.detail), style="dim")
    t.append(" ({} bytes)".format(block.input_size))
    return _add_filter_indicator(t, "tools")


def _render_tool_result(block: ToolResultBlock, filters: dict) -> Text | None:
    """Render tool result block. Shows full or summary based on tools filter."""
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]

    if filters.get("tools", False):
        # Full mode: detailed display
        label = "[tool_result:error]" if block.is_error else "[tool_result]"
        t = Text("  ")
        t.append(label, style="bold {}".format(color))
        if block.tool_name:
            t.append(" {}".format(block.tool_name))
        if block.detail:
            t.append(" {}".format(block.detail), style="dim")
        t.append(" ({} bytes)".format(block.size))
        return _add_filter_indicator(t, "tools")
    else:
        # Summary mode: compact, dimmed
        if block.tool_name:
            label = "[{}:error]".format(block.tool_name) if block.is_error else "[{}]".format(block.tool_name)
        else:
            label = "[tool_result:error]" if block.is_error else "[tool_result]"
        t = Text("  ")
        t.append(label, style="dim {}".format(color))
        if block.detail:
            t.append(" {}".format(block.detail), style="dim")
        t.append(" ({} bytes)".format(block.size), style="dim")
        return t


def _render_image(block: ImageBlock, filters: dict) -> Text | None:
    """Render image block placeholder."""
    return Text("  [image: {}]".format(block.media_type), style="dim")


def _render_unknown_type(block: UnknownTypeBlock, filters: dict) -> Text | None:
    """Render unknown block type."""
    return Text("  [{}]".format(block.block_type), style="dim")


def _render_stream_info(block: StreamInfoBlock, filters: dict) -> Text | None:
    """Render stream info block."""
    if not filters.get("metadata", False):
        return None
    t = Text("  ", style="dim")
    t.append("model: ")
    t.append(block.model, style="bold")
    return _add_filter_indicator(t, "metadata")


def _render_stream_tool_use(block: StreamToolUseBlock, filters: dict) -> Text | None:
    """Render stream tool use block."""
    if not filters.get("tools", False):
        return None
    t = Text("\n  ")
    t.append("[tool_use]", style=f"bold {cc_dump.palette.PALETTE.info}")
    t.append(" " + block.name)
    return _add_filter_indicator(t, "tools")


def _render_text_delta(block: TextDeltaBlock, filters: dict) -> Text | None:
    """Render text delta block."""
    return Text(block.text)


def _render_stop_reason(block: StopReasonBlock, filters: dict) -> Text | None:
    """Render stop reason block."""
    if not filters.get("metadata", False):
        return None
    t = Text("\n  stop: " + block.reason, style="dim")
    return _add_filter_indicator(t, "metadata")


def _render_error(block: ErrorBlock, filters: dict) -> Text | None:
    """Render error block."""
    return Text("\n  [HTTP {} {}]".format(block.code, block.reason), style=f"bold {cc_dump.palette.PALETTE.error}")


def _render_proxy_error(block: ProxyErrorBlock, filters: dict) -> Text | None:
    """Render proxy error block."""
    return Text("\n  [PROXY ERROR: {}]".format(block.error), style=f"bold {cc_dump.palette.PALETTE.error}")


def _render_log(block: LogBlock, filters: dict) -> Text | None:
    """Render log block."""
    return Text("  {} {} {}".format(block.command, block.path, block.status), style="dim")


def _render_newline(block: NewlineBlock, filters: dict) -> Text | None:
    """Render newline block."""
    return Text("")


# Registry mapping block type NAME to renderer function.
# Uses class names (strings) instead of class objects so that blocks created
# before a hot-reload still match after the module is reloaded (class identity
# changes on reload, but __name__ stays the same).
BLOCK_RENDERERS: dict[str, BlockRenderer] = {
    "SeparatorBlock": _render_separator,
    "HeaderBlock": _render_header,
    "HttpHeadersBlock": _render_http_headers,
    "MetadataBlock": _render_metadata,
    "TurnBudgetBlock": _render_turn_budget_block,
    "SystemLabelBlock": _render_system_label,
    "TrackedContentBlock": _render_tracked_content_block,
    "RoleBlock": _render_role,
    "TextContentBlock": _render_text_content,
    "ToolUseBlock": _render_tool_use,
    "ToolResultBlock": _render_tool_result,
    "ImageBlock": _render_image,
    "UnknownTypeBlock": _render_unknown_type,
    "StreamInfoBlock": _render_stream_info,
    "StreamToolUseBlock": _render_stream_tool_use,
    "TextDeltaBlock": _render_text_delta,
    "StopReasonBlock": _render_stop_reason,
    "ErrorBlock": _render_error,
    "ProxyErrorBlock": _render_proxy_error,
    "LogBlock": _render_log,
    "NewlineBlock": _render_newline,
}


# Mapping: block type NAME -> filter key that controls its visibility.
# None means always visible (never filtered out).
# Uses class names for hot-reload safety (same reason as BLOCK_RENDERERS).
BLOCK_FILTER_KEY: dict[str, str | None] = {
    "SeparatorBlock": "headers",
    "HeaderBlock": "headers",
    "HttpHeadersBlock": "headers",
    "MetadataBlock": "metadata",
    "TurnBudgetBlock": "expand",
    "SystemLabelBlock": "system",
    "TrackedContentBlock": "system",
    "RoleBlock": "system",             # _render_role checks filters["system"] for system roles
    "TextContentBlock": None,
    "ToolUseBlock": "tools",
    "ToolResultBlock": None,  # Always visible (summary or full based on tools filter)
    "ImageBlock": None,
    "UnknownTypeBlock": None,
    "StreamInfoBlock": "metadata",
    "StreamToolUseBlock": "tools",
    "TextDeltaBlock": None,
    "StopReasonBlock": "metadata",
    "ErrorBlock": None,
    "ProxyErrorBlock": None,
    "LogBlock": None,
    "NewlineBlock": None,
}


def render_block(block: FormattedBlock, filters: dict) -> Text | None:
    """Render a FormattedBlock to a Rich Text object.

    Returns None if the block should be filtered out based on filters dict.
    """
    renderer = BLOCK_RENDERERS.get(type(block).__name__)
    if renderer is None:
        return None  # Unknown block type - graceful degradation
    return renderer(block, filters)


def render_blocks(blocks: list[FormattedBlock], filters: dict) -> list[Text]:
    """Render a list of FormattedBlock to Rich Text objects, applying filters."""
    rendered = []
    for block in blocks:
        r = render_block(block, filters)
        if r is not None:
            rendered.append(r)
    return rendered


def combine_rendered_texts(texts: list[Text]) -> Text:
    """Join rendered Text objects into a single Text with newline separators."""
    if not texts:
        return Text()
    if len(texts) == 1:
        return texts[0]
    combined = Text()
    for i, t in enumerate(texts):
        if i > 0:
            combined.append("\n")
        combined.append(t)
    return combined


def render_turn_to_strips(
    blocks: list[FormattedBlock],
    filters: dict,
    console,
    width: int,
    wrap: bool = True,
) -> tuple[list, dict[int, int]]:
    """Render blocks to Strip objects for Line API storage.

    Renders each block individually to track block-to-strip boundaries,
    enabling stable scroll anchoring across filter changes.

    Args:
        blocks: FormattedBlock list for one turn
        filters: Current filter state
        console: Rich Console instance (from app.console)
        width: Render width in cells
        wrap: Enable word wrapping

    Returns:
        (strips, block_strip_map) — pre-rendered lines and a dict mapping
        block index (in the blocks list) to its first strip line index.
    """
    from rich.segment import Segment
    from textual.strip import Strip

    render_options = console.options
    if not wrap:
        render_options = render_options.update(overflow="ignore", no_wrap=True)
    render_options = render_options.update_width(width)

    all_strips: list[Strip] = []
    block_strip_map: dict[int, int] = {}

    for i, block in enumerate(blocks):
        text = render_block(block, filters)
        if text is None:
            continue

        block_strip_map[i] = len(all_strips)

        segments = console.render(text, render_options)
        lines = list(Segment.split_lines(segments))
        if lines:
            block_strips = Strip.from_lines(lines)
            for strip in block_strips:
                strip.adjust_cell_length(width)
            all_strips.extend(block_strips)

    return all_strips, block_strip_map


def _render_tracked_content(block: TrackedContentBlock, filters: dict) -> Text:
    """Render a TrackedContentBlock with tag colors."""
    fg, bg = TAG_STYLES[block.color_idx % len(TAG_STYLES)]
    tag_style = "bold {} on {}".format(fg, bg)

    if block.status == "new":
        content_len = len(block.content)
        t = Text(block.indent + "  ")
        t.append(" {} ".format(block.tag_id), style=tag_style)
        t.append(" NEW ({} chars):\n".format(content_len))
        if filters.get("expand", False):
            t.append(_indent_text(block.content, block.indent + "    "))
        else:
            t.append(Text(block.indent + "    ...", style="dim"))
        return _add_filter_indicator(t, "system")

    elif block.status == "ref":
        t = Text(block.indent + "  ")
        t.append(" {} ".format(block.tag_id), style=tag_style)
        t.append(" (unchanged)")
        return _add_filter_indicator(t, "system")

    elif block.status == "changed":
        old_len = len(block.old_content)
        new_len = len(block.new_content)
        t = Text(block.indent + "  ")
        t.append(" {} ".format(block.tag_id), style=tag_style)
        t.append(" CHANGED ({} -> {} chars):\n".format(old_len, new_len))
        if filters.get("expand", False):
            diff_lines = make_diff_lines(block.old_content, block.new_content)
            t.append(_render_diff(diff_lines, block.indent + "    "))
        else:
            t.append(Text(block.indent + "    ...", style="dim"))
        return _add_filter_indicator(t, "system")

    return Text("")


def _render_diff(diff_lines: list, indent: str) -> Text:
    """Render diff lines with color-coded additions/deletions."""
    t = Text()
    for i, (kind, text) in enumerate(diff_lines):
        if i > 0:
            t.append("\n")
        p = cc_dump.palette.PALETTE
        if kind == "hunk":
            t.append(indent + text, style="dim")
        elif kind == "add":
            t.append(indent + "+ " + text, style=p.success)
        elif kind == "del":
            t.append(indent + "- " + text, style=p.error)
    return t


def _indent_text(text: str, indent: str) -> Text:
    """Indent each line of text with the given prefix."""
    lines = text.splitlines()
    t = Text()
    for i, line in enumerate(lines):
        if i > 0:
            t.append("\n")
        t.append(indent + line)
    return t


def _fmt_tokens(n: int) -> str:
    """Format token count for compact display: 1.2k, 68.9k, etc."""
    if n >= 1000:
        return "{:.1f}k".format(n / 1000)
    return str(n)


def _pct(part: int, total: int) -> str:
    """Format percentage."""
    if total == 0:
        return "0%"
    return "{:.0f}%".format(100 * part / total)


def _render_turn_budget(block: TurnBudgetBlock) -> Text:
    """Render TurnBudget as a compact multi-line summary."""
    b = block.budget
    total = b.total_est

    sys_tok = b.system_tokens_est + b.tool_defs_tokens_est
    conv_tok = b.conversation_tokens_est
    tool_tok = b.tool_use_tokens_est + b.tool_result_tokens_est

    p = cc_dump.palette.PALETTE
    t = Text("  ")
    t.append("Context: ", style="bold")
    t.append("{} tok".format(_fmt_tokens(total)))
    t.append(" | sys: {} ({})".format(_fmt_tokens(sys_tok), _pct(sys_tok, total)), style=f"dim {p.info}")
    t.append(" | tools: {} ({})".format(_fmt_tokens(tool_tok), _pct(tool_tok, total)), style=f"dim {p.warning}")
    t.append(" | conv: {} ({})".format(_fmt_tokens(conv_tok), _pct(conv_tok, total)), style=f"dim {p.success}")

    # Tool result breakdown by name
    if block.tool_result_by_name:
        parts = []
        # Sort by tokens descending
        sorted_tools = sorted(block.tool_result_by_name.items(), key=lambda x: x[1], reverse=True)
        for name, tokens in sorted_tools[:5]:
            parts.append("{}: {}".format(name, _fmt_tokens(tokens)))
        t.append("\n    tool_use: {} | tool_results: {} ({})".format(
            _fmt_tokens(b.tool_use_tokens_est),
            _fmt_tokens(b.tool_result_tokens_est),
            ", ".join(parts),
        ), style="dim")

    # Cache info (if actual data is available)
    if b.actual_input_tokens > 0 or b.actual_cache_read_tokens > 0:
        t.append("\n    ")
        t.append("Cache: ", style="bold")
        t.append("{} read ({})".format(
            _fmt_tokens(b.actual_cache_read_tokens),
            _pct(b.actual_cache_read_tokens, b.actual_input_tokens + b.actual_cache_read_tokens),
        ), style=f"dim {p.info}")
        if b.actual_cache_creation_tokens > 0:
            t.append(" | {} created".format(_fmt_tokens(b.actual_cache_creation_tokens)), style=f"dim {p.warning}")
        t.append(" | {} fresh".format(_fmt_tokens(b.actual_input_tokens)), style="dim")

    return _add_filter_indicator(t, "expand")
