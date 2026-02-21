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
from typing import NamedTuple

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
from cc_dump.palette import TAG_COLOR_COUNT
import cc_dump.segmentation

# Type alias for content block dicts from the API response
_ContentBlockDict = dict[str, str | int | dict | list | None]


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
    """Block category — groups blocks for visibility control.

    6 categories: USER, ASSISTANT, TOOLS, SYSTEM, METADATA, THINKING.
    METADATA consolidates former BUDGET, METADATA, and HEADERS categories.
    """

    USER = "user"
    ASSISTANT = "assistant"
    TOOLS = "tools"
    SYSTEM = "system"
    METADATA = "metadata"
    THINKING = "thinking"


# ─── Structured IR ────────────────────────────────────────────────────────────

# // [LAW:one-source-of-truth] Block identity — monotonic, unique per process.
_next_block_id: int = 0


def _auto_id() -> int:
    """Allocate a unique block_id. Monotonically increasing per process."""
    global _next_block_id
    _next_block_id += 1
    return _next_block_id


@dataclass
class ContentRegion:
    """An independently expandable/collapsible region within a block.

    // [LAW:one-source-of-truth] Domain data only. View state (expanded, strip_range)
    // lives in ViewOverrides.RegionViewState.

    kind: structural discriminator — determines rendering behavior.
        Values: "xml_block", "md", "code_fence", "md_fence", "tool_def"
    tags: semantic labels for navigation/search (e.g., XML tag name, tool name).
        Empty list = not navigable.
    """

    index: int  # Position in parent's content_regions list
    kind: str = ""  # "xml_block", "md", "code_fence", "md_fence", "tool_def"
    tags: list[str] = field(default_factory=list)  # Semantic labels for navigation


def populate_content_regions(block: "FormattedBlock") -> None:
    """Eagerly populate content_regions from text segmentation.

    Idempotent. Creates one ContentRegion per SubBlock segment
    (MD, CODE_FENCE, MD_FENCE, XML_BLOCK) — not just XML.

    // [LAW:single-enforcer] Single place that creates text-based ContentRegion instances.
    // [LAW:dataflow-not-control-flow] Pure data population, not control flow.

    FUTURE: content-derived tags — scan region text for identifiable content
    (e.g., "CLAUDE.md" in system-reminder text) and add to tags list.
    """
    if block.content_regions:
        return

    text = getattr(block, "content", "") or ""
    if not text:
        return

    seg = cc_dump.segmentation.segment(text)
    if not seg.sub_blocks:
        return

    regions: list[ContentRegion] = []
    for i, sb in enumerate(seg.sub_blocks):
        kind = sb.kind.value  # "md", "code_fence", "md_fence", "xml_block"

        tags: list[str] = []
        if sb.kind == cc_dump.segmentation.SubBlockKind.XML_BLOCK:
            tags = [sb.meta.tag_name]
        elif sb.kind == cc_dump.segmentation.SubBlockKind.CODE_FENCE and sb.meta.info:
            tags = [sb.meta.info]

        regions.append(ContentRegion(index=i, kind=kind, tags=tags))

    block.content_regions = regions


@dataclass
class FormattedBlock:
    """Base class for all formatted output blocks.

    Visibility axes:
    - Level (per-category, keyboard cycle): EXISTENCE / SUMMARY / FULL
    - category: overrides static BLOCK_CATEGORY for context-dependent blocks
      (e.g., TextContentBlock can be USER or ASSISTANT depending on the message).

    Per-block view state (expanded, _expandable, _force_vis) lives in
    ViewOverrides, owned by ConversationView — not on the block itself.

    Sub-region axis:
    - content_regions: list[ContentRegion] — independently toggleable regions
      within the block (e.g., XML sub-blocks). Empty = no sub-regions.
    """

    # // [LAW:one-source-of-truth] Stable identity for cache keys and ViewOverrides.
    block_id: int = field(default_factory=_auto_id)

    # Context-dependent category override. None = use static BLOCK_CATEGORY.
    category: Category | None = None

    # Whether this block should be rendered during streaming.
    # // [LAW:dataflow-not-control-flow] Block type declares streaming behavior,
    # // consumer code checks the value, not the type.
    show_during_streaming: bool = False

    # Per-region expand/collapse state. Empty = no sub-regions.
    # // [LAW:one-source-of-truth] All sub-region state lives here, not in shadow attrs.
    content_regions: list[ContentRegion] = field(default_factory=list)

    # Claude Code session ID (from user_id metadata). Stamped on all blocks.
    session_id: str = ""
    # Stream/agent attribution stamped by stream registry at event ingress.
    # // [LAW:one-source-of-truth] Attribution is data on canonical blocks.
    lane_id: str = ""
    agent_kind: str = ""  # "main" | "subagent" | "unknown"
    agent_label: str = ""


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


