"""Request and response formatting — structured intermediate representation.

Returns FormattedBlock dataclasses that can be rendered by different backends
(e.g., tui/rendering.py for Rich renderables in TUI mode).
"""

import difflib
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from typing import NamedTuple

from cc_dump.analysis import TurnBudget, compute_turn_budget, tool_result_breakdown
from cc_dump.colors import TAG_COLORS


# ─── Visibility model ─────────────────────────────────────────────────────────


class VisState(NamedTuple):
    """Visibility state for a block — three orthogonal boolean axes.

    // [LAW:one-source-of-truth] THE representation of visibility.
    // [LAW:dataflow-not-control-flow] Values, not control flow branching.
    """
    visible: bool  # False = hidden, True = shown
    full: bool     # False = summary level, True = full level
    expanded: bool # False = collapsed, True = expanded


# Visibility state constants
HIDDEN = VisState(visible=False, full=False, expanded=False)
ALWAYS_VISIBLE = VisState(visible=True, full=True, expanded=True)


class Category(Enum):
    """Block category — groups blocks for visibility control."""

    HEADERS = "headers"
    USER = "user"
    ASSISTANT = "assistant"
    TOOLS = "tools"
    SYSTEM = "system"
    METADATA = "metadata"
    BUDGET = "budget"


# ─── Structured IR ────────────────────────────────────────────────────────────


@dataclass
class FormattedBlock:
    """Base class for all formatted output blocks.

    Two visibility axes:
    - Level (per-category, keyboard cycle): EXISTENCE / SUMMARY / FULL
    - expanded (per-block, click toggle): collapsed / expanded within current level.
      None means use the level default.
    - category: overrides static BLOCK_CATEGORY for context-dependent blocks
      (e.g., TextContentBlock can be USER or ASSISTANT depending on the message).
    """

    # Per-block expand/collapse override. None = use level default.
    # [LAW:one-source-of-truth] Level default is in rendering.DEFAULT_EXPANDED;
    # this field only stores explicit per-block overrides.
    expanded: bool | None = None

    # Context-dependent category override. None = use static BLOCK_CATEGORY.
    category: Category | None = None


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
    content: str = ""  # Actual result text for full-level rendering


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


