"""Tests for ViewOverrides — block identity, override store, serialization."""


from types import SimpleNamespace

from rich.color import Color
from textual.theme import BUILTIN_THEMES

from cc_dump.core.formatting import (
    TextContentBlock,
    ToolUseBlock,
    HeaderBlock,
    ErrorBlock,
    Category,
    ALWAYS_VISIBLE,
    VisState,
    populate_content_regions,
)
from cc_dump.tui.search import (
    SearchContext,
    SearchMode,
    compile_search_pattern,
    find_all_matches,
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
    """Set region overrides on 2 categories, clear one — the other remains."""
    _setup_theme()

    vo = ViewOverrides()

    user_block = TextContentBlock(content="hi", category=Category.USER)
    asst_block = TextContentBlock(content="hello", category=Category.ASSISTANT)
    populate_content_regions(user_block)
    populate_content_regions(asst_block)

    # Set region overrides
    vo.get_region(user_block.block_id, 0).expanded = False
    vo.get_region(asst_block.block_id, 0).expanded = False
    vo.get_block(user_block.block_id).expanded = False
    vo.get_block(asst_block.block_id).expanded = False

    # Clear only USER category
    vo.clear_category([user_block, asst_block], Category.USER)

    assert vo.get_region(user_block.block_id, 0).expanded is None  # cleared
    assert vo.get_region(asst_block.block_id, 0).expanded is False  # untouched
    assert vo.get_block(user_block.block_id).expanded is None  # cleared
    assert vo.get_block(asst_block.block_id).expanded is False  # untouched


# ─── AC4: serialization round-trip ────────────────────────────────────────


def test_view_overrides_serialization():
    """to_dict() → from_dict() round-trip preserves block and region state."""
    vo = ViewOverrides()

    b1 = TextContentBlock(content="one")
    b2 = TextContentBlock(content="two")

    vo.get_block(b1.block_id).expandable = True
    vo.get_block(b2.block_id).expandable = False
    vo.get_block(b1.block_id).expanded = False

    vo.get_region(b1.block_id, 0).expanded = False
    vo.get_region(b1.block_id, 1).expanded = None  # default — not serialized

    data = vo.to_dict()
    restored = ViewOverrides.from_dict(data)

    # Block state
    assert restored.get_block(b1.block_id).expandable is True
    assert restored.get_block(b2.block_id).expandable is False
    assert restored.get_block(b1.block_id).expanded is False

    # Region state
    assert restored.get_region(b1.block_id, 0).expanded is False

# ─── AC5: blocks not mutated by render ────────────────────────────────────


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
    assert bvs.expandable is False

    rvs = vo.get_region(999, 0)
    assert isinstance(rvs, RegionViewState)
    assert rvs.expanded is None
    assert rvs.strip_range is None


def test_categoryless_block_respects_block_expansion_override():
    from cc_dump.tui.rendering import _resolve_visibility

    block = ErrorBlock(code=500, reason="boom")
    vo = ViewOverrides()
    vo.get_block(block.block_id).expanded = False

    vis = _resolve_visibility(block, {}, overrides=vo)

    assert vis.visible is True
    assert vis.full is True
    assert vis.expanded is False


def test_search_reveal_block_forces_expanded_visibility():
    from cc_dump.tui.rendering import _resolve_visibility

    block = TextContentBlock(content="hidden", category=Category.ASSISTANT)
    filters = {"assistant": VisState(False, False, False)}
    vo = ViewOverrides()
    vo.set_search_reveal(block_id=block.block_id)

    vis = _resolve_visibility(block, filters, overrides=vo)

    assert vis.visible is True
    assert vis.full is True
    assert vis.expanded is True


def test_search_reveal_tracks_all_reveal_block_ids():
    vo = ViewOverrides()
    vo.set_search_reveal(block_id=22, block_ids={11, 22, 33})

    assert vo.has_search_reveal_block(11) is True
    assert vo.has_search_reveal_block(22) is True
    assert vo.has_search_reveal_block(33) is True


def test_search_reveal_state_is_not_serialized():
    vo = ViewOverrides()
    vo.set_search_reveal(block_id=123, region_index=4)

    data = vo.to_dict()
    restored = ViewOverrides.from_dict(data)

    assert vo.has_search_reveal_block(123) is True
    assert restored.has_search_reveal_block(123) is False
    assert restored.has_search_reveal_region(123, 4) is False


def test_search_reveal_region_forces_region_expanded():
    from rich.console import Console
    from cc_dump.tui.rendering import render_turn_to_strips

    _setup_theme()
    block = TextContentBlock(
        content="intro\n<thinking>\nline1\nline2\n</thinking>\noutro",
        category=Category.ASSISTANT,
    )
    populate_content_regions(block)
    xml_idx = next(i for i, r in enumerate(block.content_regions) if r.kind == "xml_block")

    vo = ViewOverrides()
    vo.get_region(block.block_id, xml_idx).expanded = False
    filters = {"assistant": ALWAYS_VISIBLE}
    console = Console()
    strips_collapsed, _, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
        overrides=vo,
    )

    vo.set_search_reveal(block_id=block.block_id, region_index=xml_idx)
    strips_revealed, _, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
        overrides=vo,
    )

    assert len(strips_revealed) > len(strips_collapsed)


def test_search_highlight_applies_for_region_rendering_path():
    from rich.console import Console
    from cc_dump.tui.rendering import get_theme_colors, render_turn_to_strips

    _setup_theme()
    block = TextContentBlock(
        content="intro\n<thinking>\nneedle value\n</thinking>\noutro",
        category=Category.ASSISTANT,
    )
    populate_content_regions(block)
    assert block.content_regions

    pattern = compile_search_pattern("needle", SearchMode.CASE_INSENSITIVE)
    assert pattern is not None
    turn = SimpleNamespace(is_streaming=False, blocks=[block])
    matches = find_all_matches([turn], pattern)
    assert matches

    search_ctx = SearchContext(
        pattern=pattern,
        pattern_str="needle",
        current_match=matches[0],
        all_matches=matches,
    )

    strips, _, _ = render_turn_to_strips(
        blocks=[block],
        filters={"assistant": ALWAYS_VISIBLE},
        console=Console(),
        width=80,
        search_ctx=search_ctx,
        turn_index=0,
    )

    target_bg = Color.parse(get_theme_colors().search_all_bg).triplet

    def _has_search_bg() -> bool:
        for strip in strips:
            for seg in strip:
                style = getattr(seg, "style", None)
                if style is None or style.bgcolor is None:
                    continue
                if style.bgcolor.triplet == target_bg:
                    return True
        return False

    assert _has_search_bg() is True