@dataclass
class NewSessionBlock(FormattedBlock):
    """Indicates a new Claude Code session started."""

    pass


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
    show_during_streaming: bool = True


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


# ─── Hierarchical container blocks ───────────────────────────────────────────
# // [LAW:one-type-per-behavior] All containers share the same children pattern.
# // [LAW:dataflow-not-control-flow] Containers always have children; emptiness
# // is expressed via empty list, not absence of the field.


@dataclass
class ThinkingBlock(FormattedBlock):
    """Extended thinking content block.

    Represents {"type": "thinking", "thinking": "..."} in API response.
    """

    content: str = ""
    indent: str = "    "


@dataclass
class ConfigContentBlock(FormattedBlock):
    """Injected configuration content within a user message.

    Detected from CLAUDE.md, plugin content, agent instructions.
    Source tagging identifies the origin when detectable.
    """

    content: str = ""
    source: str = ""  # e.g., "project CLAUDE.md", "plugin: do", "unknown"
    indent: str = "    "


@dataclass
class HookOutputBlock(FormattedBlock):
    """Hook output injected into user messages.

    Detected from <user-prompt-submit-hook>, <system-reminder> tags.
    """

    content: str = ""
    hook_name: str = ""  # e.g., "UserPromptSubmit", "system-reminder"
    indent: str = "    "


@dataclass
class MessageBlock(FormattedBlock):
    """Container for one entry in messages[] array.

    Renders its own header ("USER [0]" / "ASSISTANT [3]") and holds
    child content blocks (TextContentBlock, ToolUseBlock, etc.).
    // [LAW:one-source-of-truth] Replaces RoleBlock + flat block list.
    """

    role: str = ""  # "user" or "assistant"
    msg_index: int = 0
    timestamp: str = ""
    children: list[FormattedBlock] = field(default_factory=list)


@dataclass
class MetadataSection(FormattedBlock):
    """Container for combined request metadata.

    Children: ModelParamsBlock, HttpHeadersBlock, TokenBudgetBlock.
    """

    children: list[FormattedBlock] = field(default_factory=list)


@dataclass
class SystemSection(FormattedBlock):
    """Container for the system field from the request body.

    Children: TrackedContentBlock instances.
    """

    children: list[FormattedBlock] = field(default_factory=list)


@dataclass
class ToolDefsSection(FormattedBlock):
    """Container for the tools array from the request body.

    Children: ToolDefBlock instances.
    """

    tool_count: int = 0
    total_tokens: int = 0
    children: list[FormattedBlock] = field(default_factory=list)


@dataclass
class ToolDefBlock(FormattedBlock):
    """Individual tool definition (child of ToolDefsSection).

    For known compound tools (Skill, Task), has its own children.
    """

    name: str = ""
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    token_estimate: int = 0
    children: list[FormattedBlock] = field(default_factory=list)


@dataclass
class SkillDefChild(FormattedBlock):
    """Individual skill within the Skill tool definition."""

    name: str = ""
    description: str = ""
    plugin_source: str = ""  # e.g., "do", "plugin-dev"


@dataclass
class AgentDefChild(FormattedBlock):
    """Individual agent type within the Task tool definition."""

    name: str = ""
    description: str = ""
    available_tools: str = ""  # e.g., "All tools"


@dataclass
class ResponseMetadataSection(FormattedBlock):
    """Container for response HTTP headers + model info.

    Children: HttpHeadersBlock, StreamInfoBlock.
    """

    children: list[FormattedBlock] = field(default_factory=list)



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
            color_idx = state["next_color"] % TAG_COLOR_COUNT
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
    color_idx = state["next_color"] % TAG_COLOR_COUNT
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


