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
)

import cc_dump.palette


def _build_role_styles() -> dict[str, str]:
    p = cc_dump.palette.PALETTE
    return {
        "user": f"bold {p.user}",
        "assistant": f"bold {p.assistant}",
        "system": f"bold {p.system}",
        "tool_result": f"dim {p.user}",
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
        "user": ("▌", p.filter_color("user")),
        "assistant": ("▌", p.filter_color("assistant")),
    }


ROLE_STYLES = _build_role_styles()
TAG_STYLES = _build_tag_styles()
MSG_COLORS = _build_msg_colors()
FILTER_INDICATORS = _build_filter_indicators()

# Block types that support per-block expand/collapse via click
_EXPANDABLE_BLOCK_TYPES = frozenset({"TrackedContentBlock", "TurnBudgetBlock"})


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
    """Render HTTP headers block."""
    if not filters.get("headers", False):
        return None
    t = Text()
    for i, (key, value) in enumerate(block.headers):
        if i > 0:
            t.append("\n")
        t.append(f"  {key}: ", style="dim")
        t.append(value)
    return _add_filter_indicator(t, "headers")


def _render_metadata(block: MetadataBlock, filters: dict) -> Text | None:
    """Render metadata block."""
    if not filters.get("metadata", False):
        return None
    t = Text()
    for i, (key, value) in enumerate(block.data):
        if i > 0:
            t.append("\n")
        t.append(f"  {key}: ", style="dim")
        t.append(value)
    return _add_filter_indicator(t, "metadata")


def _render_system_label(block: SystemLabelBlock, filters: dict) -> Text | None:
    """Render system label block."""
    if not filters.get("system", False):
        return None
    p = cc_dump.palette.PALETTE
    return Text("\n" + block.label, style=f"bold {p.system}")


def _indent_text(text: str, indent: str) -> Text:
    """Apply indent prefix to each line, preserving existing formatting."""
    if not indent:
        return Text(text)
    lines = text.splitlines()
    t = Text()
    for i, line in enumerate(lines):
        if i > 0:
            t.append("\n")
        t.append(indent + line)
    return t


def _render_tracked_content(block: TrackedContentBlock, filters: dict, expanded: bool | None = None) -> Text | None:
    """Render tracked content with expand/collapse based on filter or override.

    Args:
        block: TrackedContentBlock to render
        filters: Current filter state
        expanded: Optional per-block override for expand state
    """
    if not filters.get("expand", False) and not block.track_changes:
        return None

    # Determine expand state
    is_expanded = expanded if expanded is not None else filters.get("expand", False)

    color = TAG_STYLES[block.tag_idx % len(TAG_STYLES)]
    fg_hex, bg_hex = color
    t = Text()

    arrow = "\u25bc" if is_expanded else "\u25b6"
    t.append(
        "{}{}:".format(block.indent, arrow),
        style=f"bold {fg_hex} on {bg_hex}"
    )
    t.append(" " + block.label, style=f"bold {fg_hex}")

    if is_expanded:
        if block.diff_lines:
            for line in block.diff_lines:
                t.append("\n" + block.indent + "    " + line[0], style=line[1])
        else:
            t.append("\n")
            t.append(_indent_text(block.content, block.indent + "    "))
    else:
        if block.diff_lines:
            t.append(" ({} lines changed)".format(len(block.diff_lines)), style="dim")
        else:
            t.append("\n" + block.indent + "    ...", style="dim")

    return _add_filter_indicator(t, "expand")


def _render_role(block: RoleBlock, filters: dict) -> Text | None:
    """Render role label (USER, ASSISTANT, SYSTEM)."""
    role_lower = block.role.lower()
    if role_lower == "system" and not filters.get("system", False):
        return None
    if role_lower == "tool_result" and not filters.get("tools", False):
        return None
    style = ROLE_STYLES.get(role_lower, "bold magenta")
    label = block.role.upper().replace("_", " ")
    t = Text(label, style=style)
    if block.timestamp:
        t.append(f"  {block.timestamp}", style="dim")
    return t


def _render_text_content(block: TextContentBlock, filters: dict) -> Text | None:
    """Render text content with proper indentation."""
    if not block.text:
        return None
    return _indent_text(block.text, block.indent)


def _render_text_content_collapsed(block: TextContentBlock, filters: dict, role_filter_key: str) -> Text | None:
    """Render text content with collapse behavior for role-based filters.

    When the role filter is off (collapsed), shows first 2 lines with arrow indicator.
    When on (expanded), shows full content with down arrow if >2 lines.
    Messages with <=2 lines are always shown in full without arrow.

    Args:
        block: TextContentBlock to render
        filters: Current filter state
        role_filter_key: Filter key ("user" or "assistant")
    """
    if not block.text:
        return None

    lines = block.text.splitlines()
    is_expanded = filters.get(role_filter_key, False)

    if len(lines) <= 2:
        # Short message: always show full, no arrow
        return _indent_text(block.text, block.indent)

    if is_expanded:
        # Expanded: full content with down arrow
        t = Text()
        t.append("\u25bc ", style="dim")  # down arrow
        t.append(_indent_text(block.text, block.indent))
        return _add_filter_indicator(t, role_filter_key)
    else:
        # Collapsed: first 2 lines with right arrow
        truncated = "\n".join(lines[:2])
        t = Text()
        t.append("\u25b6 ", style="dim")  # right arrow
        t.append(_indent_text(truncated, block.indent))
        remaining = len(lines) - 2
        t.append(f"\n{block.indent}  ... ({remaining} more lines)", style="dim")
        return _add_filter_indicator(t, role_filter_key)


