"""Tests for ViewOverrides — block identity, override store, serialization.

Covers AC1–AC6 from the plan.
"""

import copy

from textual.theme import BUILTIN_THEMES

from cc_dump.formatting import (
    FormattedBlock,
    TextContentBlock,
    ToolUseBlock,
    HeaderBlock,
    Category,
    VisState,
    ALWAYS_VISIBLE,
    populate_content_regions,
)
from cc_dump.tui.view_overrides import (
    BlockViewState,
    RegionViewState,
    ViewOverrides,
)


def _setup_theme():
    """Initialize theme for tests."""
    from cc_dump.tui.rendering import set_theme
    set_theme(BUILTIN_THEMES["textual-dark"])


# ─── AC1: block_id unique in turn ─────────────────────────────────────────


def test_block_id_unique_in_turn():
    """All block_ids in a batch of blocks are unique."""
    blocks = [
        TextContentBlock(content="a"),
        TextContentBlock(content="b"),
        ToolUseBlock(name="Bash", input_size=10, msg_color_idx=0),
        HeaderBlock(label="REQUEST #1", request_num=1),
    ]
    ids = [b.block_id for b in blocks]
    assert len(ids) == len(set(ids)), f"Duplicate block_ids: {ids}"


# ─── AC2: block_id monotonic ──────────────────────────────────────────────


def test_block_id_monotonic():
    """Block_ids from successive block creation are strictly increasing."""
    batch1 = [TextContentBlock(content="x") for _ in range(3)]
    max1 = max(b.block_id for b in batch1)

    batch2 = [TextContentBlock(content="y") for _ in range(3)]
    min2 = min(b.block_id for b in batch2)

    assert min2 > max1, f"batch2 min {min2} should be > batch1 max {max1}"


# ─── AC3: clear_category ──────────────────────────────────────────────────


def test_view_overrides_clear_category():
    """Set overrides on 3 categories, clear one — other two unchanged."""
    _setup_theme()

    vo = ViewOverrides()

    user_block = TextContentBlock(content="hi", category=Category.USER)
    asst_block = TextContentBlock(content="hello", category=Category.ASSISTANT)
    tool_block = ToolUseBlock(name="Read", input_size=10, msg_color_idx=0)

    # Set expanded overrides
    vo.get_block(user_block.block_id).expanded = True
    vo.get_block(asst_block.block_id).expanded = False
    vo.get_block(tool_block.block_id).expanded = True

    # Clear only USER category
    vo.clear_category([user_block, asst_block, tool_block], Category.USER)

    assert vo.get_block(user_block.block_id).expanded is None  # cleared
    assert vo.get_block(asst_block.block_id).expanded is False  # untouched
    assert vo.get_block(tool_block.block_id).expanded is True  # untouched


# ─── AC4: clear_search ────────────────────────────────────────────────────


def test_view_overrides_clear_search():
    """Set force_vis on 5 blocks, clear → all force_vis is None."""
    vo = ViewOverrides()

    block_ids = []
    for i in range(5):
        b = TextContentBlock(content=f"block {i}")
        block_ids.append(b.block_id)
        vo.get_block(b.block_id).force_vis = ALWAYS_VISIBLE
        vo._search_block_ids.add(b.block_id)

    # All should be set
    for bid in block_ids:
        assert vo.get_block(bid).force_vis is ALWAYS_VISIBLE

    # Clear
    vo.clear_search()

    for bid in block_ids:
        assert vo.get_block(bid).force_vis is None
    assert len(vo._search_block_ids) == 0


# ─── AC5: serialization round-trip ────────────────────────────────────────


def test_view_overrides_serialization():
    """to_dict() → from_dict() round-trip preserves block and region state."""
    vo = ViewOverrides()

    b1 = TextContentBlock(content="one")
    b2 = TextContentBlock(content="two")

    vo.get_block(b1.block_id).expanded = True
    vo.get_block(b1.block_id).expandable = True
    vo.get_block(b2.block_id).expanded = False

    vo.get_region(b1.block_id, 0).expanded = False
    vo.get_region(b1.block_id, 1).expanded = None  # default — not serialized

    data = vo.to_dict()
    restored = ViewOverrides.from_dict(data)

    # Block state
    assert restored.get_block(b1.block_id).expanded is True
    assert restored.get_block(b1.block_id).expandable is True
    assert restored.get_block(b2.block_id).expanded is False

    # Region state
    assert restored.get_region(b1.block_id, 0).expanded is False

    # force_vis is NOT serialized (transient search state)
    vo.get_block(b1.block_id).force_vis = ALWAYS_VISIBLE
    data2 = vo.to_dict()
    restored2 = ViewOverrides.from_dict(data2)
    assert restored2.get_block(b1.block_id).force_vis is None


# ─── AC6: blocks not mutated by render ────────────────────────────────────


def test_blocks_not_mutated_by_render():
    """render_turn_to_strips() with overrides does not mutate block fields.

    AC6: Verifies overrides parameter routes view mutations to ViewOverrides.
    When overrides is provided, block domain fields (category, block_id) are unchanged
    and expandable is written to overrides instead of monkey-patched onto the block.
    """
    from rich.console import Console
    from cc_dump.tui.rendering import render_turn_to_strips

    _setup_theme()

    block = TextContentBlock(content="Hello world", category=Category.ASSISTANT)
    populate_content_regions(block)

    vo = ViewOverrides()

    # Snapshot block state before render
    pre_category = block.category
    pre_block_id = block.block_id

    console = Console()
    filters = {"assistant": ALWAYS_VISIBLE}

    render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
        overrides=vo,
    )

    # Domain fields unchanged
    assert block.category == pre_category
    assert block.block_id == pre_block_id
    # No _expandable attribute on block — lives in overrides
    assert "_expandable" not in vars(block)

    # expandable written to overrides
    bvs = vo.get_block(block.block_id)
    assert isinstance(bvs.expandable, bool)


def test_auto_create_on_miss():
    """get_block and get_region auto-create on miss."""
    vo = ViewOverrides()
    bvs = vo.get_block(999)
    assert isinstance(bvs, BlockViewState)
    assert bvs.expanded is None
    assert bvs.force_vis is None
    assert bvs.expandable is False

    rvs = vo.get_region(999, 0)
    assert isinstance(rvs, RegionViewState)
    assert rvs.expanded is None
    assert rvs.strip_range is None


def test_clear_search_empty_is_noop():
    """clear_search on empty overrides is a no-op."""
    vo = ViewOverrides()
    vo.clear_search()  # should not raise
    assert len(vo._search_block_ids) == 0