def _format_thinking_content(cblock, ctx: _ContentContext) -> list:
    """Format a thinking content block."""
    text = cblock.get("thinking", "")
    return [ThinkingBlock(content=text, indent=ctx.indent, category=Category.THINKING)]


_CONTENT_BLOCK_FACTORIES = {
    "text": _format_text_content,
    "tool_use": _format_tool_use_content,
    "tool_result": _format_tool_result_content,
    "image": _format_image_content,
    "thinking": _format_thinking_content,
}


# ─── Compound tool decomposition ─────────────────────────────────────────────
# // [LAW:one-source-of-truth] Known compound tools parsed into children.
# Hardcoded for Skill (→ skills) and Task (→ agents). Extensible list.


def _parse_skill_children(description: str) -> list["FormattedBlock"]:
    """Parse Skill tool description into SkillDefChild blocks.

    Extracts skill entries from the description's "user-invocable skills" section
    and from lines matching '- skill_name: description' pattern.
    """
    children: list[FormattedBlock] = []
    # Look for lines matching "- name: description" or "- plugin:name: description"
    for line in description.splitlines():
        line = line.strip()
        if line.startswith("- ") and ":" in line[2:]:
            # Extract name and description
            rest = line[2:]  # Remove "- "
            # Handle "name: description" or "plugin:name: description"
            # Find the first ": " that's likely a separator (not part of plugin:name)
            colon_idx = rest.find(": ")
            if colon_idx > 0:
                name = rest[:colon_idx].strip()
                desc = rest[colon_idx + 2:].strip().strip('"')
                # Detect plugin source from name
                plugin_source = ""
                if ":" in name:
                    parts = name.split(":", 1)
                    plugin_source = parts[0]
                children.append(SkillDefChild(
                    name=name,
                    description=desc,
                    plugin_source=plugin_source,
                    category=Category.TOOLS,
                ))
    return children


def _parse_agent_children(description: str) -> list["FormattedBlock"]:
    """Parse Task tool description into AgentDefChild blocks.

    Extracts agent type entries from the description's "Available agent types" section.
    Looks for '- AgentName: description' pattern within the description text.
    """
    children: list[FormattedBlock] = []
    # Look for lines matching "- Name: description (Tools: ...)"
    for line in description.splitlines():
        line = line.strip()
        if line.startswith("- ") and ":" in line[2:]:
            rest = line[2:]
            colon_idx = rest.find(": ")
            if colon_idx > 0:
                name = rest[:colon_idx].strip()
                desc_part = rest[colon_idx + 2:].strip()
                # Extract tools list if present
                tools_str = ""
                if "(Tools:" in desc_part:
                    tools_start = desc_part.index("(Tools:")
                    tools_str = desc_part[tools_start + 7:].rstrip(")")
                    desc_part = desc_part[:tools_start].strip()
                children.append(AgentDefChild(
                    name=name,
                    description=desc_part.strip('"'),
                    available_tools=tools_str.strip(),
                    category=Category.TOOLS,
                ))
    return children


# // [LAW:one-source-of-truth] Known compound tools and their child parsers.
_COMPOUND_TOOL_PARSERS: dict[str, "Callable[[str], list[FormattedBlock]]"] = {
    "Skill": _parse_skill_children,
    "Task": _parse_agent_children,
}



