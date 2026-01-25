"""Rich rendering for FormattedBlock structures in the TUI.

Converts structured IR from formatting.py into Rich Text objects for display.
"""

from rich.text import Text

from cc_dump.formatting import (
    FormattedBlock, SeparatorBlock, HeaderBlock, MetadataBlock,
    SystemLabelBlock, TrackedContentBlock, RoleBlock, TextContentBlock,
    ToolUseBlock, ToolResultBlock, ImageBlock, UnknownTypeBlock,
    StreamInfoBlock, StreamToolUseBlock, TextDeltaBlock, StopReasonBlock,
    ErrorBlock, ProxyErrorBlock, LogBlock, NewlineBlock, TurnBudgetBlock,
    make_diff_lines,
)

# Rich style equivalents of the ANSI color scheme
ROLE_STYLES = {
    "user": "bold cyan",
    "assistant": "bold green",
    "system": "bold yellow",
}

# Tag color palette (fg, bg) for content tracking
TAG_STYLES = [
    ("cyan", "blue"),
    ("black", "green"),
    ("black", "yellow"),
    ("white", "magenta"),
    ("white", "red"),
    ("white", "blue"),
    ("black", "white"),
    ("black", "cyan"),
]

MSG_COLORS = ["cyan", "green", "yellow", "magenta", "blue", "red"]


def render_block(block: FormattedBlock, filters: dict) -> Text | None:
    """Render a FormattedBlock to a Rich Text object.

    Returns None if the block should be filtered out based on filters dict.
    """

    if isinstance(block, SeparatorBlock):
        if not filters.get("headers", False):
            return None
        char = "\u2500" if block.style == "heavy" else "\u2504"
        return Text(char * 70, style="dim")

    if isinstance(block, HeaderBlock):
        if not filters.get("headers", False):
            return None
        if block.header_type == "request":
            t = Text()
            t.append(" {} ".format(block.label), style="bold cyan")
            t.append(" ({})".format(block.timestamp), style="dim")
            return t
        else:
            t = Text()
            t.append(" RESPONSE ", style="bold green")
            t.append(" ({})".format(block.timestamp), style="dim")
            return t

    if isinstance(block, MetadataBlock):
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
        return t

    if isinstance(block, TurnBudgetBlock):
        if not filters.get("expand", False):
            return None
        return _render_turn_budget(block)

    if isinstance(block, SystemLabelBlock):
        if not filters.get("system", False):
            return None
        return Text("SYSTEM:", style="bold yellow")

    if isinstance(block, TrackedContentBlock):
        # System content is controlled by "system" filter
        if not filters.get("system", False):
            return None
        return _render_tracked_content(block, filters)

    if isinstance(block, RoleBlock):
        role_lower = block.role.lower()
        if role_lower == "system" and not filters.get("system", False):
            return None
        style = ROLE_STYLES.get(role_lower, "bold magenta")
        return Text(block.role.upper(), style=style)

    if isinstance(block, TextContentBlock):
        if not block.text:
            return None
        return _indent_text(block.text, block.indent)

    if isinstance(block, ToolUseBlock):
        if not filters.get("tools", False):
            return None
        color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
        t = Text("  ")
        t.append("[tool_use]", style="bold {}".format(color))
        t.append(" {} ({} bytes)".format(block.name, block.input_size))
        return t

    if isinstance(block, ToolResultBlock):
        if not filters.get("tools", False):
            return None
        color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
        label = "[tool_result:error]" if block.is_error else "[tool_result]"
        t = Text("  ")
        t.append(label, style="bold {}".format(color))
        t.append(" ({} bytes)".format(block.size))
        return t

    if isinstance(block, ImageBlock):
        return Text("  [image: {}]".format(block.media_type), style="dim")

    if isinstance(block, UnknownTypeBlock):
        return Text("  [{}]".format(block.block_type), style="dim")

    if isinstance(block, StreamInfoBlock):
        if not filters.get("metadata", False):
            return None
        t = Text("  ", style="dim")
        t.append("model: ")
        t.append(block.model, style="bold")
        return t

    if isinstance(block, StreamToolUseBlock):
        if not filters.get("tools", False):
            return None
        t = Text("\n  ")
        t.append("[tool_use]", style="bold cyan")
        t.append(" " + block.name)
        return t

    if isinstance(block, TextDeltaBlock):
        return Text(block.text)

    if isinstance(block, StopReasonBlock):
        if not filters.get("metadata", False):
            return None
        return Text("\n  stop: " + block.reason, style="dim")

    if isinstance(block, ErrorBlock):
        return Text("\n  [HTTP {} {}]".format(block.code, block.reason), style="bold red")

    if isinstance(block, ProxyErrorBlock):
        return Text("\n  [PROXY ERROR: {}]".format(block.error), style="bold red")

    if isinstance(block, LogBlock):
        return Text("  {} {} {}".format(block.command, block.path, block.status), style="dim")

    if isinstance(block, NewlineBlock):
        return Text("")

    return None


def render_blocks(blocks: list[FormattedBlock], filters: dict) -> list[Text]:
    """Render a list of FormattedBlock to Rich Text objects, applying filters."""
    rendered = []
    for block in blocks:
        r = render_block(block, filters)
        if r is not None:
            rendered.append(r)
    return rendered


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
        return t

    elif block.status == "ref":
        t = Text(block.indent + "  ")
        t.append(" {} ".format(block.tag_id), style=tag_style)
        t.append(" (unchanged)")
        return t

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
        return t

    return Text("")


def _render_diff(diff_lines: list, indent: str) -> Text:
    """Render diff lines with color-coded additions/deletions."""
    t = Text()
    for i, (kind, text) in enumerate(diff_lines):
        if i > 0:
            t.append("\n")
        if kind == "hunk":
            t.append(indent + text, style="dim")
        elif kind == "add":
            t.append(indent + "+ " + text, style="green")
        elif kind == "del":
            t.append(indent + "- " + text, style="red")
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

    t = Text("  ")
    t.append("Context: ", style="bold")
    t.append("{} tok".format(_fmt_tokens(total)))
    t.append(" | sys: {} ({})".format(_fmt_tokens(sys_tok), _pct(sys_tok, total)), style="dim cyan")
    t.append(" | tools: {} ({})".format(_fmt_tokens(tool_tok), _pct(tool_tok, total)), style="dim yellow")
    t.append(" | conv: {} ({})".format(_fmt_tokens(conv_tok), _pct(conv_tok, total)), style="dim green")

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
        ), style="dim cyan")
        if b.actual_cache_creation_tokens > 0:
            t.append(" | {} created".format(_fmt_tokens(b.actual_cache_creation_tokens)), style="dim yellow")
        t.append(" | {} fresh".format(_fmt_tokens(b.actual_input_tokens)), style="dim")

    return t
