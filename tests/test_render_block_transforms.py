"""Behavior tests for render-stage block transforms."""

from rich.console import Console

from cc_dump.core.formatting import (
    Category,
    NewlineBlock,
    TextContentBlock,
    TrackedContentBlock,
    VisState,
)
from cc_dump.tui.rendering import render_turn_to_strips


def test_render_turn_to_strips_hides_empty_leaf_block_output():
    """Empty leaf output is filtered out of strips/flat block mapping."""
    console = Console()
    filters = {"system": VisState(True, False, True)}
    block = TrackedContentBlock(
        status="unknown-status",
        category=Category.SYSTEM,
    )

    strips, block_map, flat_blocks = render_turn_to_strips(
        [block],
        filters,
        console,
        width=80,
    )

    assert strips == []
    assert block_map == {}
    assert flat_blocks == []


def test_render_turn_to_strips_preserves_structural_newline_block():
    """Structural spacer blocks remain renderable even with empty text output."""
    console = Console()
    block = NewlineBlock()

    strips, block_map, flat_blocks = render_turn_to_strips(
        [block],
        {},
        console,
        width=80,
    )

    assert len(strips) == 1
    assert block_map == {0: 0}
    assert flat_blocks == [block]


def test_render_turn_to_strips_keeps_non_empty_leaf_blocks():
    """Non-empty leaf blocks continue to render normally."""
    console = Console()
    block = TextContentBlock(content="hello", category=Category.USER)

    strips, block_map, flat_blocks = render_turn_to_strips(
        [block],
        {},
        console,
        width=80,
    )

    assert len(strips) >= 1
    assert block_map == {0: 0}
    assert flat_blocks == [block]
