"""Request and response formatting — structured intermediate representation.

Returns FormattedBlock dataclasses that can be rendered by different backends
(e.g., tui/rendering.py for Rich renderables in TUI mode).
"""

import difflib
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime

from cc_dump.analysis import TurnBudget, compute_turn_budget, tool_result_breakdown
from cc_dump.colors import TAG_COLORS


# ─── Structured IR ────────────────────────────────────────────────────────────


@dataclass
class FormattedBlock:
    """Base class for all formatted output blocks.

    The collapsed field carries UI state (expand/collapse) directly on the block.
    This is intentional: the renderer reads block.collapsed directly, eliminating
    parameter threading through the render pipeline. The block is mutable, owned
    by TurnData, which is owned by ConversationView — no ownership inversion.
    """

    # UI state: whether this block is collapsed (showing summary vs full content).
    # Only meaningful for expandable block types (TrackedContentBlock, TurnBudgetBlock).
    # Default True = collapsed (show summary). Mutated by click handler.
    collapsed: bool = True


@dataclass
class SeparatorBlock(FormattedBlock):
    """A visual separator line."""

    style: str = "heavy"  # "heavy" or "thin" [MODIFIED]


@dataclass
class HeaderBlock(FormattedBlock):
    """Section header (e.g., REQUEST #1, RESPONSE)."""

    label: str = ""
    request_num: int = 0
    timestamp: str = ""
    header_type: str = "request"  # "request" or "response"


@dataclass
class HttpHeadersBlock(FormattedBlock):
    """HTTP request or response headers."""

    headers: dict = field(default_factory=dict)
    header_type: str = "request"  # "request" or "response"
    status_code: int = 0  # only for response headers


@dataclass
class MetadataBlock(FormattedBlock):
    """Key-value metadata (model, max_tokens, etc.)."""

    model: str = ""
    max_tokens: str = ""
    stream: bool = False
    tool_count: int = 0


@dataclass
class SystemLabelBlock(FormattedBlock):
    """The 'SYSTEM:' label."""

    pass


@dataclass
class TrackedContentBlock(FormattedBlock):
    """Result of content tracking (new/ref/changed)."""

    status: str = ""  # "new", "ref", "changed"
    tag_id: str = ""
    color_idx: int = 0
    content: str = ""
    old_content: str = ""
    new_content: str = ""
    indent: str = "    "


@dataclass
class RoleBlock(FormattedBlock):
    """A message role header (USER, ASSISTANT, SYSTEM)."""

    role: str = ""
    msg_index: int = 0
    timestamp: str = ""


@dataclass
class TextContentBlock(FormattedBlock):
    """Plain text content."""

    text: str = ""
    indent: str = "    "


@dataclass
class ToolUseBlock(FormattedBlock):
    """A tool_use content block."""

    name: str = ""
    input_size: int = 0
    msg_color_idx: int = 0
    detail: str = (
        ""  # Tool-specific enrichment (file path, skill name, command preview)
    )
    tool_use_id: str = ""  # Tool use ID for correlation


@dataclass
class ToolResultBlock(FormattedBlock):
    """A tool_result content block."""

    size: int = 0
    is_error: bool = False
    msg_color_idx: int = 0
    tool_use_id: str = ""  # Tool use ID for correlation
    tool_name: str = ""  # Tool name for summary display
    detail: str = ""  # Tool-specific detail (copied from corresponding ToolUseBlock)


@dataclass
class ToolUseSummaryBlock(FormattedBlock):
    """Summary of a collapsed run of tool_use blocks (when tools filter is off)."""

    tool_counts: dict = field(default_factory=dict)  # {tool_name: count}
    total: int = 0
    first_block_index: int = 0  # index in original block list


@dataclass
class ImageBlock(FormattedBlock):
    """An image content block."""

    media_type: str = ""


@dataclass
class UnknownTypeBlock(FormattedBlock):
    """An unknown content block type."""

    block_type: str = ""


@dataclass
class StreamInfoBlock(FormattedBlock):
    """Stream start info (model name)."""

    model: str = ""


@dataclass
class StreamToolUseBlock(FormattedBlock):
    """Tool use start in streaming response."""

    name: str = ""


@dataclass
class TextDeltaBlock(FormattedBlock):
    """A text delta from streaming response."""

    text: str = ""


@dataclass
class StopReasonBlock(FormattedBlock):
    """Stop reason from message_delta."""

    reason: str = ""