def _render_tool_use(block: ToolUseBlock, filters: dict) -> Text | None:
    """Render tool use block. Only shown when tools filter is on."""
    if not filters.get("tools", False):
        return None  # Summary handled by render_blocks
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    t = Text("  ")
    t.append("[Use: {}]".format(block.name), style="bold {}".format(color))
    if block.detail:
        t.append(" {}".format(block.detail), style="dim")
    t.append(" ({} bytes)".format(block.input_size))
    return _add_filter_indicator(t, "tools")


def _render_tool_result(block: ToolResultBlock, filters: dict) -> Text | None:
    """Render tool result block. Hidden when tools filter is off."""
    if not filters.get("tools", False):
        return None
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    if block.is_error:
        label = "[Result: {} ERROR]".format(block.tool_name) if block.tool_name else "[Result: ERROR]"
    else:
        label = "[Result: {}]".format(block.tool_name) if block.tool_name else "[Result]"
    t = Text("  ")
    t.append(label, style="bold {}".format(color))
    if block.detail:
        t.append(" {}".format(block.detail), style="dim")
    t.append(" ({} bytes)".format(block.size))
    return _add_filter_indicator(t, "tools")


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
    return Text("\n  [Proxy Error: {}]".format(block.message), style=f"bold {cc_dump.palette.PALETTE.error}")


def _render_log(block: LogBlock, filters: dict) -> Text | None:
    """Render log block."""
    style_map = {
        "ERROR": f"bold {cc_dump.palette.PALETTE.error}",
        "WARNING": f"bold {cc_dump.palette.PALETTE.warning}",
        "INFO": f"bold {cc_dump.palette.PALETTE.info}",
    }
    style = style_map.get(block.level, "")
    t = Text()
    t.append("[{}] ".format(block.level), style=style)
    t.append(block.message)
    return t


def _render_newline(block: NewlineBlock, filters: dict) -> Text | None:
    """Render a newline block."""
    return Text("")


def _render_turn_budget(block: TurnBudgetBlock, filters: dict, expanded: bool | None = None) -> Text | None:
    """Render turn budget block with expand/collapse based on filter or override."""
    if not filters.get("metadata", False):
        return None

    # Determine expand state
    is_expanded = expanded if expanded is not None else filters.get("expand", False)

    t = Text()
    arrow = "\u25bc" if is_expanded else "\u25b6"
    t.append(f"{arrow} ", style="dim")

    # Summary line
    p = cc_dump.palette.PALETTE
    t.append("Input: ", style="dim")
    t.append(f"{block.input_tokens:,}", style=f"bold {p.info}")
    t.append(" | Output: ", style="dim")
    t.append(f"{block.output_tokens:,}", style=f"bold {p.success}")

    # Expanded breakdown
    if is_expanded and block.breakdown:
        t.append("\n")
        for key, value in block.breakdown.items():
            t.append(f"  {key}: ", style="dim")
            t.append(f"{value:,}\n", style="bold")

    return _add_filter_indicator(t, "metadata")


# Mapping from block type name to renderer function
_BLOCK_REGISTRY: dict[str, BlockRenderer] = {
    "SeparatorBlock": _render_separator,
    "HeaderBlock": _render_header,
    "HttpHeadersBlock": _render_http_headers,
    "MetadataBlock": _render_metadata,
    "SystemLabelBlock": _render_system_label,
    "TrackedContentBlock": _render_tracked_content,
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
    "TurnBudgetBlock": _render_turn_budget,
}


def render_block(block: FormattedBlock, filters: dict, expanded: bool | None = None) -> Text | None:
    """Render a single block to Rich Text, applying filters.

    Args:
        block: FormattedBlock to render
        filters: Current filter state
        expanded: Optional per-block override for expand state (for expandable blocks)
    """
    block_type = type(block).__name__
    renderer = _BLOCK_REGISTRY.get(block_type)
    if renderer is None:
        return Text(f"[Unknown block type: {block_type}]", style="dim")

    # Pass expanded override for expandable blocks
    if block_type in _EXPANDABLE_BLOCK_TYPES:
        return renderer(block, filters, expanded)
    else:
        return renderer(block, filters)


