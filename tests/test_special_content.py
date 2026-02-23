"""Tests for special content classification and marker location collection."""

from cc_dump.core.formatting import (
    Category,
    ConfigContentBlock,
    HookOutputBlock,
    TextContentBlock,
    ToolDefsSection,
    ToolUseBlock,
)
from cc_dump.core.special_content import (
    MARKER_CLAUDE_MD,
    MARKER_HOOK,
    MARKER_SKILL_CONSIDERATION,
    MARKER_SKILL_SEND,
    MARKER_TOOL_USE_LIST,
    collect_special_locations,
    display_markers_for_block,
    markers_for_block,
)


class _Turn:
    def __init__(self, blocks, *, is_streaming=False):
        self.blocks = blocks
        self.is_streaming = is_streaming


def _marker_keys(markers):
    return {m.key for m in markers}


def test_markers_for_config_detects_claude_md():
    block = ConfigContentBlock(source="/Users/test/.claude/CLAUDE.md", content="x")
    assert _marker_keys(markers_for_block(block)) == {MARKER_CLAUDE_MD}


def test_markers_for_hook_detects_hook_and_skills():
    block = HookOutputBlock(
        hook_name="system-reminder",
        content="The following skills are available for use with the Skill tool:",
    )
    assert _marker_keys(markers_for_block(block)) == {MARKER_HOOK, MARKER_SKILL_CONSIDERATION}


def test_markers_for_hook_detects_tool_list_phrase():
    block = HookOutputBlock(
        hook_name="system-reminder",
        content="The following tools are available to use in this session.",
    )
    assert _marker_keys(markers_for_block(block)) == {MARKER_HOOK, MARKER_TOOL_USE_LIST}


def test_markers_for_skill_tool_use_detects_skill_send():
    block = ToolUseBlock(name="Skill", input_size=1, detail="commit")
    assert _marker_keys(markers_for_block(block)) == {MARKER_SKILL_SEND}


def test_markers_for_user_text_fallback_detects_special_tokens():
    block = TextContentBlock(
        category=Category.USER,
        content="Contents of /tmp/CLAUDE.md\nThe following tools are available",
    )
    assert _marker_keys(markers_for_block(block)) == {MARKER_CLAUDE_MD, MARKER_TOOL_USE_LIST}


def test_display_markers_excludes_hook_badge():
    block = HookOutputBlock(
        hook_name="system-reminder",
        content="The following skills are available for use with the Skill tool:",
    )
    assert _marker_keys(display_markers_for_block(block)) == {MARKER_SKILL_CONSIDERATION}


def test_collect_special_locations_orders_chronologically_and_filters():
    turns = [
        _Turn([ConfigContentBlock(source="/tmp/CLAUDE.md", content="a")]),
        _Turn([ToolUseBlock(name="Skill", input_size=1)]),
        _Turn([ToolDefsSection(tool_count=2)]),
    ]

    all_locs = collect_special_locations(turns)
    assert [loc.marker.key for loc in all_locs] == [
        MARKER_CLAUDE_MD,
        MARKER_SKILL_SEND,
        MARKER_TOOL_USE_LIST,
    ]

    skill_locs = collect_special_locations(turns, marker_key=MARKER_SKILL_SEND)
    assert len(skill_locs) == 1
    assert skill_locs[0].turn_index == 1
