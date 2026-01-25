"""ANSI terminal renderer for FormattedBlock structures.

Consumes the structured IR from formatting.py and produces ANSI-colored strings.
"""

from cc_dump.colors import (
    BOLD, CYAN, DIM, GREEN, MAGENTA, RED, RESET, SEPARATOR, TAG_COLORS,
    THIN_SEP, WHITE, YELLOW, BLUE,
)
from cc_dump.formatting import (
    FormattedBlock, SeparatorBlock, HeaderBlock, MetadataBlock,
    SystemLabelBlock, TrackedContentBlock, RoleBlock, TextContentBlock,
    ToolUseBlock, ToolResultBlock, ImageBlock, UnknownTypeBlock,
    StreamInfoBlock, StreamToolUseBlock, TextDeltaBlock, StopReasonBlock,
    ErrorBlock, ProxyErrorBlock, LogBlock, NewlineBlock, make_diff_lines,
)

# 6-color cycle for message indices
MSG_COLORS = [CYAN, GREEN, YELLOW, MAGENTA, BLUE, RED]


def render_block(block: FormattedBlock) -> str:
    """Render a single FormattedBlock to an ANSI string."""

    if isinstance(block, SeparatorBlock):
        return SEPARATOR if block.style == "heavy" else THIN_SEP

    if isinstance(block, HeaderBlock):
        if block.header_type == "request":
            return (BOLD + CYAN + " {} ".format(block.label) + RESET +
                    DIM + " ({})".format(block.timestamp) + RESET)
        else:
            return BOLD + GREEN + " RESPONSE " + RESET + DIM + " ({})".format(block.timestamp) + RESET

    if isinstance(block, MetadataBlock):
        parts = []
        parts.append("  model: " + BOLD + block.model + RESET)
        parts.append("max_tokens: " + str(block.max_tokens))
        parts.append("stream: " + str(block.stream))
        if block.tool_count:
            parts.append("tools: {}".format(block.tool_count))
        return DIM + " | ".join(parts) + RESET

    if isinstance(block, SystemLabelBlock):
        return BOLD + YELLOW + "SYSTEM:" + RESET

    if isinstance(block, TrackedContentBlock):
        return _render_tracked_content(block)

    if isinstance(block, RoleBlock):
        return _role_str(block.role)

    if isinstance(block, TextContentBlock):
        if not block.text:
            return ""
        return _indent_text(block.text, block.indent)

    if isinstance(block, ToolUseBlock):
        color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
        return "  " + color + BOLD + "[tool_use]" + RESET + " {} ({} bytes)".format(
            block.name, block.input_size
        )

    if isinstance(block, ToolResultBlock):
        color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
        label = "[tool_result:error]" if block.is_error else "[tool_result]"
        return "  " + color + BOLD + label + RESET + " ({} bytes)".format(block.size)

    if isinstance(block, ImageBlock):
        return "  " + DIM + "[image: {}]".format(block.media_type) + RESET

    if isinstance(block, UnknownTypeBlock):
        return "  " + DIM + "[{}]".format(block.block_type) + RESET

    if isinstance(block, StreamInfoBlock):
        return "  " + DIM + "model: " + BOLD + block.model + RESET

    if isinstance(block, StreamToolUseBlock):
        return "\n  " + CYAN + BOLD + "[tool_use]" + RESET + " " + block.name

    if isinstance(block, TextDeltaBlock):
        return block.text

    if isinstance(block, StopReasonBlock):
        return "\n  " + DIM + "stop: " + block.reason + RESET

    if isinstance(block, ErrorBlock):
        return RED + "\n  [HTTP {} {}]".format(block.code, block.reason) + RESET

    if isinstance(block, ProxyErrorBlock):
        return RED + "\n  [PROXY ERROR: {}]".format(block.error) + RESET

    if isinstance(block, LogBlock):
        return DIM + "  {} {} {}".format(block.command, block.path, block.status) + RESET

    if isinstance(block, NewlineBlock):
        return ""

    # Fallback
    return ""


def render_blocks(blocks: list[FormattedBlock]) -> str:
    """Render a list of FormattedBlock to a single ANSI string, joining with newlines."""
    lines = []
    for block in blocks:
        rendered = render_block(block)
        # TextDeltaBlock renders inline (no trailing newline)
        if isinstance(block, TextDeltaBlock):
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += rendered
            else:
                lines.append(rendered)
        else:
            lines.append(rendered)
    return "\n".join(lines)


def _role_str(role: str) -> str:
    """Render a role label with appropriate color."""
    icons = {
        "user": CYAN + BOLD + "USER" + RESET,
        "assistant": GREEN + BOLD + "ASSISTANT" + RESET,
        "system": YELLOW + BOLD + "SYSTEM" + RESET,
    }
    return icons.get(role, MAGENTA + BOLD + role.upper() + RESET)


def _format_tag(tag_id: str, color_idx: int) -> str:
    """Render a content tag with appropriate color from TAG_COLORS palette."""
    fg, bg = TAG_COLORS[color_idx % len(TAG_COLORS)]
    return bg + fg + BOLD + " {} ".format(tag_id) + RESET


def _render_tracked_content(block: TrackedContentBlock) -> str:
    """Render a TrackedContentBlock (new/ref/changed content)."""
    tag = _format_tag(block.tag_id, block.color_idx)

    if block.status == "new":
        content_len = len(block.content)
        header = "{}  {} NEW ({} chars):".format(block.indent, tag, content_len)
        indented_content = _indent_text(block.content, block.indent + "    ")
        return header + "\n" + indented_content

    elif block.status == "ref":
        return "{}  {} (unchanged)".format(block.indent, tag)

    elif block.status == "changed":
        old_len = len(block.old_content)
        new_len = len(block.new_content)
        header = "{}  {} CHANGED ({} -> {} chars):".format(
            block.indent, tag, old_len, new_len
        )
        diff_lines = make_diff_lines(block.old_content, block.new_content)
        diff_str = _render_diff(diff_lines, block.indent + "    ")
        return header + "\n" + diff_str

    return ""


def _render_diff(diff_lines: list, indent: str) -> str:
    """Render diff lines with color-coded additions/deletions."""
    output = []
    for kind, text in diff_lines:
        if kind == "hunk":
            output.append(indent + DIM + text + RESET)
        elif kind == "add":
            output.append(indent + GREEN + "+ " + text + RESET)
        elif kind == "del":
            output.append(indent + RED + "- " + text + RESET)
    return "\n".join(output)


def _indent_text(text: str, indent: str) -> str:
    """Indent each line of text with the given prefix."""
    lines = text.splitlines()
    return "\n".join(indent + line for line in lines)