def track_content(content, position_key, state, indent="    "):
    """
    Track a content block using the state dict. Returns TrackedContentBlock.

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
        return TrackedContentBlock(
            status="ref",
            tag_id=tag_id,
            color_idx=color_idx,
            content="",
            old_content="",
            new_content="",
            indent=indent,
        )

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
        return TrackedContentBlock(
            status="changed",
            tag_id=tag_id,
            color_idx=color_idx,
            content="",
            old_content=old_content_val,
            new_content=content,
            indent=indent,
        )

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
    return TrackedContentBlock(
        status="new",
        tag_id=tag_id,
        color_idx=color_idx,
        content=content,
        old_content="",
        new_content="",
        indent=indent,
    )


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


# [LAW:dataflow-not-control-flow] Tool detail extraction dispatch table
_TOOL_DETAIL_EXTRACTORS = {
    "Read": lambda inp: _front_ellipse_path(inp.get("file_path", ""), max_len=40),
    "mcp__plugin_repomix-mcp_repomix__file_system_read_file": lambda inp: (
        _front_ellipse_path(inp.get("file_path", ""), max_len=40)
    ),
    "Skill": lambda inp: inp.get("skill", ""),
    "Bash": lambda inp: (
        (lambda cmd: cmd[:57] + "..." if len(cmd) > 60 else cmd)(
            inp.get("command", "").split("\n", 1)[0]
        )
        if inp.get("command")
        else ""
    ),
}


def _tool_detail(name: str, tool_input: dict) -> str:
    """Extract tool-specific detail string for display enrichment."""
    extractor = _TOOL_DETAIL_EXTRACTORS.get(name, lambda _: "")
    return extractor(tool_input)


MSG_COLOR_CYCLE = 6  # matches the 6-color cycle in the ANSI renderer


# [LAW:dataflow-not-control-flow] Content block formatting dispatch
@dataclass
class _ContentContext:
    """Shared context for content block formatters."""

    role_cat: Category | None
    state: dict
    tool_id_map: dict
    tool_color_counter: int
    msg_index: int
    indent: str = "    "


def _format_text_content(cblock, ctx: _ContentContext) -> list:
    """Format a text content block."""
    text = cblock.get("text", "")
    if len(text) > 500 and ctx.msg_index == 0:
        return [
            track_content(
                text,
                "msg0:text:{}".format(ctx.msg_index),
                ctx.state,
                indent=ctx.indent,
            )
        ]
    else:
        return [TextContentBlock(text=text, indent=ctx.indent, category=ctx.role_cat)]


def _format_tool_use_content(cblock, ctx: _ContentContext) -> list:
    """Format a tool_use content block."""
    name = cblock.get("name", "?")
    tool_input = cblock.get("input", {})
    input_size = len(json.dumps(tool_input))
    tool_use_id = cblock.get("id", "")
    detail = _tool_detail(name, tool_input)
    # Assign correlation color
    tool_color_idx = ctx.tool_color_counter % MSG_COLOR_CYCLE
    ctx.tool_color_counter += 1
    if tool_use_id:
        ctx.tool_id_map[tool_use_id] = (name, tool_color_idx, detail)
    return [
        ToolUseBlock(
            name=name,
            input_size=input_size,
            msg_color_idx=tool_color_idx,
            detail=detail,
            tool_use_id=tool_use_id,
        )
    ]


def _format_tool_result_content(cblock, ctx: _ContentContext) -> list:
    """Format a tool_result content block."""
    content_val = cblock.get("content", "")
    # [LAW:dataflow-not-control-flow] Extract content text unconditionally
    if isinstance(content_val, list):
        size = sum(len(json.dumps(p)) for p in content_val)
        # Extract text parts from list
        content_text = "".join(
            p.get("text", "") for p in content_val if p.get("type") == "text"
        )
    elif isinstance(content_val, str):
        size = len(content_val)
        content_text = content_val
    else:
        size = len(json.dumps(content_val))
        content_text = json.dumps(content_val)
    is_error = cblock.get("is_error", False)
    tool_use_id = cblock.get("tool_use_id", "")
    # Look up correlated name, color, and detail
    msg_color_idx = ctx.msg_index % MSG_COLOR_CYCLE
    tool_name = ""
    tool_color_idx = msg_color_idx  # fallback to message color
    detail = ""
    if tool_use_id and tool_use_id in ctx.tool_id_map:
        tool_name, tool_color_idx, detail = ctx.tool_id_map[tool_use_id]
    return [
        ToolResultBlock(
            size=size,
            is_error=is_error,
            msg_color_idx=tool_color_idx,
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            detail=detail,
            content=content_text,
        )
    ]


def _format_image_content(cblock, ctx: _ContentContext) -> list:
    """Format an image content block."""
    source = cblock.get("source", {})
    return [ImageBlock(media_type=source.get("media_type", "?"), category=ctx.role_cat)]


def _format_unknown_content(cblock, ctx: _ContentContext) -> list:
    """Format an unknown content block type."""
    btype = cblock.get("type", "?")
    return [UnknownTypeBlock(block_type=btype)]


_CONTENT_BLOCK_FACTORIES = {
    "text": _format_text_content,
    "tool_use": _format_tool_use_content,
    "tool_result": _format_tool_result_content,
    "image": _format_image_content,
}


def format_request(body, state, request_headers: dict | None = None):
    """Format a full API request as a list of FormattedBlock.

    Args:
        body: Request body dict
        state: Content tracking state dict
        request_headers: Optional HTTP request headers to include after MetadataBlock

    Returns:
        List of FormattedBlock objects
    """
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

    # [LAW:one-source-of-truth] Header injection happens here, not in callers
    # format_request_headers({}) returns [], so extend is always safe
    blocks.extend(format_request_headers(request_headers or {}))

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
            blocks.append(track_content(system, "system:0", state))
        elif isinstance(system, list):
            for i, block in enumerate(system):
                text = block.get("text", "") if isinstance(block, dict) else str(block)
                pos_key = "system:{}".format(i)
                blocks.append(track_content(text, pos_key, state))
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

        # Blank line between messages (skip before the first one)
        if i > 0:
            blocks.append(NewlineBlock())

        # [LAW:one-source-of-truth] Category set here at creation, not resolved later
        role_cat = {
            "user": Category.USER,
            "assistant": Category.ASSISTANT,
            "system": Category.SYSTEM,
        }.get(role.lower())

        blocks.append(
            RoleBlock(
                role=role, msg_index=i, timestamp=_get_timestamp(), category=role_cat
            )
        )

        # Create shared context for content block formatters
        ctx = _ContentContext(
            role_cat=role_cat,
            state=state,
            tool_id_map=tool_id_map,
            tool_color_counter=tool_color_counter,
            msg_index=i,
            indent="    ",
        )

        if isinstance(content, str):
            if content:
                blocks.append(
                    TextContentBlock(text=content, indent="    ", category=role_cat)
                )
        elif isinstance(content, list):
            for cblock in content:
                if isinstance(cblock, str):
                    blocks.append(
                        TextContentBlock(
                            text=cblock[:200], indent="    ", category=role_cat
                        )
                    )
                    continue
                btype = cblock.get("type", "?")
                factory = _CONTENT_BLOCK_FACTORIES.get(btype, _format_unknown_content)
                blocks.extend(factory(cblock, ctx))

        # Extract updated tool_color_counter from context
        tool_color_counter = ctx.tool_color_counter

    blocks.append(NewlineBlock())
    return blocks


def _format_message_start(data):
    """Handle message_start event."""
    msg = data.get("message", {})
    return [StreamInfoBlock(model=msg.get("model", "?"))]


# [LAW:dataflow-not-control-flow] content_block_start dispatch
_CBLOCK_START_HANDLERS = {
    "tool_use": lambda block: [StreamToolUseBlock(name=block.get("name", "?"))],
}


def _format_cblock_start(data):
    """Handle content_block_start event."""
    block = data.get("content_block", {})
    btype = block.get("type", "?")
    handler = _CBLOCK_START_HANDLERS.get(btype, lambda _: [])
    return handler(block)


# [LAW:dataflow-not-control-flow] content_block_delta dispatch
_CBLOCK_DELTA_HANDLERS = {
    "text_delta": lambda delta: (
        [TextDeltaBlock(text=delta.get("text", ""), category=Category.ASSISTANT)]
        if delta.get("text", "")
        else []
    ),
}


def _format_cblock_delta(data):
    """Handle content_block_delta event."""
    delta = data.get("delta", {})
    dtype = delta.get("type", "?")
    handler = _CBLOCK_DELTA_HANDLERS.get(dtype, lambda _: [])
    return handler(delta)


def _format_message_delta(data):
    """Handle message_delta event."""
    delta = data.get("delta", {})
    stop = delta.get("stop_reason", "")
    if stop:
        return [StopReasonBlock(reason=stop)]
    return []


# [LAW:dataflow-not-control-flow] Dispatch table replaces if/elif chain
_RESPONSE_EVENT_FORMATTERS = {
    "message_start": _format_message_start,
    "content_block_start": _format_cblock_start,
    "content_block_delta": _format_cblock_delta,
    "message_delta": _format_message_delta,
    "message_stop": lambda _: [],
}


def format_response_event(event_type, data):
    """Format a streaming response event as a list of FormattedBlock."""
    formatter = _RESPONSE_EVENT_FORMATTERS.get(event_type, lambda _: [])
    return formatter(data)


# [LAW:dataflow-not-control-flow] Complete response content block factories
def _complete_text_block(block: dict) -> list:
    """Create blocks for text content."""
    text = block.get("text", "")
    if text:
        return [TextDeltaBlock(text=text, category=Category.ASSISTANT)]
    return []


def _complete_tool_use_block(block: dict) -> list:
    """Create blocks for tool_use content."""
    tool_name = block.get("name", "?")
    return [StreamToolUseBlock(name=tool_name)]


# [LAW:dataflow-not-control-flow] Complete response content block factories
_COMPLETE_RESPONSE_FACTORIES = {
    "text": _complete_text_block,
    "tool_use": _complete_tool_use_block,
}


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

    # [LAW:dataflow-not-control-flow] Content blocks via dispatch table
    content = complete_message.get("content", [])
    for block in content:
        block_type = block.get("type", "")
        factory = _COMPLETE_RESPONSE_FACTORIES.get(block_type, lambda _: [])
        blocks.extend(factory(block))

    # [LAW:dataflow-not-control-flow] Always create block, let renderer handle empty
    stop_reason = complete_message.get("stop_reason", "")
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
