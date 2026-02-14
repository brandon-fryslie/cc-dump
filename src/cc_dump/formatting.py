"""Request and response formatting — structured intermediate representation.

Returns FormattedBlock dataclasses that can be rendered by different backends
(e.g., tui/rendering.py for Rich renderables in TUI mode).
"""

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from collections.abc import Callable
from typing import Any, NamedTuple

from cc_dump.event_types import (
    InputJsonDeltaEvent,
    MessageDeltaEvent,
    MessageStartEvent,
    MessageStopEvent,
    SSEEvent,
    ContentBlockStopEvent,
    StopReason,
    TextBlockStartEvent,
    TextDeltaEvent,
    ToolUseBlockStartEvent,
)

from cc_dump.analysis import TurnBudget, compute_turn_budget, estimate_tokens, tool_result_breakdown
from cc_dump.colors import TAG_COLORS


# ─── API Metadata parsing ────────────────────────────────────────────────────


_USER_ID_PATTERN = re.compile(
    r"user_([a-f0-9]+)_account_([a-f0-9-]+)_session_([a-f0-9-]+)"
)


def parse_user_id(user_id: str) -> dict | None:
    """Parse compound user_id into user, account, session components.

    Format: user_<hash>_account_<uuid>_session_<uuid>

    Returns dict with user_hash, account_id, session_id or None if no match.
    """
    match = _USER_ID_PATTERN.match(user_id)
    if match:
        return {
            "user_hash": match.group(1),
            "account_id": match.group(2),
            "session_id": match.group(3),
        }
    return None


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

    USER = "user"
    ASSISTANT = "assistant"
    TOOLS = "tools"
    SYSTEM = "system"
    BUDGET = "budget"
    METADATA = "metadata"
    HEADERS = "headers"


# ─── Structured IR ────────────────────────────────────────────────────────────


@dataclass
class ContentRegion:
    """An independently expandable/collapsible region within a block.

    // [LAW:one-source-of-truth] Replaces _xml_expanded shadow dict, _xml_strip_ranges,
    // and _xml_expandable bool — all region state lives here.

    kind: structural discriminator — determines rendering behavior.
        Values: "xml_block", "md", "code_fence", "md_fence", "tool_def"
    tags: semantic labels for navigation/search (e.g., XML tag name, tool name).
        Empty list = not navigable.
    """

    index: int  # Position in parent's content_regions list
    kind: str = ""  # "xml_block", "md", "code_fence", "md_fence", "tool_def"
    tags: list[str] = field(default_factory=list)  # Semantic labels for navigation
    expanded: bool | None = None  # None = default (expanded). False = collapsed.
    _strip_range: tuple[int, int] | None = None  # Set by renderer: (start, end) in block strips


def populate_content_regions(block: "FormattedBlock") -> None:
    """Eagerly populate content_regions from text segmentation.

    Idempotent. Creates one ContentRegion per SubBlock segment
    (MD, CODE_FENCE, MD_FENCE, XML_BLOCK) — not just XML.

    // [LAW:single-enforcer] Single place that creates text-based ContentRegion instances.
    // [LAW:dataflow-not-control-flow] Pure data population, not control flow.

    FUTURE: content-derived tags — scan region text for identifiable content
    (e.g., "CLAUDE.md" in system-reminder text) and add to tags list.
    """
    from cc_dump.segmentation import segment, SubBlockKind

    # Already populated — idempotent (preserves ToolDefinitionsBlock's inline creation)
    if block.content_regions:
        return

    text = getattr(block, "content", "") or ""
    if not text:
        return

    seg = segment(text)
    if not seg.sub_blocks:
        return

    regions: list[ContentRegion] = []
    for i, sb in enumerate(seg.sub_blocks):
        kind = sb.kind.value  # "md", "code_fence", "md_fence", "xml_block"

        tags: list[str] = []
        if sb.kind == SubBlockKind.XML_BLOCK:
            tags = [sb.meta.tag_name]
        elif sb.kind == SubBlockKind.CODE_FENCE and sb.meta.info:
            tags = [sb.meta.info]
        # MD and MD_FENCE: no tags (not navigable)

        regions.append(ContentRegion(index=i, kind=kind, tags=tags))

    block.content_regions = regions