def render_blocks(
    blocks: list[FormattedBlock],
    filters: dict,
    expanded_overrides: dict[int, bool] | None = None,
) -> list[tuple[int, Text]]:
    """Render a list of FormattedBlock to indexed Rich Text objects, applying filters.

    When the tools filter is off, consecutive ToolUseBlocks are collapsed
    into a single summary line like '[used 3 tools: Bash 2x, Read 1x]'.

    Args:
        expanded_overrides: Optional dict mapping block_index → expand state.
            Overrides filters["expand"] for individual collapsible blocks.

    Returns:
        List of (block_index, Text) pairs. The block_index is the position
        in the original blocks list. Summary lines use the index of the
        first ToolUseBlock in the collapsed run.
    """
    rendered: list[tuple[int, Text]] = []
    tools_on = filters.get("tools", False)
    pending_tool_uses: list[tuple[int, ToolUseBlock]] = []
    current_role = None  # Track role for message collapse

    def flush_tool_uses():
        if pending_tool_uses:
            first_idx = pending_tool_uses[0][0]
            tool_blocks = [b for _, b in pending_tool_uses]
            rendered.append((first_idx, _make_tool_use_summary(tool_blocks)))
            pending_tool_uses.clear()

    for i, block in enumerate(blocks):
        block_name = type(block).__name__

        # Track current role from RoleBlock
        if block_name == "RoleBlock":
            current_role = block.role.lower()

        is_tool_use = block_name == "ToolUseBlock"
        if is_tool_use and not tools_on:
            pending_tool_uses.append((i, block))
            continue
        # Non-tool-use block: flush any pending summary first
        flush_tool_uses()

        # Role-based collapse for TextContentBlock
        if block_name == "TextContentBlock" and current_role in ("user", "assistant"):
            role_filter_key = current_role  # "user" or "assistant"
            r = _render_text_content_collapsed(block, filters, role_filter_key)
            if r is not None:
                rendered.append((i, r))
            continue

        # Look up per-block expand override
        block_expanded = expanded_overrides.get(i) if expanded_overrides else None
        r = render_block(block, filters, expanded=block_expanded)
        if r is not None:
            rendered.append((i, r))

    flush_tool_uses()
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
    expanded_overrides: dict[int, bool] | None = None,
    block_cache=None,
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
        expanded_overrides: Per-block expand state overrides (block_index → bool)
        block_cache: Optional LRUCache for caching rendered strips per block

    Returns:
        (strips, block_strip_map) — pre-rendered lines and a dict mapping
        block index (in the blocks list) to its first strip line index.
    """
    from rich.segment import Segment
    from textual.strip import Strip

    strips = []
    block_strip_map = {}  # block_index → first strip line

    rendered_blocks = render_blocks(blocks, filters, expanded_overrides)

    for block_idx, text in rendered_blocks:
        block_strip_map[block_idx] = len(strips)

        # Check cache
        cache_key = None
        if block_cache is not None:
            # Use block index and filter state as cache key
            filter_snapshot = tuple(sorted(filters.items()))
            expand_state = expanded_overrides.get(block_idx) if expanded_overrides else None
            cache_key = (block_idx, filter_snapshot, expand_state)
            cached_strips = block_cache.get(cache_key)
            if cached_strips is not None:
                strips.extend(cached_strips)
                continue

        # Render to segments
        if wrap:
            segments = console.render(text, console.options.update_width(width))
        else:
            segments = list(text.render(console))

        # Split into lines
        lines = []
        current_line = []
        for segment in segments:
            if segment.text:
                for char in segment.text:
                    if char == "\n":
                        lines.append(current_line)
                        current_line = []
                    else:
                        current_line.append(Segment(char, segment.style))
            elif segment.control:
                current_line.append(segment)

        if current_line:
            lines.append(current_line)

        # Convert to strips
        block_strips = [Strip(line) for line in lines]
        strips.extend(block_strips)

        # Cache result
        if block_cache is not None and cache_key is not None:
            block_cache[cache_key] = block_strips

    return strips, block_strip_map


def _make_tool_use_summary(tool_blocks: list[ToolUseBlock]) -> Text:
    """Create a summary line for collapsed tool uses."""
    from collections import Counter
    counts = Counter(b.name for b in tool_blocks)
    parts = [f"{name} {count}x" if count > 1 else name for name, count in counts.items()]
    label = f"[used {len(tool_blocks)} tools: {', '.join(parts)}]"
    return Text("  " + label, style="dim")


# Filter key registry: maps block type name → filter key
_FILTER_KEY_MAP: dict[str, str] = {
    "HeaderBlock": "headers",
    "HttpHeadersBlock": "headers",
    "SeparatorBlock": "headers",
    "ToolUseBlock": "tools",
    "ToolResultBlock": "tools",
    "StreamToolUseBlock": "tools",
    "SystemLabelBlock": "system",
    "StreamInfoBlock": "metadata",
    "MetadataBlock": "metadata",
    "StopReasonBlock": "metadata",
    "TurnBudgetBlock": "metadata",
    "TrackedContentBlock": "expand",
}


def get_block_filter_key(block_type_name: str) -> str | None:
    """Get the filter key that controls visibility of a block type.

    Args:
        block_type_name: Name of the block type (e.g., "HeaderBlock")

    Returns:
        Filter key string (e.g., "headers") or None if always visible.
    """
    return _FILTER_KEY_MAP.get(block_type_name)