@dataclass
class ErrorBlock(FormattedBlock):
    """HTTP error."""

    code: int = 0
    reason: str = ""


@dataclass
class ProxyErrorBlock(FormattedBlock):
    """Proxy error."""

    error: str = ""


@dataclass
class TurnBudgetBlock(FormattedBlock):
    """Per-turn context budget breakdown."""

    budget: TurnBudget = field(default_factory=TurnBudget)
    tool_result_by_name: dict = field(default_factory=dict)  # {name: tokens_est}


@dataclass
class NewlineBlock(FormattedBlock):
    """An explicit newline/blank."""

    pass


# ─── Content tracking (stateful) ─────────────────────────────────────────────


def track_content(content, position_key, state):
    """
    Track a content block using the state dict. Returns one of:
    - ("new", id, color_idx, content)
    - ("ref", id, color_idx)
    - ("changed", id, color_idx, old_content, new_content)

    State keys used:
      positions: pos_key → {hash, content, id, color_idx}
      known_hashes: hash → id
      next_id: int
      next_color: int
    """
    h = hashlib.sha256(content.encode()).hexdigest()[:8]
    positions = state["positions"]
    known_hashes = state["known_hashes"]

    # Exact content seen before (by hash)
    if h in known_hashes:
        color_idx = None
        for pos in positions.values():
            if pos["hash"] == h:
                color_idx = pos["color_idx"]
                break
        if color_idx is None:
            color_idx = state["next_color"] % len(TAG_COLORS)
            state["next_color"] += 1
        tag_id = known_hashes[h]
        positions[position_key] = {
            "hash": h,
            "content": content,
            "id": tag_id,
            "color_idx": color_idx,
        }
        return ("ref", tag_id, color_idx)

    # Check if this position had different content before
    old_pos = positions.get(position_key)
    if old_pos and old_pos["hash"] != h:
        color_idx = old_pos["color_idx"]
        state["next_id"] += 1
        tag_id = "sp-{}".format(state["next_id"])
        old_content_val = old_pos["content"]
        known_hashes[h] = tag_id
        positions[position_key] = {
            "hash": h,
            "content": content,
            "id": tag_id,
            "color_idx": color_idx,
        }
        return ("changed", tag_id, color_idx, old_content_val, content)

    # Completely new
    color_idx = state["next_color"] % len(TAG_COLORS)
    state["next_color"] += 1
    state["next_id"] += 1
    tag_id = "sp-{}".format(state["next_id"])
    known_hashes[h] = tag_id
    positions[position_key] = {
        "hash": h,
        "content": content,
        "id": tag_id,
        "color_idx": color_idx,
    }
    return ("new", tag_id, color_idx, content)


def _make_tracked_block(result, indent="    "):
    """Convert a tracking result tuple into a TrackedContentBlock."""
    if result[0] == "new":
        _, tag_id, color_idx, content = result
        return TrackedContentBlock(
            status="new",
            tag_id=tag_id,
            color_idx=color_idx,
            content=content,
            indent=indent,
        )
    elif result[0] == "ref":
        _, tag_id, color_idx = result
        return TrackedContentBlock(
            status="ref",
            tag_id=tag_id,
            color_idx=color_idx,
            indent=indent,
        )
    elif result[0] == "changed":
        _, tag_id, color_idx, old_content, new_content = result
        return TrackedContentBlock(
            status="changed",
            tag_id=tag_id,
            color_idx=color_idx,
            old_content=old_content,
            new_content=new_content,
            indent=indent,
        )
    return TextContentBlock(text="", indent=indent)


def make_diff_lines(old_text, new_text):
    """Compute diff lines as (kind, text) tuples.

    kind is one of: "hunk", "add", "del"
    """
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, lineterm="", n=2)
    lines = []
    for line in diff:
        if line.startswith("+++") or line.startswith("---"):
            continue
        elif line.startswith("@@"):
            lines.append(("hunk", line.strip()))
        elif line.startswith("+"):
            lines.append(("add", line[1:].rstrip()))
        elif line.startswith("-"):
            lines.append(("del", line[1:].rstrip()))
    return lines


# ─── Formatting to structured blocks ─────────────────────────────────────────


def _get_timestamp():
    return datetime.now().strftime("%-I:%M:%S %p")