@dataclass
class FormattedBlock:
    """Base class for all formatted output blocks.

    Two visibility axes:
    - Level (per-category, keyboard cycle): EXISTENCE / SUMMARY / FULL
    - expanded (per-block, click toggle): collapsed / expanded within current level.
      None means use the level default.
    - category: overrides static BLOCK_CATEGORY for context-dependent blocks
      (e.g., TextContentBlock can be USER or ASSISTANT depending on the message).

    Sub-region axis:
    - content_regions: list[ContentRegion] — independently toggleable regions
      within the block (e.g., XML sub-blocks). Empty = no sub-regions.
    """

    # Per-block expand/collapse override. None = use level default.
    # [LAW:one-source-of-truth] Level default is in rendering.DEFAULT_EXPANDED;
    # this field only stores explicit per-block overrides.
    expanded: bool | None = None

    # Context-dependent category override. None = use static BLOCK_CATEGORY.
    category: Category | None = None

    # Whether this block should be rendered during streaming.
    # // [LAW:dataflow-not-control-flow] Block type declares streaming behavior,
    # // consumer code checks the value, not the type.
    show_during_streaming: bool = False

    # Per-region expand/collapse state. Empty = no sub-regions.
    # // [LAW:one-source-of-truth] All sub-region state lives here, not in shadow attrs.
    content_regions: list[ContentRegion] = field(default_factory=list)


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
    # API metadata from metadata.user_id field:
    user_hash: str = ""
    account_id: str = ""
    session_id: str = ""


@dataclass
class ToolDefinitionsBlock(FormattedBlock):
    """Tool definitions from the request body. Each tool is a collapsible sub-block."""

    tools: list = field(default_factory=list)  # [{name, description, input_schema}, ...]
    tool_tokens: list = field(default_factory=list)  # per-tool token estimates
    total_tokens: int = 0  # sum of all tool token estimates