def format_request(body, state, request_headers: dict | None = None):
    """Format a full API request as a list of FormattedBlock.

    Produces hierarchical container blocks (MetadataSection, ToolDefsSection,
    SystemSection, MessageBlock). Top-level blocks contain children; the
    rendering pipeline flattens them for display.

    Args:
        body: Request body dict
        state: Content tracking state dict
        request_headers: Optional HTTP request headers to include in MetadataSection

    Returns:
        List of FormattedBlock objects (hierarchical — containers with children)
    """
    state["request_counter"] += 1
    request_num = state["request_counter"]

    blocks: list[FormattedBlock] = []
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
        blocks.append(NewSessionBlock())
        state["current_session"] = session_id

    # MetadataSection container — groups model params, HTTP headers, budget
    # // [LAW:one-source-of-truth] Single container for all request metadata.
    metadata_block = MetadataBlock(
        model=str(model),
        max_tokens=str(max_tokens),
        stream=stream,
        tool_count=len(tools),
        user_hash=user_hash,
        account_id=account_id,
    )

    # [LAW:one-source-of-truth] Header injection happens here, not in callers
    header_blocks = format_request_headers(request_headers or {})

    # Store tool descriptions in state for ToolUseBlock enrichment
    # // [LAW:one-source-of-truth] tool_descriptions populated here, consumed by _format_tool_use_content
    state["tool_descriptions"] = {
        t.get("name", ""): t.get("description", "") for t in tools
    }

    # Context budget breakdown
    budget = compute_turn_budget(body)
    messages = body.get("messages", [])
    breakdown = tool_result_breakdown(messages)
    budget_block = TurnBudgetBlock(budget=budget, tool_result_by_name=breakdown)

    # Emit MetadataSection container (children flattened by rendering pipeline)
    blocks.append(MetadataSection(
        children=[metadata_block] + header_blocks + [budget_block],
        category=Category.METADATA,
    ))

    # ToolDefsSection container — groups tool definitions
    # [LAW:dataflow-not-control-flow] Always create block, renderer handles empty list
    per_tool_tokens = [estimate_tokens(json.dumps(t)) for t in tools]
    total_tool_tokens = sum(per_tool_tokens)

    # // [LAW:one-source-of-truth] Compound tools parsed into children via _COMPOUND_TOOL_PARSERS.
    tool_def_children: list[FormattedBlock] = []
    for i, tool in enumerate(tools):
        tool_name = tool.get("name", "?")
        tool_desc = tool.get("description", "")
        # Parse compound tools into children
        parser = _COMPOUND_TOOL_PARSERS.get(tool_name)
        compound_children = parser(tool_desc) if parser else []
        tool_def_children.append(ToolDefBlock(
            name=tool_name,
            description=tool_desc,
            input_schema=tool.get("input_schema", {}),
            token_estimate=per_tool_tokens[i] if i < len(per_tool_tokens) else 0,
            children=compound_children,
            category=Category.TOOLS,
        ))

    # Emit ToolDefsSection container
    blocks.append(ToolDefsSection(
        tool_count=len(tools),
        total_tokens=total_tool_tokens,
        children=tool_def_children,
        category=Category.TOOLS,
    ))

    blocks.append(SeparatorBlock(style="thin"))

    # SystemSection container — groups system prompt blocks
    system = body.get("system", "")
    system_children: list[FormattedBlock] = []
    if system:
        if isinstance(system, str):
            system_children.append(track_content(system, "system:0", state))
        elif isinstance(system, list):
            for i, sblock in enumerate(system):
                text = sblock.get("text", "") if isinstance(sblock, dict) else str(sblock)
                system_children.append(track_content(text, "system:{}".format(i), state))

    # Emit SystemSection container (always — renderer handles empty children)
    blocks.append(SystemSection(
        children=system_children,
        category=Category.SYSTEM,
    ))
    blocks.append(SeparatorBlock(style="thin"))

    # Tool correlation state (per-request, not persistent)
    tool_id_map: dict[
        str, tuple[str, int, str, dict]
    ] = {}  # tool_use_id -> (name, color_idx, detail, tool_input)
    tool_color_counter = 0

    # Messages — each wrapped in a MessageBlock container
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

        # Create shared context for content block formatters
        ctx = _ContentContext(
            role_cat=role_cat,
            state=state,
            tool_id_map=tool_id_map,
            tool_color_counter=tool_color_counter,
            msg_index=i,
            indent="    ",
        )

        # Build children for this message
        msg_children: list[FormattedBlock] = []

        if isinstance(content, str):
            if content:
                msg_children.append(
                    TextContentBlock(content=content, indent="    ", category=role_cat)
                )
        elif isinstance(content, list):
            for cblock in content:
                if isinstance(cblock, str):
                    msg_children.append(
                        TextContentBlock(
                            content=cblock[:200], indent="    ", category=role_cat
                        )
                    )
                    continue
                btype = cblock.get("type", "?")
                factory = _CONTENT_BLOCK_FACTORIES.get(btype, _format_unknown_content)
                msg_children.extend(factory(cblock, ctx))

        # Extract updated tool_color_counter from context
        tool_color_counter = ctx.tool_color_counter

        # // [LAW:one-source-of-truth] MessageBlock container replaces RoleBlock + flat children.
        blocks.append(MessageBlock(
            role=role,
            msg_index=i,
            timestamp=_get_timestamp(),
            children=msg_children,
            category=role_cat,
        ))

    blocks.append(NewlineBlock())

    # Eagerly populate content_regions for all text blocks (recursive tree walk)
    # // [LAW:single-enforcer] populate_content_regions is idempotent.
    def _walk_blocks(block_list):
        for block in block_list:
            populate_content_regions(block)
            block.session_id = session_id
            _walk_blocks(getattr(block, "children", []))
    _walk_blocks(blocks)

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
_RESPONSE_EVENT_FORMATTERS: dict[type[SSEEvent], Callable[[SSEEvent], list[FormattedBlock]]] = {
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
        return [TextContentBlock(content=text, category=Category.ASSISTANT)]
    return []


def _complete_tool_use_block(block: dict) -> list:
    """Create blocks for tool_use content."""
    tool_name = block.get("name", "?")
    return [StreamToolUseBlock(name=tool_name)]


def _complete_thinking_block(block: dict) -> list:
    """Create blocks for thinking content."""
    text = block.get("thinking", "")
    if text:
        return [ThinkingBlock(content=text, category=Category.THINKING)]
    return []


# [LAW:dataflow-not-control-flow] Complete response content block factories
_COMPLETE_RESPONSE_FACTORIES = {
    "text": _complete_text_block,
    "tool_use": _complete_tool_use_block,
    "thinking": _complete_thinking_block,
}


def format_complete_response(complete_message):
    """Format a complete (non-streaming) Claude message as FormattedBlocks.

    Wraps content in a MessageBlock container for structural consistency with
    the request-side message formatting. Metadata blocks (StreamInfoBlock,
    StopReasonBlock) remain outside the container.
    // [LAW:one-source-of-truth] One block structure for responses, regardless of transport.

    Args:
        complete_message: Complete Claude API message dict

    Returns:
        List of FormattedBlock objects
    """
    result: list[FormattedBlock] = []

    # Model info — metadata, outside container
    model = complete_message.get("model", "?")
    result.append(StreamInfoBlock(model=model))

    # [LAW:dataflow-not-control-flow] Content blocks via dispatch table
    content_children: list[FormattedBlock] = []
    content = complete_message.get("content", [])
    for block in content:
        block_type = block.get("type", "")
        factory: Callable[[_ContentBlockDict], list[FormattedBlock]] = _COMPLETE_RESPONSE_FACTORIES.get(block_type, lambda _: [])
        content_children.extend(factory(block))

    # // [LAW:one-source-of-truth] MessageBlock wraps content, matching request-side structure.
    result.append(MessageBlock(
        role="assistant",
        msg_index=0,
        children=content_children,
        category=Category.ASSISTANT,
    ))

    # [LAW:dataflow-not-control-flow] Always create block, let renderer handle empty
    stop_reason = complete_message.get("stop_reason", "")
    result.append(StopReasonBlock(reason=stop_reason))

    return result


def format_request_headers(headers_dict: dict) -> list:
    """Format HTTP request headers as blocks."""
    # [LAW:dataflow-not-control-flow] Always create block, renderer handles empty dict
    return [HttpHeadersBlock(headers=headers_dict or {}, header_type="request")]


def format_response_headers(status_code: int, headers_dict: dict) -> list:
    """Format HTTP response headers as a ResponseMetadataSection container."""
    # [LAW:dataflow-not-control-flow] Always emit container;
    # empty headers dict → HttpHeadersBlock with no entries (status code still shown)
    return [
        ResponseMetadataSection(
            children=[
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
            ],
            category=Category.METADATA,
        )
    ]
