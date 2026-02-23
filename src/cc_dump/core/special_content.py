"""Special request-content classification and navigation markers.

// [LAW:one-source-of-truth] markers_for_block() is the canonical classifier.
// [LAW:single-enforcer] collect_special_locations() is the sole marker locator.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


MARKER_CLAUDE_MD = "claude_md"
MARKER_HOOK = "hook"
MARKER_SKILL_CONSIDERATION = "skill_consideration"
MARKER_SKILL_SEND = "skill_send"
MARKER_TOOL_USE_LIST = "tool_use_list"


MARKER_LABELS: dict[str, str] = {
    MARKER_CLAUDE_MD: "CLAUDE.md",
    MARKER_HOOK: "hook",
    MARKER_SKILL_CONSIDERATION: "skills",
    MARKER_SKILL_SEND: "skill send",
    MARKER_TOOL_USE_LIST: "tools",
}


DISPLAY_MARKER_KEYS: tuple[str, ...] = (
    MARKER_CLAUDE_MD,
    MARKER_SKILL_CONSIDERATION,
    MARKER_SKILL_SEND,
    MARKER_TOOL_USE_LIST,
)


_SKILL_CONSIDERATION_RE = re.compile(
    r"(following skills are available|skills are available for use with the skill tool|skill considerations?)",
    re.IGNORECASE,
)
_TOOL_USE_LIST_RE = re.compile(
    r"(following tools are available|available tools|tool use list|tool list)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SpecialMarker:
    key: str
    label: str


@dataclass(frozen=True)
class SpecialLocation:
    marker: SpecialMarker
    turn_index: int
    block_index: int
    block: object


def _markers_for_config(block) -> list[str]:
    source = str(getattr(block, "source", "") or "")
    return [MARKER_CLAUDE_MD] if "claude.md" in source.lower() else []


def _markers_for_hook(block) -> list[str]:
    content = str(getattr(block, "content", "") or "")
    markers: list[str] = [MARKER_HOOK]
    if _SKILL_CONSIDERATION_RE.search(content):
        markers.append(MARKER_SKILL_CONSIDERATION)
    if _TOOL_USE_LIST_RE.search(content):
        markers.append(MARKER_TOOL_USE_LIST)
    return markers


def _markers_for_text(block) -> list[str]:
    """Fallback text classifier for user-controlled request text."""
    category = str(getattr(block, "category", "") or "").lower()
    if "user" not in category:
        return []
    content = str(getattr(block, "content", "") or "")
    markers: list[str] = []
    if "claude.md" in content.lower():
        markers.append(MARKER_CLAUDE_MD)
    if _SKILL_CONSIDERATION_RE.search(content):
        markers.append(MARKER_SKILL_CONSIDERATION)
    if _TOOL_USE_LIST_RE.search(content):
        markers.append(MARKER_TOOL_USE_LIST)
    return markers


def _markers_for_tool_use(block) -> list[str]:
    tool_name = str(getattr(block, "name", "") or "")
    if tool_name == "Skill":
        return [MARKER_SKILL_SEND]
    return []


def _markers_for_tool_defs_section(block) -> list[str]:
    tool_count = int(getattr(block, "tool_count", 0) or 0)
    return [MARKER_TOOL_USE_LIST] if tool_count > 0 else []


_CLASSIFIERS = {
    "ConfigContentBlock": _markers_for_config,
    "HookOutputBlock": _markers_for_hook,
    "TextContentBlock": _markers_for_text,
    "ToolUseBlock": _markers_for_tool_use,
    "ToolDefsSection": _markers_for_tool_defs_section,
}


def markers_for_block(block) -> tuple[SpecialMarker, ...]:
    """Return marker labels for a block (possibly empty)."""
    classifier = _CLASSIFIERS.get(type(block).__name__)
    if classifier is None:
        return ()
    keys = classifier(block)
    return tuple(
        SpecialMarker(key=key, label=MARKER_LABELS[key])
        for key in keys
        if key in MARKER_LABELS
    )


def display_markers_for_block(block) -> tuple[SpecialMarker, ...]:
    """Return marker labels intended for inline renderer badges."""
    return tuple(
        marker
        for marker in markers_for_block(block)
        if marker.key in DISPLAY_MARKER_KEYS
    )


def _iter_descendants_with_hier_idx(block, hier_idx: int):
    """Yield (hier_idx, block) in pre-order traversal."""
    yield (hier_idx, block)
    for child in getattr(block, "children", []) or []:
        yield from _iter_descendants_with_hier_idx(child, hier_idx)


def collect_special_locations(turns: list, marker_key: str = "all") -> list[SpecialLocation]:
    """Collect marker locations in chronological order across completed turns."""
    locations: list[SpecialLocation] = []

    for turn_idx, turn in enumerate(turns):
        if getattr(turn, "is_streaming", False):
            continue
        for block_idx, top_block in enumerate(turn.blocks):
            for hier_idx, block in _iter_descendants_with_hier_idx(top_block, block_idx):
                for marker in markers_for_block(block):
                    if marker_key != "all" and marker.key != marker_key:
                        continue
                    locations.append(
                        SpecialLocation(
                            marker=marker,
                            turn_index=turn_idx,
                            block_index=hier_idx,
                            block=block,
                        )
                    )
    return locations