@dataclass
class NewSessionBlock(FormattedBlock):
    """Indicates a new Claude Code session started."""

    session_id: str = ""


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

    content: str = ""
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
    tool_input: dict = field(default_factory=dict)  # Raw input for rendering
    description: str = ""  # From tool definitions, populated via state


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
    tool_input: dict = field(default_factory=dict)  # From correlated ToolUseBlock


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

    content: str = ""
    show_during_streaming = True


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
        # [LAW:one-source-of-truth] content is always the current text;
        # renderers decide whether to show it or diff metadata.
        return TrackedContentBlock(
            status="ref",
            tag_id=tag_id,
            color_idx=color_idx,
            content=content,
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
        # [LAW:one-source-of-truth] content is always the current text;
        # old_content/new_content carry diff data for SUMMARY renderer.
        return TrackedContentBlock(
            status="changed",
            tag_id=tag_id,
            color_idx=color_idx,
            content=content,
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
    "Write": lambda inp: _front_ellipse_path(inp.get("file_path", ""), max_len=40),
    "Edit": lambda inp: _front_ellipse_path(inp.get("file_path", ""), max_len=40),
    "Grep": lambda inp: inp.get("pattern", "")[:60],
    "Glob": lambda inp: inp.get("pattern", "")[:60],
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
        return [TextContentBlock(content=text, indent=ctx.indent, category=ctx.role_cat)]


def _format_tool_use_content(cblock, ctx: _ContentContext) -> list:
    """Format a tool_use content block."""
    name = cblock.get("name", "?")
    tool_input = cblock.get("input", {})
    input_size = sum(v.count('\n') + 1 for v in tool_input.values() if isinstance(v, str)) or 1
    tool_use_id = cblock.get("id", "")
    detail = _tool_detail(name, tool_input)
    description = ctx.state.get("tool_descriptions", {}).get(name, "")
    # Assign correlation color
    tool_color_idx = ctx.tool_color_counter % MSG_COLOR_CYCLE
    ctx.tool_color_counter += 1
    if tool_use_id:
        ctx.tool_id_map[tool_use_id] = (name, tool_color_idx, detail, tool_input)
    return [
        ToolUseBlock(
            name=name,
            input_size=input_size,
            msg_color_idx=tool_color_idx,
            detail=detail,
            tool_use_id=tool_use_id,
            tool_input=tool_input,
            description=description,
        )
    ]


def _format_tool_result_content(cblock, ctx: _ContentContext) -> list:
    """Format a tool_result content block."""
    content_val = cblock.get("content", "")
    # [LAW:dataflow-not-control-flow] Extract content text unconditionally
    if isinstance(content_val, list):
        # Extract text parts from list
        content_text = "".join(
            p.get("text", "") for p in content_val if p.get("type") == "text"
        )
    elif isinstance(content_val, str):
        content_text = content_val
    else:
        content_text = json.dumps(content_val)
    size = len(content_text.splitlines()) if content_text else 0
    is_error = cblock.get("is_error", False)
    tool_use_id = cblock.get("tool_use_id", "")
    # Look up correlated name, color, and detail
    msg_color_idx = ctx.msg_index % MSG_COLOR_CYCLE
    tool_name = ""
    tool_color_idx = msg_color_idx  # fallback to message color
    detail = ""
    correlated_tool_input: dict = {}
    if tool_use_id and tool_use_id in ctx.tool_id_map:
        tool_name, tool_color_idx, detail, correlated_tool_input = ctx.tool_id_map[tool_use_id]
    return [
        ToolResultBlock(
            size=size,
            is_error=is_error,
            msg_color_idx=tool_color_idx,
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            detail=detail,
            content=content_text,
            tool_input=correlated_tool_input,
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

    # Parse API metadata from metadata.user_id
    user_hash = ""
    account_id = ""
    session_id = ""
    metadata = body.get("metadata", {})
    if metadata:
        user_id_raw = metadata.get("user_id", "")
        if user_id_raw:
            parsed = parse_user_id(user_id_raw)
            if parsed:
                user_hash = parsed["user_hash"]
                account_id = parsed["account_id"]
                session_id = parsed["session_id"]

    # Track session changes — emit NewSessionBlock when session changes
    current_session = state.get("current_session")
    if session_id and session_id != current_session:
        blocks.append(NewSessionBlock(session_id=session_id))
        state["current_session"] = session_id

    blocks.append(
        MetadataBlock(
            model=str(model),
            max_tokens=str(max_tokens),
            stream=stream,
            tool_count=len(tools),
            user_hash=user_hash,
            account_id=account_id,
            session_id=session_id,
        )
    )

    # [LAW:one-source-of-truth] Header injection happens here, not in callers
    # format_request_headers({}) returns [], so extend is always safe
    blocks.extend(format_request_headers(request_headers or {}))

    # Store tool descriptions in state for ToolUseBlock enrichment
    # // [LAW:one-source-of-truth] tool_descriptions populated here, consumed by _format_tool_use_content
    state["tool_descriptions"] = {
        t.get("name", ""): t.get("description", "") for t in tools
    }

    # Context budget breakdown
    budget = compute_turn_budget(body)
    messages = body.get("messages", [])
    breakdown = tool_result_breakdown(messages)
    blocks.append(TurnBudgetBlock(budget=budget, tool_result_by_name=breakdown))

    # Tool definitions block (when tools are present)
    # // [LAW:dataflow-not-control-flow] Always evaluate; empty tools → no block appended
    if tools:
        per_tool_tokens = [estimate_tokens(json.dumps(t)) for t in tools]
        tool_def_block = ToolDefinitionsBlock(
            tools=tools,
            tool_tokens=per_tool_tokens,
            total_tokens=sum(per_tool_tokens),
        )
        tool_def_block.content_regions = [
            ContentRegion(index=i, kind="tool_def", tags=[tool.get("name", "?")], expanded=False)
            for i, tool in enumerate(tools)
        ]
        blocks.append(tool_def_block)

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
                    TextContentBlock(content=content, indent="    ", category=role_cat)
                )
        elif isinstance(content, list):
            for cblock in content:
                if isinstance(cblock, str):
                    blocks.append(
                        TextContentBlock(
                            content=cblock[:200], indent="    ", category=role_cat
                        )
                    )
                    continue
                btype = cblock.get("type", "?")
                factory = _CONTENT_BLOCK_FACTORIES.get(btype, _format_unknown_content)
                blocks.extend(factory(cblock, ctx))

        # Extract updated tool_color_counter from context
        tool_color_counter = ctx.tool_color_counter

    blocks.append(NewlineBlock())

    # Eagerly populate content_regions for all text blocks
    # // [LAW:single-enforcer] populate_content_regions is idempotent —
    # ToolDefinitionsBlock regions (created inline above) are preserved.
    for block in blocks:
        populate_content_regions(block)

    return blocks


def _fmt_message_start(event: MessageStartEvent) -> list[FormattedBlock]:
    """Handle message_start event."""
    return [StreamInfoBlock(model=event.message.model)]


def _fmt_tool_use_block_start(event: ToolUseBlockStartEvent) -> list[FormattedBlock]:
    """Handle content_block_start with type=tool_use."""
    return [StreamToolUseBlock(name=event.name)]


def _fmt_text_delta(event: TextDeltaEvent) -> list[FormattedBlock]:
    """Handle content_block_delta with type=text_delta."""
    if event.text:
        return [TextDeltaBlock(content=event.text, category=Category.ASSISTANT)]
    return []


def _fmt_message_delta(event: MessageDeltaEvent) -> list[FormattedBlock]:
    """Handle message_delta event."""
    if event.stop_reason != StopReason.NONE:
        return [StopReasonBlock(reason=event.stop_reason.value)]
    return []


# [LAW:dataflow-not-control-flow] Dispatch table: SSEEvent type -> formatter
_RESPONSE_EVENT_FORMATTERS: dict[type, Callable[..., list[FormattedBlock]]] = {
    MessageStartEvent: _fmt_message_start,
    TextBlockStartEvent: lambda _: [],
    ToolUseBlockStartEvent: _fmt_tool_use_block_start,
    TextDeltaEvent: _fmt_text_delta,
    InputJsonDeltaEvent: lambda _: [],
    ContentBlockStopEvent: lambda _: [],
    MessageDeltaEvent: _fmt_message_delta,
    MessageStopEvent: lambda _: [],
}


def format_response_event(sse_event: SSEEvent) -> list[FormattedBlock]:
    """Format a streaming SSE event as a list of FormattedBlock.

    // [LAW:one-source-of-truth] The class IS the type — dispatch on type().
    """
    formatter = _RESPONSE_EVENT_FORMATTERS.get(type(sse_event), lambda _: [])
    return formatter(sse_event)


# [LAW:dataflow-not-control-flow] Complete response content block factories
def _complete_text_block(block: dict) -> list:
    """Create blocks for text content."""
    text = block.get("text", "")
    if text:
        return [TextDeltaBlock(content=text, category=Category.ASSISTANT)]
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
        factory: Callable[[dict[str, Any]], list[FormattedBlock]] = _COMPLETE_RESPONSE_FACTORIES.get(block_type, lambda _: [])
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
    # [LAW:dataflow-not-control-flow] Always emit both blocks;
    # empty headers dict → HttpHeadersBlock with no entries (status code still shown)
    return [
        HeaderBlock(
            label="RESPONSE",
            request_num=0,
            timestamp=_get_timestamp(),
            header_type="response",
        ),
        HttpHeadersBlock(
            headers=headers_dict or {},
            header_type="response",
            status_code=status_code,
        ),
    ]
