"""Behavior tests for same-category render coalescing."""

from rich.console import Console

from cc_dump.formatting import Category, TextContentBlock, ToolUseBlock
from cc_dump.tui.rendering import render_turn_to_strips


def _arrow_for_block(strips, block_map, block_index: int) -> str:
    first_line = strips[block_map[block_index]]
    segments = list(first_line)
    if len(segments) < 2:
        return ""
    return segments[1].text


def test_consecutive_same_category_blocks_share_single_arrow_header():
    """Second block in same-category run renders as continuation (no arrow)."""
    console = Console()
    blocks = [
        ToolUseBlock(name="Read", category=Category.TOOLS),
        ToolUseBlock(name="Write", category=Category.TOOLS),
    ]

    strips, block_map, _ = render_turn_to_strips(blocks, {}, console, width=80)

    first_arrow = _arrow_for_block(strips, block_map, 0)
    second_arrow = _arrow_for_block(strips, block_map, 1)
    assert first_arrow != "   "
    assert second_arrow == "   "


def test_category_change_resets_coalesced_header_group():
    """A different category between runs restores arrow on next matching category."""
    console = Console()
    blocks = [
        ToolUseBlock(name="Read", category=Category.TOOLS),
        TextContentBlock(content="gap", category=Category.USER),
        ToolUseBlock(name="Write", category=Category.TOOLS),
    ]

    strips, block_map, _ = render_turn_to_strips(blocks, {}, console, width=80)

    first_arrow = _arrow_for_block(strips, block_map, 0)
    third_arrow = _arrow_for_block(strips, block_map, 2)
    assert first_arrow != "   "
    assert third_arrow != "   "