def _front_ellipse_path(path: str, max_len: int = 40) -> str:
    """Front-ellipse a file path: /a/b/c/d/file.ts -> ...c/d/file.ts"""
    if len(path) <= max_len:
        return path
    parts = path.split("/")
    # Build from the end until we exceed max_len
    result = ""
    for i in range(len(parts) - 1, -1, -1):
        candidate = "/".join(parts[i:])
        if len(candidate) + 3 > max_len:  # 3 for "..."
            break
        result = candidate
    if not result:
        # Even the filename alone is too long
        result = parts[-1]
        if len(result) > max_len - 3:
            result = result[-(max_len - 3) :]
    return "..." + result


def _tool_detail(name: str, tool_input: dict) -> str:
    """Extract tool-specific detail string for display enrichment."""
    if (
        name == "Read"
        or name == "mcp__plugin_repomix-mcp_repomix__file_system_read_file"
    ):
        file_path = tool_input.get("file_path", "")
        if not file_path:
            return ""
        return _front_ellipse_path(file_path, max_len=40)
    if name == "Skill":
        return tool_input.get("skill", "")
    if name == "Bash":
        command = tool_input.get("command", "")
        if not command:
            return ""
        first_line = command.split("\n", 1)[0]
        if len(first_line) > 60:
            return first_line[:57] + "..."
        return first_line
    return ""


MSG_COLOR_CYCLE = 6  # matches the 6-color cycle in the ANSI renderer


def format_request(body, state):
    """Format a full API request as a list of FormattedBlock."""
    state["request_counter"] += 1
    request_num = state["request_counter"]

    blocks = []
    blocks.append(NewlineBlock())
    blocks.append(SeparatorBlock(style="heavy"))
    blocks.append(
        HeaderBlock(
            label="REQUEST #{}".format(request_num),
            request_num=request_num,
            timestamp=_get_timestamp(),
            header_type="request",
        )
    )
    blocks.append(SeparatorBlock(style="heavy"))

    model = body.get("model", "?")
    max_tokens = body.get("max_tokens", "?")
    stream = body.get("stream", False)
    tools = body.get("tools", [])

    blocks.append(
        MetadataBlock(
            model=str(model),
            max_tokens=str(max_tokens),
            stream=stream,
            tool_count=len(tools),
        )
    )

    # Context budget breakdown
    budget = compute_turn_budget(body)
    messages = body.get("messages", [])
    breakdown = tool_result_breakdown(messages)
    blocks.append(TurnBudgetBlock(budget=budget, tool_result_by_name=breakdown))

    blocks.append(SeparatorBlock(style="thin"))

    # System prompt(s)
    system = body.get("system", "")
    if system:
        blocks.append(SystemLabelBlock())
        if isinstance(system, str):
            result = track_content(system, "system:0", state)
            blocks.append(_make_tracked_block(result))
        elif isinstance(system, list):
            for i, block in enumerate(system):
                text = block.get("text", "") if isinstance(block, dict) else str(block)
                pos_key = "system:{}".format(i)
                result = track_content(text, pos_key, state)
                blocks.append(_make_tracked_block(result))
        blocks.append(SeparatorBlock(style="thin"))

    # Tool correlation state (per-request, not persistent)
    tool_id_map: dict[
        str, tuple[str, int, str]
    ] = {}  # tool_use_id -> (name, color_idx, detail)
    tool_color_counter = 0

    # Messages
    messages = body.get("messages", [])
    for i, msg in enumerate(messages):
        role = msg.get("role", "?")
        content = msg.get("content", "")
        msg_color_idx = i % MSG_COLOR_CYCLE

        # Blank line between messages (skip before the first one)
        if i > 0:
            blocks.append(NewlineBlock())

        blocks.append(RoleBlock(role=role, msg_index=i, timestamp=_get_timestamp()))

        if isinstance(content, str):
            if content:
                blocks.append(TextContentBlock(text=content, indent="    "))
        elif isinstance(content, list):
            for cblock in content:
                if isinstance(cblock, str):
                    blocks.append(TextContentBlock(text=cblock[:200], indent="    "))
                    continue
                btype = cblock.get("type", "?")
                if btype == "text":
                    text = cblock.get("text", "")
                    if len(text) > 500 and i == 0:
                        result = track_content(
                            text, "msg0:text:{}".format(content.index(cblock)), state
                        )
                        blocks.append(_make_tracked_block(result, indent="    "))
                    else:
                        blocks.append(TextContentBlock(text=text, indent="    "))
                elif btype == "tool_use":
                    name = cblock.get("name", "?")
                    tool_input = cblock.get("input", {})
                    input_size = len(json.dumps(tool_input))
                    tool_use_id = cblock.get("id", "")
                    detail = _tool_detail(name, tool_input)
                    # Assign correlation color
                    tool_color_idx = tool_color_counter % MSG_COLOR_CYCLE
                    tool_color_counter += 1
                    if tool_use_id:
                        tool_id_map[tool_use_id] = (name, tool_color_idx, detail)
                    blocks.append(
                        ToolUseBlock(
                            name=name,
                            input_size=input_size,
                            msg_color_idx=tool_color_idx,
                            detail=detail,
                            tool_use_id=tool_use_id,
                        )
                    )
                elif btype == "tool_result":
                    content_val = cblock.get("content", "")
                    if isinstance(content_val, list):
                        size = sum(len(json.dumps(p)) for p in content_val)
                    elif isinstance(content_val, str):
                        size = len(content_val)
                    else:
                        size = len(json.dumps(content_val))
                    is_error = cblock.get("is_error", False)
                    tool_use_id = cblock.get("tool_use_id", "")
                    # Look up correlated name, color, and detail
                    tool_name = ""
                    tool_color_idx = msg_color_idx  # fallback to message color
                    detail = ""
                    if tool_use_id and tool_use_id in tool_id_map:
                        tool_name, tool_color_idx, detail = tool_id_map[tool_use_id]
                    blocks.append(
                        ToolResultBlock(
                            size=size,
                            is_error=is_error,
                            msg_color_idx=tool_color_idx,
                            tool_use_id=tool_use_id,
                            tool_name=tool_name,
                            detail=detail,
                        )
                    )
                elif btype == "image":
                    source = cblock.get("source", {})
                    blocks.append(ImageBlock(media_type=source.get("media_type", "?")))
                else:
                    blocks.append(UnknownTypeBlock(block_type=btype))

    blocks.append(NewlineBlock())
    return blocks


def format_response_event(event_type, data):
    """Format a streaming response event as a list of FormattedBlock."""
    if event_type == "message_start":
        msg = data.get("message", {})
        return [StreamInfoBlock(model=msg.get("model", "?"))]

    if event_type == "content_block_start":
        block = data.get("content_block", {})
        btype = block.get("type", "?")
        if btype == "tool_use":
            return [StreamToolUseBlock(name=block.get("name", "?"))]
        return []

    if event_type == "content_block_delta":
        delta = data.get("delta", {})
        if delta.get("type") == "text_delta":
            text = delta.get("text", "")
            if text:
                return [TextDeltaBlock(text=text)]
        return []

    if event_type == "message_delta":
        delta = data.get("delta", {})
        stop = delta.get("stop_reason", "")
        if stop:
            return [StopReasonBlock(reason=stop)]
        return []

    if event_type == "message_stop":
        return []

    return []


def format_complete_response(complete_message):
    """Format a complete (non-streaming) Claude message as FormattedBlocks.

    This is used for replay mode - takes a complete message and builds the blocks
    directly without going through streaming events.

    Args:
        complete_message: Complete Claude API message dict

    Returns:
        List of FormattedBlock objects
    """
    blocks = []

    # Model info
    model = complete_message.get("model", "?")
    blocks.append(StreamInfoBlock(model=model))

    # Content blocks
    content = complete_message.get("content", [])
    for block in content:
        block_type = block.get("type", "")

        if block_type == "text":
            text = block.get("text", "")
            if text:
                blocks.append(TextDeltaBlock(text=text))

        elif block_type == "tool_use":
            tool_name = block.get("name", "?")
            blocks.append(StreamToolUseBlock(name=tool_name))

    # Stop reason
    stop_reason = complete_message.get("stop_reason")
    if stop_reason:
        blocks.append(StopReasonBlock(reason=stop_reason))

    return blocks


def format_request_headers(headers_dict: dict) -> list:
    """Format HTTP request headers as blocks."""
    if not headers_dict:
        return []
    return [HttpHeadersBlock(headers=headers_dict, header_type="request")]


def format_response_headers(status_code: int, headers_dict: dict) -> list:
    """Format HTTP response headers as blocks."""
    if not headers_dict:
        return []
    return [
        HttpHeadersBlock(
            headers=headers_dict, header_type="response", status_code=status_code
        )
    ]
