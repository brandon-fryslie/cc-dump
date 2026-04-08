"""Unit tests for Sprint 1 widget architecture.

Tests the new widget architecture components:
- BLOCK_CATEGORY completeness
- render_turn_to_strips output
- TurnData.re_render skip logic
- ConversationView._find_turn_for_line binary search
- Saved scroll anchor determinism across filter hide/show cycles
"""

import contextlib
from unittest.mock import patch, PropertyMock, MagicMock
from rich.console import Console
from rich.style import Style
from textual.geometry import Offset
from textual.strip import Strip

import cc_dump.tui.rendering
from cc_dump.core.formatting import (
    SeparatorBlock,
    HeaderBlock,
    MetadataBlock,
    SystemSection,
    TextContentBlock,
    ToolUseBlock,
    TextDeltaBlock,
    Category,
    HIDDEN,
    ALWAYS_VISIBLE,
)
from cc_dump.tui.rendering import BLOCK_RENDERERS, BLOCK_CATEGORY, render_turn_to_strips
from cc_dump.tui.widget_factory import (
    TurnData,
    ConversationView,
    FollowState,
    ScrollAnchor,
    _next_strip_version,
)


class TestBlockCategoryCompleteness:
    """Test that BLOCK_CATEGORY covers all block types from BLOCK_RENDERERS."""

    def test_all_renderer_types_have_filter_keys(self):
        """Every block type in BLOCK_RENDERERS must have an entry in BLOCK_CATEGORY."""
        renderer_types = set(BLOCK_RENDERERS.keys())
        filter_key_types = set(BLOCK_CATEGORY.keys())

        assert renderer_types == filter_key_types, (
            f"BLOCK_CATEGORY missing types: {renderer_types - filter_key_types}\n"
            f"BLOCK_CATEGORY extra types: {filter_key_types - renderer_types}"
        )

    def test_filter_key_count_matches_block_count(self):
        """BLOCK_CATEGORY should have 19+ entries (18+ block types)."""
        # Verify we have all expected block types
        assert len(BLOCK_CATEGORY) >= 19, (
            f"Expected at least 19 block types in BLOCK_CATEGORY, got {len(BLOCK_CATEGORY)}"
        )

    def test_filter_key_mappings_are_correct(self):
        """Verify key filter mappings match renderer behavior.

        BLOCK_CATEGORY uses class name strings as keys (for hot-reload safety).
        """
        # Blocks that check specific filters
        assert BLOCK_CATEGORY["SeparatorBlock"] == Category.METADATA
        assert BLOCK_CATEGORY["HeaderBlock"] == Category.METADATA
        assert BLOCK_CATEGORY["HttpHeadersBlock"] == Category.METADATA
        assert BLOCK_CATEGORY["MetadataBlock"] == Category.METADATA
        assert BLOCK_CATEGORY["TurnBudgetBlock"] == Category.METADATA
        assert BLOCK_CATEGORY["SystemSection"] == Category.SYSTEM
        assert BLOCK_CATEGORY["ToolUseBlock"] == Category.TOOLS
        assert BLOCK_CATEGORY["ToolResultBlock"] == Category.TOOLS
        assert BLOCK_CATEGORY["ToolUseSummaryBlock"] == Category.TOOLS
        assert BLOCK_CATEGORY["StreamInfoBlock"] == Category.METADATA
        assert BLOCK_CATEGORY["StreamToolUseBlock"] == Category.TOOLS
        assert BLOCK_CATEGORY["StopReasonBlock"] == Category.METADATA

        # Context-dependent blocks (use block.category field)
        assert BLOCK_CATEGORY["MessageBlock"] is None
        assert BLOCK_CATEGORY["TextContentBlock"] is None
        assert BLOCK_CATEGORY["TextDeltaBlock"] is None
        assert BLOCK_CATEGORY["ImageBlock"] is None

        # Always visible blocks (no category)
        assert BLOCK_CATEGORY["ErrorBlock"] is None
        assert BLOCK_CATEGORY["ProxyErrorBlock"] is None
        assert BLOCK_CATEGORY["NewlineBlock"] is None
        assert BLOCK_CATEGORY["UnknownTypeBlock"] is None


class TestRenderTurnToStrips:
    """Test render_turn_to_strips rendering pipeline."""

    def test_empty_block_list_returns_empty_strips(self):
        """Empty block list should return empty strip list."""
        console = Console()
        filters = {}
        blocks = []

        strips, block_map, _ = render_turn_to_strips(blocks, filters, console, width=80)

        assert strips == []
        assert block_map == {}

    def test_filtered_out_blocks_return_fewer_strips(self):
        """Blocks at EXISTENCE level are fully hidden (0 lines)."""
        console = Console()
        filters = {"metadata": HIDDEN}  # Fully hidden
        blocks = [
            SeparatorBlock(style="light"),
            HeaderBlock(header_type="request", label="REQUEST 1", timestamp="12:00:00"),
        ]

        strips, block_map, _ = render_turn_to_strips(blocks, filters, console, width=80)

        # At EXISTENCE with default expanded=False, blocks are fully hidden
        assert len(strips) == 0
        assert block_map == {}

    def test_basic_rendering_produces_strips(self):
        """Basic text content should produce strips."""
        console = Console()
        filters = {}
        blocks = [
            TextContentBlock(content="Hello, world!", indent=""),
        ]

        strips, block_map, _ = render_turn_to_strips(blocks, filters, console, width=80)

        # Should produce at least one strip
        assert len(strips) > 0
        assert all(isinstance(strip, Strip) for strip in strips)
        # Block map should map block 0 to strip 0
        assert block_map == {0: 0}

    def test_multiline_text_produces_multiple_strips(self):
        """Multi-line text should produce multiple strips."""
        console = Console()
        filters = {}
        blocks = [
            TextContentBlock(content="Line 1\nLine 2\nLine 3", indent=""),
        ]

        strips, block_map, _ = render_turn_to_strips(blocks, filters, console, width=80)

        # Should produce 3 strips (one per line)
        assert len(strips) == 3
        assert block_map == {0: 0}

    def test_mixed_filtered_and_visible_blocks(self):
        """Mix of filtered and visible blocks should only render visible ones."""
        console = Console()
        filters = {"metadata": HIDDEN, "tools": ALWAYS_VISIBLE}
        blocks = [
            HeaderBlock(header_type="request", label="REQUEST 1", timestamp="12:00:00"),  # hidden at EXISTENCE
            TextContentBlock(content="User message", indent=""),  # visible
            ToolUseBlock(name="read_file", input_size=100, msg_color_idx=0),  # visible
        ]

        strips, block_map, flat_blocks = render_turn_to_strips(blocks, filters, console, width=80)

        # Header is hidden at EXISTENCE level, so 2 strips (text + tool)
        assert len(strips) == 2
        # Sequential keys: 0 and 1 for the two visible blocks
        assert len(block_map) == 2
        assert 0 in block_map  # first visible block (text)
        assert 1 in block_map  # second visible block (tool)
        # flat_blocks corresponds to block_map keys
        assert len(flat_blocks) == 2


class TestTurnDataReRender:
    """Test TurnData.re_render skip logic."""

    def test_compute_relevant_keys_finds_filter_dependencies(self):
        """compute_relevant_keys should identify which filters affect this turn."""
        blocks = [
            TextContentBlock(content="Hello", indent=""),
            ToolUseBlock(name="test", input_size=10, msg_color_idx=0),
            MetadataBlock(model="claude-3", max_tokens=100, stream=True, tool_count=0),
        ]
        td = TurnData(turn_index=0, blocks=blocks, strips=[])
        td.compute_relevant_keys()

        # Should find "tools" and "metadata" but not "system"
        assert "tools" in td.relevant_filter_keys
        assert "metadata" in td.relevant_filter_keys
        assert "system" not in td.relevant_filter_keys

    def test_re_render_skips_when_irrelevant_filter_changes(self):
        """re_render should skip when changed filter is not relevant."""
        blocks = [
            TextContentBlock(content="Hello", indent=""),
        ]
        console = Console()
        filters1 = {"metadata": HIDDEN, "tools": HIDDEN}

        td = TurnData(
            turn_index=0,
            blocks=blocks,
            strips=render_turn_to_strips(blocks, filters1, console, width=80)[0],
        )
        td.compute_relevant_keys()
        # Initial render
        td.re_render(filters1, console, 80)

        # Change a filter that doesn't affect this turn
        filters2 = {"metadata": ALWAYS_VISIBLE, "tools": HIDDEN}  # metadata changed, but no metadata blocks in this turn
        result = td.re_render(filters2, console, 80)

        # Should skip re-render (return False)
        assert result is False

    def test_re_render_executes_when_relevant_filter_changes(self):
        """re_render should execute when a relevant filter changes."""
        blocks = [
            TextContentBlock(content="Hello", indent=""),
            ToolUseBlock(name="test", input_size=10, msg_color_idx=0),
        ]
        console = Console()
        filters1 = {"tools": HIDDEN}

        td = TurnData(
            turn_index=0,
            blocks=blocks,
            strips=render_turn_to_strips(blocks, filters1, console, width=80)[0],
        )
        td.compute_relevant_keys()
        # Initial render
        td.re_render(filters1, console, 80)

        # Change a filter that affects this turn
        filters2 = {"tools": ALWAYS_VISIBLE}  # tools changed, and we have ToolUseBlock
        result = td.re_render(filters2, console, 80)

        # Should execute re-render (return True)
        assert result is True

    def test_re_render_updates_strips(self):
        """re_render should update strips when executed."""
        blocks = [
            ToolUseBlock(name="test", input_size=10, msg_color_idx=0),
        ]
        console = Console()
        filters1 = {"tools": HIDDEN}

        td = TurnData(
            turn_index=0,
            blocks=blocks,
            strips=render_turn_to_strips(blocks, filters1, console, width=80)[0],
        )
        td.compute_relevant_keys()
        td.re_render(filters1, console, 80)

        # Tools at EXISTENCE are fully hidden (0 lines)
        assert len(td.strips) == 0

        # Enable tools filter
        filters2 = {"tools": ALWAYS_VISIBLE}
        td.re_render(filters2, console, 80)

        # Should now have strips for the individual tool block
        assert len(td.strips) > 0

    def test_re_render_force_always_updates_version(self):
        """Forced rerender always assigns new strip version (no-op detection is upstream)."""
        blocks = [TextContentBlock(content="Hello", indent="")]
        console = Console()
        filters = {}
        strips, block_strip_map, flat_blocks = render_turn_to_strips(
            blocks, filters, console, width=80
        )

        td = TurnData(
            turn_index=0,
            blocks=blocks,
            strips=strips,
            block_strip_map=block_strip_map,
            _flat_blocks=flat_blocks,
        )
        td._strip_version = _next_strip_version()
        td.compute_relevant_keys()
        old_version = td._strip_version

        result = td.re_render(filters, console, 80, force=True)

        assert result is True
        assert td._strip_version > old_version

    def test_re_render_skips_when_render_key_unchanged(self):
        """Search-active rerender should skip when render key and filters are unchanged."""
        from cc_dump.tui.search import SearchContext, SearchMode, compile_search_pattern

        blocks = [TextContentBlock(content="Hello", indent="")]
        console = Console()
        filters = {}
        pattern = compile_search_pattern("hello", SearchMode.CASE_INSENSITIVE)
        assert pattern is not None
        search_ctx = SearchContext(
            pattern=pattern,
            pattern_str="hello",
            current_match=None,
            all_matches=[],
        )

        td = TurnData(turn_index=0, blocks=blocks, strips=[])
        td.compute_relevant_keys()

        with patch("cc_dump.tui.rendering.render_turn_to_strips") as render_mock:
            render_mock.return_value = ([Strip.blank(80)], {}, blocks)
            first = td.re_render(
                filters,
                console,
                80,
                search_ctx=search_ctx,
                render_key=(80, 1, 1, 1),
            )
            second = td.re_render(
                filters,
                console,
                80,
                search_ctx=search_ctx,
                render_key=(80, 1, 1, 1),
            )

        assert first is True
        assert second is False
        assert render_mock.call_count == 1


class TestConversationViewBinarySearch:
    """Test ConversationView._find_turn_for_line binary search correctness.

    These are unit tests that directly test the binary search algorithm
    without requiring a full Textual app context.
    """

    def test_find_turn_for_line_empty_list(self):
        """Binary search on empty turns list should return None."""
        conv = ConversationView()
        result = conv._find_turn_for_line(0)
        assert result is None

    def test_find_turn_for_line_single_turn_creates_turn_data(self):
        """Test with a single TurnData directly without app."""
        from textual.strip import Strip

        conv = ConversationView()

        # Manually create and add TurnData
        td = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(content="Hello", indent="")],
            strips=[Strip.blank(80), Strip.blank(80)],  # 2 lines
        )
        conv._turns.append(td)
        conv._recalculate_offsets()

        # Should find the turn for any line within its range
        turn = conv._find_turn_for_line(0)
        assert turn is not None
        assert turn.turn_index == 0

        turn = conv._find_turn_for_line(1)
        assert turn is not None
        assert turn.turn_index == 0

    def test_find_turn_for_line_multiple_turns_manual(self):
        """Binary search with multiple turns should find correct turn."""
        from textual.strip import Strip

        conv = ConversationView()

        # Create multiple turns with known line counts
        # Turn 0: 3 lines (line 0-2)
        td0 = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(content="A\nB\nC", indent="")],
            strips=[Strip.blank(80), Strip.blank(80), Strip.blank(80)],
        )

        # Turn 1: 2 lines (line 3-4)
        td1 = TurnData(
            turn_index=1,
            blocks=[TextContentBlock(content="D\nE", indent="")],
            strips=[Strip.blank(80), Strip.blank(80)],
        )

        # Turn 2: 1 line (line 5)
        td2 = TurnData(
            turn_index=2,
            blocks=[TextContentBlock(content="F", indent="")],
            strips=[Strip.blank(80)],
        )

        conv._turns.extend([td0, td1, td2])
        conv._recalculate_offsets()

        # Test finding each turn
        turn0 = conv._find_turn_for_line(0)
        assert turn0 is not None
        assert turn0.turn_index == 0

        turn1 = conv._find_turn_for_line(3)
        assert turn1 is not None
        assert turn1.turn_index == 1

        turn2 = conv._find_turn_for_line(5)
        assert turn2 is not None
        assert turn2.turn_index == 2

    def test_find_turn_for_line_beyond_range(self):
        """Binary search beyond last line should return None."""
        from textual.strip import Strip

        conv = ConversationView()

        # Create a turn with 2 lines
        td = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(content="Line 1\nLine 2", indent="")],
            strips=[Strip.blank(80), Strip.blank(80)],
        )
        conv._turns.append(td)
        conv._recalculate_offsets()

        # Line 0-1 are valid, line 10 is beyond
        turn = conv._find_turn_for_line(10)
        assert turn is None

    def test_find_turn_for_line_boundary_conditions(self):
        """Test boundary conditions at turn edges."""
        from textual.strip import Strip

        conv = ConversationView()

        # Turn 0: lines 0-2 (3 lines)
        td0 = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(content="A\nB\nC", indent="")],
            strips=[Strip.blank(80), Strip.blank(80), Strip.blank(80)],
        )

        # Turn 1: lines 3-5 (3 lines)
        td1 = TurnData(
            turn_index=1,
            blocks=[TextContentBlock(content="D\nE\nF", indent="")],
            strips=[Strip.blank(80), Strip.blank(80), Strip.blank(80)],
        )

        conv._turns.extend([td0, td1])
        conv._recalculate_offsets()

        # Test first line of each turn
        assert conv._find_turn_for_line(0).turn_index == 0
        assert conv._find_turn_for_line(3).turn_index == 1

        # Test last line of each turn
        assert conv._find_turn_for_line(2).turn_index == 0
        assert conv._find_turn_for_line(5).turn_index == 1


class TestScrollPreservation:
    """Test turn-level scroll preservation across filter toggles.

    The anchor is (turn_index, offset_within_turn) — stateless, filter-agnostic.
    No cross-toggle state accumulation. Each rerender() captures, re-renders, restores.
    """

    def _make_conv(self, console: Console, turns_blocks: list[list], filters: dict) -> ConversationView:
        """Create a ConversationView with multiple turns, mocking Textual internals."""
        conv = ConversationView()

        for i, blocks in enumerate(turns_blocks):
            strips, block_strip_map, _ = render_turn_to_strips(blocks, filters, console, width=80)
            td = TurnData(
                turn_index=i,
                blocks=blocks,
                strips=strips,
                block_strip_map=block_strip_map,
            )
            td._widest_strip = max((s.cell_length for s in strips), default=0)
            td.compute_relevant_keys()
            td._last_filter_snapshot = {k: filters.get(k, ALWAYS_VISIBLE) for k in td.relevant_filter_keys}
            conv._turns.append(td)

        conv._recalculate_offsets()
        conv._last_filters = dict(filters)
        conv._last_width = 80
        return conv

    @contextlib.contextmanager
    def _patch_scroll(self, conv, scroll_y=0, height=50):
        """Mock scroll infrastructure on ConversationView."""
        region_mock = MagicMock()
        region_mock.width = 80
        region_mock.height = height
        app_mock = MagicMock(console=Console())
        cls = type(conv)

        conv.scroll_to = MagicMock()
        with patch.object(cls, 'scroll_offset', new_callable=PropertyMock, return_value=Offset(0, scroll_y)), \
             patch.object(cls, 'scrollable_content_region', new_callable=PropertyMock, return_value=region_mock), \
             patch.object(cls, 'app', new_callable=PropertyMock, return_value=app_mock), \
             patch.object(cls, 'size', new_callable=PropertyMock, return_value=MagicMock(width=80)):
            yield

    def test_filter_toggle_preserves_viewport_turn(self):
        """Toggling a filter should keep the same turn at the viewport top."""
        console = Console()
        turns_blocks = [
            [TextContentBlock(content="Turn 0 text", indent="")],
            [
                TextContentBlock(content="Turn 1 text\nLine 2\nLine 3", indent=""),
                ToolUseBlock(name="test", input_size=10, msg_color_idx=0),
            ],
            [TextContentBlock(content="Turn 2 text", indent="")],
        ]
        filters = {"tools": ALWAYS_VISIBLE}
        conv = self._make_conv(console, turns_blocks, filters)
        conv._follow_state = FollowState.OFF

        # Scroll to turn 1 with some offset
        turn1_offset = conv._offset_tree.prefix_sum(1)
        scroll_y = turn1_offset + 1  # 1 line into turn 1

        with self._patch_scroll(conv, scroll_y=scroll_y):
            conv._scroll_anchor = conv._compute_anchor_from_scroll()
            conv.rerender({"tools": HIDDEN})

        # scroll_to should be called with turn 1's new offset + clamped offset_within
        turn1_after = conv._turns[1]
        turn1_after_offset = conv._offset_tree.prefix_sum(1)
        expected_offset = min(1, turn1_after.line_count - 1)
        expected_y = turn1_after_offset + expected_offset
        conv.scroll_to.assert_called_with(y=expected_y, animate=False)

    def test_no_cross_toggle_state(self):
        """Toggle A then B: B should not jump to A's pre-toggle position."""
        from cc_dump.tui.rendering import set_theme
        from textual.theme import BUILTIN_THEMES

        # Initialize theme for SystemSection rendering
        set_theme(BUILTIN_THEMES["textual-dark"])

        console = Console()
        turns_blocks = [
            [TextContentBlock(content="Turn 0", indent="")],
            [
                SystemSection(children=[]),
                TextContentBlock(content="System", category=Category.SYSTEM),
            ],
            [
                TextContentBlock(content="Turn 2 text\nLine 2", indent=""),
                ToolUseBlock(name="test", input_size=10, msg_color_idx=0),
            ],
            [TextContentBlock(content="Turn 3", indent="")],
        ]
        filters = {"system": ALWAYS_VISIBLE, "tools": ALWAYS_VISIBLE}
        conv = self._make_conv(console, turns_blocks, filters)
        conv._follow_state = FollowState.OFF

        # Step 1: Scroll to turn 1 (system block area), hide system
        with self._patch_scroll(conv, scroll_y=conv._offset_tree.prefix_sum(1)):
            conv._scroll_anchor = conv._compute_anchor_from_scroll()
            conv.rerender({"system": HIDDEN, "tools": ALWAYS_VISIBLE})

        # Step 2: Scroll to turn 2, then toggle tools
        with self._patch_scroll(conv, scroll_y=conv._offset_tree.prefix_sum(2)):
            conv.scroll_to.reset_mock()
            conv._scroll_anchor = conv._compute_anchor_from_scroll()
            conv.rerender({"system": HIDDEN, "tools": HIDDEN})

        # scroll_to should restore to turn 2's area, NOT turn 1
        assert conv.scroll_to.called
        call_y = conv.scroll_to.call_args.kwargs.get("y", conv.scroll_to.call_args[1].get("y"))
        turn2_after = conv._turns[2]
        # Should be at or near turn 2's offset
        turn2_after_offset = conv._offset_tree.prefix_sum(2)
        assert call_y >= turn2_after_offset
        assert call_y < turn2_after_offset + turn2_after.line_count

    def test_follow_mode_skips_anchor(self):
        """In follow mode, scroll_to should not be called by rerender."""
        console = Console()
        turns_blocks = [
            [TextContentBlock(content="Turn 0", indent=""),
             ToolUseBlock(name="test", input_size=10, msg_color_idx=0)],
        ]
        filters = {"tools": ALWAYS_VISIBLE}
        conv = self._make_conv(console, turns_blocks, filters)
        conv._follow_state = FollowState.ACTIVE

        with self._patch_scroll(conv, scroll_y=0):
            conv.rerender({"tools": HIDDEN})

        conv.scroll_to.assert_not_called()

    def test_clamped_offset_when_turn_shrinks(self):
        """When a turn shrinks, offset_within is clamped to new line count."""
        console = Console()
        # Turn with many lines when tools are shown
        turns_blocks = [
            [
                TextContentBlock(content="Line 0\nLine 1\nLine 2", indent=""),
                ToolUseBlock(name="tool1", input_size=10, msg_color_idx=0),
                ToolUseBlock(name="tool2", input_size=20, msg_color_idx=1),
                ToolUseBlock(name="tool3", input_size=30, msg_color_idx=2),
            ],
        ]
        filters = {"tools": ALWAYS_VISIBLE}
        conv = self._make_conv(console, turns_blocks, filters)
        conv._follow_state = FollowState.OFF

        turn = conv._turns[0]
        original_lines = turn.line_count
        # Scroll deep into the turn
        deep_offset = original_lines - 1
        scroll_y = conv._offset_tree.prefix_sum(0) + deep_offset

        with self._patch_scroll(conv, scroll_y=scroll_y):
            conv._scroll_anchor = conv._compute_anchor_from_scroll()
            conv.rerender({"tools": HIDDEN})

        # Turn should have fewer lines now
        turn_after = conv._turns[0]
        assert turn_after.line_count < original_lines
        # scroll_to should clamp to turn's last line
        expected_y = conv._offset_tree.prefix_sum(0) + turn_after.line_count - 1
        conv.scroll_to.assert_called_with(y=expected_y, animate=False)

    def test_deferred_anchor_resolve_preserves_scroll(self):
        """Deferred anchor resolve should restore scroll position."""
        console = Console()
        turns_blocks = [
            [TextContentBlock(content="Turn 0\nLine 2", indent="")],
            [TextContentBlock(content="Turn 1\nLine 2", indent="")],
        ]
        filters = {}
        conv = self._make_conv(console, turns_blocks, filters)
        conv._follow_state = FollowState.OFF

        # Scroll to turn 1
        turn1_offset = conv._offset_tree.prefix_sum(1)
        with self._patch_scroll(conv, scroll_y=turn1_offset):
            conv._scroll_anchor = conv._compute_anchor_from_scroll()
            conv._flush_deferred_anchor_resolve()

        # Should restore to turn 1
        conv.scroll_to.assert_called()
        call_y = conv.scroll_to.call_args.kwargs.get("y", conv.scroll_to.call_args[1].get("y"))
        assert call_y >= conv._offset_tree.prefix_sum(1)

    def test_anchor_turn_shrinks_but_visible(self):
        """When anchor turn shrinks but remains visible, scroll adjusts."""
        from cc_dump.tui.rendering import set_theme
        from textual.theme import BUILTIN_THEMES

        # Initialize theme for SystemSection rendering
        set_theme(BUILTIN_THEMES["textual-dark"])

        console = Console()
        # Turn 0: always visible text
        # Turn 1: system blocks (will be hidden at EXISTENCE level)
        # Turn 2: always visible text
        turns_blocks = [
            [TextContentBlock(content="Turn 0 visible", indent="")],
            [SystemSection(children=[]),
             TextContentBlock(content="System only", category=Category.SYSTEM)],
            [TextContentBlock(content="Turn 2 visible", indent="")],
        ]
        filters = {"system": ALWAYS_VISIBLE}
        conv = self._make_conv(console, turns_blocks, filters)
        conv._follow_state = FollowState.OFF

        # Scroll to turn 1 (system content)
        with self._patch_scroll(conv, scroll_y=conv._offset_tree.prefix_sum(1)):
            conv._scroll_anchor = conv._compute_anchor_from_scroll()
            conv.rerender({"system": HIDDEN})

        # Turn 1 is now fully hidden at EXISTENCE level (0 lines)
        assert conv._turns[1].line_count == 0
        assert conv.scroll_to.called

    def test_out_of_range_anchor_resolves_to_last_visible_turn(self):
        """Stale anchors beyond turn count should resolve to the last visible turn."""
        conv = ConversationView()
        conv._turns.extend(
            [
                TurnData(turn_index=0, blocks=[], strips=[Strip.blank(80)]),
                TurnData(turn_index=1, blocks=[], strips=[Strip.blank(80)]),
                TurnData(turn_index=2, blocks=[], strips=[]),
                TurnData(turn_index=3, blocks=[], strips=[]),
            ]
        )
        conv._recalculate_offsets()
        conv._scroll_anchor = ScrollAnchor(turn_index=999, line_in_turn=0)
        conv.scroll_to = MagicMock()

        conv._resolve_anchor()

        conv.scroll_to.assert_called_with(
            y=conv._offset_tree.prefix_sum(1),
            animate=False,
        )


class TestWidestStripCache:
    """Test _widest_strip caching on TurnData."""

    def test_widest_strip_set_after_re_render(self):
        """_widest_strip matches actual max strip cell_length after re_render."""
        from rich.console import Console
        blocks = [TextContentBlock(content="Short\nA much longer line of text here", indent="")]
        console = Console()
        filters = {}
        td = TurnData(turn_index=0, blocks=blocks, strips=[])
        td.compute_relevant_keys()
        td.re_render(filters, console, 80, force=True)

        expected = max(s.cell_length for s in td.strips) if td.strips else 0
        assert td._widest_strip == expected
        assert td._widest_strip > 0

    def test_widest_strip_nonzero_for_existence_level(self):
        """_widest_strip is zero when blocks are hidden at EXISTENCE level."""
        from rich.console import Console
        blocks = [SystemSection(children=[])]
        console = Console()
        td = TurnData(turn_index=0, blocks=blocks, strips=[])
        td.compute_relevant_keys()
        # System blocks at EXISTENCE with default expanded=False are fully hidden (0 lines)
        td.re_render({"system": HIDDEN}, console, 80, force=True)
        # Should have no strips (fully hidden)
        assert len(td.strips) == 0
        assert td._widest_strip == 0


class TestIncrementalOffsets:
    """Test _recalculate_offsets_from correctness."""

    def test_invalidate_cache_for_turn_range_only_removes_affected_turns(self):
        """Range invalidation preserves unaffected turn cache entries."""
        from textual.strip import Strip

        conv = ConversationView()
        conv._turns = [TurnData(turn_index=i, blocks=[], strips=[]) for i in range(4)]

        key0 = ("k", 0)
        key1 = ("k", 1)
        key2 = ("k", 2)
        key3 = ("k", 3)
        conv._line_cache[key0] = Strip.blank(10)
        conv._line_cache[key1] = Strip.blank(10)
        conv._line_cache[key2] = Strip.blank(10)
        conv._line_cache[key3] = Strip.blank(10)
        conv._cache_keys_by_turn = {
            0: {key0},
            1: {key1},
            2: {key2},
            3: {key3},
        }

        conv._invalidate_cache_for_turns(2, 4)

        assert key0 in conv._line_cache
        assert key1 in conv._line_cache
        assert key2 not in conv._line_cache
        assert key3 not in conv._line_cache
        assert 0 in conv._cache_keys_by_turn
        assert 1 in conv._cache_keys_by_turn
        assert 2 not in conv._cache_keys_by_turn
        assert 3 not in conv._cache_keys_by_turn

    def test_tree_offsets_match_after_strip_change(self):
        """After modifying a turn's strips and rebuilding, tree offsets are correct."""
        from textual.strip import Strip

        conv = ConversationView()
        # Build 5 turns with known strip counts: 2, 4, 6, 8, 10
        for i in range(5):
            strip_count = (i + 1) * 2
            td = TurnData(
                turn_index=i,
                blocks=[],
                strips=[Strip.blank(80 + i * 10)] * strip_count,
                _widest_strip=80 + i * 10,
            )
            conv._turns.append(td)

        conv._recalculate_offsets()
        # Baseline: offsets should be cumulative strip counts
        assert conv._offset_tree.prefix_sum(0) == 0
        assert conv._offset_tree.prefix_sum(1) == 2
        assert conv._offset_tree.prefix_sum(2) == 6
        assert conv._offset_tree.prefix_sum(3) == 12
        assert conv._offset_tree.prefix_sum(4) == 20

        # Modify turn 2 (change strip count from 6 to 3)
        conv._turns[2].strips = [Strip.blank(90)] * 3
        conv._turns[2]._widest_strip = 90

        # Rebuild offsets
        conv._recalculate_offsets()

        # Turns 0-1 offsets unchanged, 2+ shifted
        assert conv._offset_tree.prefix_sum(0) == 0
        assert conv._offset_tree.prefix_sum(1) == 2
        assert conv._offset_tree.prefix_sum(2) == 6
        assert conv._offset_tree.prefix_sum(3) == 9   # was 12, now 6+3=9
        assert conv._offset_tree.prefix_sum(4) == 17  # 9+8=17

    def test_recalculate_offsets_invalidates_all_caches(self):
        """Full offset recalculation invalidates all cache keys."""
        from textual.strip import Strip

        conv = ConversationView()
        conv._turns = [TurnData(turn_index=i, blocks=[], strips=[Strip.blank(80)]) for i in range(4)]
        conv._recalculate_offsets()

        key0 = ("line", 0)
        key1 = ("line", 1)
        key2 = ("line", 2)
        key3 = ("line", 3)
        conv._line_cache[key0] = Strip.blank(10)
        conv._line_cache[key1] = Strip.blank(10)
        conv._line_cache[key2] = Strip.blank(10)
        conv._line_cache[key3] = Strip.blank(10)
        conv._cache_keys_by_turn = {
            0: {key0},
            1: {key1},
            2: {key2},
            3: {key3},
        }

        conv._turns[2].strips = [Strip.blank(80)] * 3
        conv._recalculate_offsets()

        # Full rebuild invalidates all caches
        assert key0 not in conv._line_cache
        assert key1 not in conv._line_cache
        assert key2 not in conv._line_cache
        assert key3 not in conv._line_cache

    def test_prune_line_cache_index_removes_stale_keys(self):
        """Stale turn-key index entries are pruned against live LRU keys."""
        conv = ConversationView()
        live_key = ("live", 0)
        stale_key = ("stale", 0)

        conv._line_cache[live_key] = Strip.blank(10)
        conv._cache_keys_by_turn = {
            0: {live_key, stale_key},
            1: {stale_key},
        }

        conv._prune_line_cache_index()

        assert conv._cache_keys_by_turn == {0: {live_key}}

    def test_clear_line_cache_clears_index(self):
        """Clearing line cache also clears turn-key index and write counter."""
        conv = ConversationView()
        key = ("line", 0)
        conv._line_cache[key] = Strip.blank(10)
        conv._cache_keys_by_turn = {0: {key}}
        conv._line_cache_index_write_count = 17

        conv._clear_line_cache()

        assert len(conv._line_cache) == 0
        assert conv._cache_keys_by_turn == {}
        assert conv._line_cache_index_write_count == 0

    def test_line_cache_index_prune_bounds_metadata_under_large_churn(self):
        """Pruning keeps index metadata bounded to live LRU keyset size."""
        conv = ConversationView()

        # Simulate high-cardinality key churn across many turns.
        for i in range(5000):
            key = ("k", i)
            conv._line_cache[key] = Strip.blank(10)
            conv._cache_keys_by_turn[i] = {key}

        # After pruning, index should only reference keys still present in LRU.
        conv._prune_line_cache_index()
        indexed_key_count = sum(len(keys) for keys in conv._cache_keys_by_turn.values())

        assert len(conv._line_cache) <= conv._line_cache.maxsize
        assert indexed_key_count <= len(conv._line_cache)

    def test_on_turns_pruned_reindexes_turns_and_adjusts_anchor(self):
        """Pruning oldest turns keeps turn indices and anchor coherent."""
        conv = ConversationView()
        conv._follow_state = FollowState.OFF

        for i in range(4):
            conv._turns.append(
                TurnData(turn_index=i, blocks=[], strips=[Strip.blank(80)])
            )
        conv._recalculate_offsets()
        conv._scroll_anchor = ScrollAnchor(turn_index=3, line_in_turn=0)

        cls = type(conv)
        with patch.object(cls, 'is_attached', new_callable=PropertyMock, return_value=True), \
             patch.object(conv, '_resolve_anchor'), \
             patch.object(conv, 'refresh'):
            conv._on_turns_pruned(2)

        assert len(conv._turns) == 2
        assert [td.turn_index for td in conv._turns] == [0, 1]
        assert conv._scroll_anchor is not None
        assert conv._scroll_anchor.turn_index == 1

    def test_recalculate_offsets_from_delegates_to_full_rebuild(self):
        """_recalculate_offsets_from() delegates to _recalculate_offsets()."""
        from textual.strip import Strip

        conv = ConversationView()
        for i in range(3):
            td = TurnData(
                turn_index=i,
                blocks=[],
                strips=[Strip.blank(80)] * (i + 1),
                _widest_strip=80,
            )
            conv._turns.append(td)

        conv._recalculate_offsets_from(0)
        offsets_from = [conv._offset_tree.prefix_sum(i) for i in range(3)]
        total_from = conv._total_lines

        conv._recalculate_offsets()
        offsets_full = [conv._offset_tree.prefix_sum(i) for i in range(3)]
        total_full = conv._total_lines

        assert offsets_from == offsets_full
        assert total_from == total_full


class TestViewportTurnRange:
    """Test _viewport_turn_range viewport-only re-rendering."""

    def _make_many_turns(self, n: int, lines_per_turn: int = 10):
        """Create a ConversationView with n turns of known size."""
        from textual.strip import Strip

        conv = ConversationView()
        for i in range(n):
            td = TurnData(
                turn_index=i,
                blocks=[TextContentBlock(content="x", indent="")],
                strips=[Strip.blank(80)] * lines_per_turn,
                _widest_strip=80,
            )
            td.compute_relevant_keys()
            td._last_filter_snapshot = {}
            conv._turns.append(td)
        conv._recalculate_offsets()
        return conv

    @contextlib.contextmanager
    def _patch_scroll(self, conv, scroll_y=0, height=50):
        """Mock scroll infrastructure with height support."""
        region_mock = MagicMock()
        region_mock.width = 80
        region_mock.height = height
        app_mock = MagicMock(console=Console())
        cls = type(conv)

        conv.scroll_to = MagicMock()
        with patch.object(cls, 'scroll_offset', new_callable=PropertyMock, return_value=Offset(0, scroll_y)), \
             patch.object(cls, 'scrollable_content_region', new_callable=PropertyMock, return_value=region_mock), \
             patch.object(cls, 'app', new_callable=PropertyMock, return_value=app_mock):
            yield

    def test_viewport_range_at_top(self):
        """At scroll_y=0, range should cover viewport + buffer from start."""
        conv = self._make_many_turns(100, lines_per_turn=10)
        # 1000 total lines, viewport=50, buffer=200
        # Range: lines 0..250 → turns 0..25

        with self._patch_scroll(conv, scroll_y=0, height=50):
            start, end = conv._viewport_turn_range(buffer_lines=200)

        assert start == 0
        # 0 + 50 + 200 = 250 → turn at line 250 is turn 25 → end = 26
        assert end == 26

    def test_viewport_range_in_middle(self):
        """In the middle, range should extend both directions from scroll position."""
        conv = self._make_many_turns(100, lines_per_turn=10)

        with self._patch_scroll(conv, scroll_y=500, height=50):
            start, end = conv._viewport_turn_range(buffer_lines=200)

        # range_start = 500 - 200 = 300 → turn 30
        # range_end = 500 + 50 + 200 = 750 → turn 75 → end = 76
        assert start == 30
        assert end == 76

    def test_viewport_range_at_bottom(self):
        """At the bottom, range should clamp to last turn."""
        conv = self._make_many_turns(100, lines_per_turn=10)
        # total=1000, scrolled to near the end

        with self._patch_scroll(conv, scroll_y=950, height=50):
            start, end = conv._viewport_turn_range(buffer_lines=200)

        # range_start = 950 - 200 = 750 → turn 75
        assert start == 75
        # range_end = 950 + 50 + 200 = 1200 → clamped to 999 → turn 99 → end = 100
        assert end == 100

    def test_viewport_range_empty_turns(self):
        """Empty turns list returns (0, 0)."""
        conv = ConversationView()
        with self._patch_scroll(conv, scroll_y=0, height=50):
            start, end = conv._viewport_turn_range()
        assert start == 0
        assert end == 0

    def test_viewport_range_small_list_covers_all(self):
        """When all turns fit in viewport+buffer, all are included."""
        conv = self._make_many_turns(5, lines_per_turn=3)
        # 15 total lines, viewport=50, buffer=200 → covers everything

        with self._patch_scroll(conv, scroll_y=0, height=50):
            start, end = conv._viewport_turn_range(buffer_lines=200)

        assert start == 0
        assert end == 5


class TestViewportOnlyRerender:
    """Test that rerender() only processes viewport turns and defers off-viewport."""

    def _make_conv_with_turns(self, console, n_turns, filters):
        """Create ConversationView with n turns containing tool blocks."""
        conv = ConversationView()
        for i in range(n_turns):
            blocks = [
                TextContentBlock(content=f"Turn {i}", indent=""),
                ToolUseBlock(name="test", input_size=10, msg_color_idx=0),
            ]
            strips, block_strip_map, _ = render_turn_to_strips(blocks, filters, console, width=80)
            td = TurnData(
                turn_index=i,
                blocks=blocks,
                strips=strips,
                block_strip_map=block_strip_map,
                _widest_strip=max((s.cell_length for s in strips), default=0),
            )
            td.compute_relevant_keys()
            td._last_filter_snapshot = {k: filters.get(k, ALWAYS_VISIBLE) for k in td.relevant_filter_keys}
            conv._turns.append(td)
        conv._recalculate_offsets()
        conv._last_filters = dict(filters)
        conv._last_width = 80
        return conv

    @contextlib.contextmanager
    def _patch_scroll(self, conv, scroll_y=0, height=50):
        region_mock = MagicMock()
        region_mock.width = 80
        region_mock.height = height
        app_mock = MagicMock(console=Console())
        cls = type(conv)

        conv.scroll_to = MagicMock()
        with patch.object(cls, 'scroll_offset', new_callable=PropertyMock, return_value=Offset(0, scroll_y)), \
             patch.object(cls, 'scrollable_content_region', new_callable=PropertyMock, return_value=region_mock), \
             patch.object(cls, 'app', new_callable=PropertyMock, return_value=app_mock), \
             patch.object(cls, 'size', new_callable=PropertyMock, return_value=MagicMock(width=80)):
            yield

    def test_viewport_turns_get_re_rendered(self):
        """Viewport turns should be re-rendered immediately with current filter revision."""
        console = Console()
        filters_initial = {"tools": ALWAYS_VISIBLE}
        conv = self._make_conv_with_turns(console, 50, filters_initial)

        with self._patch_scroll(conv, scroll_y=0, height=10):
            vp_start, vp_end = conv._viewport_turn_range()
            conv._follow_state = FollowState.OFF
            conv.rerender({"tools": HIDDEN})

        # Viewport turns should have current filter revision
        for idx in range(vp_start, min(vp_end, len(conv._turns))):
            td = conv._turns[idx]
            assert td._filter_revision == conv._active_filter_revision, (
                f"Viewport turn {idx} should have current filter revision"
            )

    def test_filter_rerender_avoids_full_turn_scan(self):
        """Filter rerender should use bounded index ranges, not iterate the entire turn list."""
        console = Console()
        filters_initial = {"tools": ALWAYS_VISIBLE}
        conv = self._make_conv_with_turns(console, 1000, filters_initial)

        class _CountingList(list):
            def __init__(self, values):
                super().__init__(values)
                self.iter_count = 0

            def __iter__(self):
                for item in super().__iter__():
                    self.iter_count += 1
                    yield item

        conv._turns = _CountingList(conv._turns)

        with self._patch_scroll(conv, scroll_y=0, height=10):
            conv._follow_state = FollowState.OFF
            conv._turns.iter_count = 0
            conv.rerender({"tools": HIDDEN})

        assert conv._turns.iter_count == 0, "filter rerender should not iterate full turn list"


class TestLazyRerenderInRenderLine:
    """Test that render_line() lazily re-renders turns with stale _filter_revision."""

    @contextlib.contextmanager
    def _patch_scroll(self, conv, scroll_y=0, height=50):
        region_mock = MagicMock()
        region_mock.width = 80
        region_mock.height = height
        app_mock = MagicMock(console=Console())
        cls = type(conv)

        conv.scroll_to = MagicMock()
        conv.call_later = MagicMock()  # Mock call_later to prevent scheduling
        with patch.object(cls, 'scroll_offset', new_callable=PropertyMock, return_value=Offset(0, scroll_y)), \
             patch.object(cls, 'scrollable_content_region', new_callable=PropertyMock, return_value=region_mock), \
             patch.object(cls, 'app', new_callable=PropertyMock, return_value=app_mock), \
             patch.object(cls, 'rich_style', new_callable=PropertyMock, return_value=Style()), \
             patch.object(cls, 'size', new_callable=PropertyMock, return_value=MagicMock(width=80)):
            yield

    def test_lazy_rerender_updates_revision_on_scroll(self):
        """When a turn with stale _filter_revision is accessed via render_line, it re-renders."""
        console = Console()
        blocks = [
            TextContentBlock(content="Hello world", indent=""),
            ToolUseBlock(name="test", input_size=10, msg_color_idx=0),
        ]
        filters = {"tools": ALWAYS_VISIBLE}

        # Build a turn manually
        strips, block_strip_map, _ = render_turn_to_strips(blocks, filters, console, width=80)
        td = TurnData(
            turn_index=0,
            blocks=blocks,
            strips=strips,
            block_strip_map=block_strip_map,
            _widest_strip=max((s.cell_length for s in strips), default=0),
        )
        td.compute_relevant_keys()
        td._last_filter_snapshot = {"tools": ALWAYS_VISIBLE}

        conv = ConversationView()
        conv._turns.append(td)
        conv._last_filters = {"tools": HIDDEN}
        conv._last_width = 80
        conv._recalculate_offsets()

        # Simulate stale filter revision (filters changed while off-viewport)
        conv._active_filter_revision = 5
        td._filter_revision = 0  # stale

        with self._patch_scroll(conv, scroll_y=0, height=50):
            # render_line at y=0 should trigger lazy re-render
            conv.render_line(0)

        # _filter_revision should now match active
        assert td._filter_revision == conv._active_filter_revision
        # call_later should have been called to schedule offset recalc
        conv.call_later.assert_called_once()

    def test_no_lazy_rerender_when_revision_matches(self):
        """render_line should not re-render turns with current _filter_revision."""
        console = Console()
        blocks = [TextContentBlock(content="Hello", indent="")]
        filters = {}

        strips, block_strip_map, _ = render_turn_to_strips(blocks, filters, console, width=80)
        td = TurnData(
            turn_index=0,
            blocks=blocks,
            strips=strips,
            block_strip_map=block_strip_map,
            _widest_strip=max((s.cell_length for s in strips), default=0),
        )
        td.compute_relevant_keys()
        td._last_filter_snapshot = {}

        conv = ConversationView()
        conv._turns.append(td)
        conv._last_filters = {}
        conv._last_width = 80
        conv._recalculate_offsets()

        # Set matching revision — turn is up-to-date
        conv._active_filter_revision = 3
        td._filter_revision = 3

        original_strips = list(td.strips)

        with self._patch_scroll(conv, scroll_y=0, height=50):
            conv.render_line(0)

        # Strips should be unchanged (no re-render)
        assert td.strips == original_strips
        # call_later should NOT have been called
        conv.call_later.assert_not_called()

    def test_selection_render_does_not_cache_transient_line(self):
        """Selection-active renders bypass cache writes to avoid stale highlighted cache."""
        console = Console()
        blocks = [TextContentBlock(content="Hello world", indent="")]
        filters = {}

        strips, block_strip_map, _ = render_turn_to_strips(blocks, filters, console, width=80)
        td = TurnData(
            turn_index=0,
            blocks=blocks,
            strips=strips,
            block_strip_map=block_strip_map,
            _widest_strip=max((s.cell_length for s in strips), default=0),
        )
        td.compute_relevant_keys()
        td._last_filter_snapshot = {}

        conv = ConversationView()
        conv._turns.append(td)
        conv._last_filters = {}
        conv._last_width = 80
        conv._recalculate_offsets()

        selection = MagicMock()
        selection.get_span.return_value = None

        cls = type(conv)
        with self._patch_scroll(conv, scroll_y=0, height=50), \
             patch.object(cls, "text_selection", new_callable=PropertyMock, return_value=selection):
            conv.render_line(0)

        assert len(conv._line_cache) == 0

    def test_selection_updates_preserve_cached_base_lines(self):
        """Selection updates refresh the view without dropping persistent base-line cache."""
        conv = ConversationView()
        key = ("line", 0)
        conv._line_cache[key] = Strip.blank(10)
        conv._cache_keys_by_turn = {0: {key}}
        conv._line_cache_index_write_count = 17
        conv.refresh = MagicMock()

        conv.selection_updated(MagicMock())
        conv.selection_updated(None)

        assert key in conv._line_cache
        assert conv._cache_keys_by_turn == {0: {key}}
        assert conv._line_cache_index_write_count == 17
        assert conv.refresh.call_count == 2


class TestRequestScopedStreaming:
    """Request-scoped streaming turns should not interleave."""

    @contextlib.contextmanager
    def _patch_app_console(self, conv):
        app_mock = MagicMock(console=Console())
        cls = type(conv)
        with patch.object(cls, 'app', new_callable=PropertyMock, return_value=app_mock), \
             patch.object(cls, 'is_attached', new_callable=PropertyMock, return_value=True):
            yield

    def test_interleaved_requests_stay_partitioned(self):
        conv = ConversationView()
        conv._last_width = 80
        conv._last_filters = {}

        with self._patch_app_console(conv):
            conv.begin_stream("req-1")
            conv.begin_stream("req-2")

            conv.append_stream_block("req-1", TextDeltaBlock(content="hello "))
            conv.append_stream_block("req-2", TextDeltaBlock(content="world "))
            conv.append_stream_block("req-1", TextDeltaBlock(content="again"))

            # req-2 is active but not focused, so its live strips are not rendered into viewport.
            assert conv.get_focused_stream_id() == "req-1"
            assert conv._domain_store.get_delta_text("req-1") == ["hello ", "again"]
            assert conv._domain_store.get_delta_text("req-2") == ["world "]

            conv.finalize_stream("req-1")
            assert "req-1" not in conv._stream_preview_turns
            assert "req-2" in conv._stream_preview_turns

    def test_focus_switch_renders_selected_stream(self):
        conv = ConversationView()
        conv._last_width = 80
        conv._last_filters = {}

        with self._patch_app_console(conv):
            conv.begin_stream("req-1")
            conv.begin_stream("req-2")
            conv.append_stream_block("req-1", TextDeltaBlock(content="alpha"))
            conv.append_stream_block("req-2", TextDeltaBlock(content="beta"))

            assert conv.get_focused_stream_id() == "req-1"
            assert conv.set_focused_stream("req-2") is True
            assert conv.get_focused_stream_id() == "req-2"
            assert len(conv._stream_preview_turns["req-2"].strips) > 0

    def test_stream_delta_paints_are_coalesced_per_tick(self):
        conv = ConversationView()
        conv._last_width = 80
        conv._last_filters = {}
        conv.call_later = MagicMock()

        with self._patch_app_console(conv):
            conv.begin_stream("req-1")
            conv.append_stream_block("req-1", TextDeltaBlock(content="a"))
            conv.append_stream_block("req-1", TextDeltaBlock(content="b"))
            conv.append_stream_block("req-1", TextDeltaBlock(content="c"))

        # Multiple chunks schedule only one deferred flush.
        assert conv.call_later.call_count == 1

        conv._invalidate = MagicMock()
        flush_cb = conv.call_later.call_args.args[0]
        flush_cb()
        conv._invalidate.assert_called_once_with("stream_delta", request_id="req-1")

    def test_incremental_delta_text_buffer_and_version(self):
        conv = ConversationView()
        conv._last_width = 80
        conv._last_filters = {}

        with self._patch_app_console(conv):
            conv.begin_stream("req-1")
            conv.append_stream_block("req-1", TextDeltaBlock(content="hello "))
            conv.append_stream_block("req-1", TextDeltaBlock(content="world"))

        assert conv._domain_store.get_delta_preview_text("req-1") == "hello world"
        assert conv._domain_store.get_delta_version("req-1") == 2

    def test_stream_preview_skips_rerender_when_version_unchanged(self):
        conv = ConversationView()
        conv._last_width = 80
        conv._last_filters = {}

        with self._patch_app_console(conv):
            conv.begin_stream("req-1")
            conv.append_stream_block("req-1", TextDeltaBlock(content="alpha"))
            conv._pending_stream_delta_request_ids.clear()
            conv._stream_delta_flush_scheduled = False

            with patch("cc_dump.tui.rendering.render_streaming_preview", wraps=cc_dump.tui.rendering.render_streaming_preview) as preview:
                conv._render_stream_delta("req-1")
                conv._render_stream_delta("req-1")
                assert preview.call_count == 1


class TestSearchRerenderGeometry:
    """Test that search highlight rerenders skip unnecessary geometry work."""

    def _make_conv_with_turns(self, console, n_turns, filters):
        """Create ConversationView with n turns."""
        conv = ConversationView()
        for i in range(n_turns):
            blocks = [TextContentBlock(content=f"Turn {i} hello world", indent="")]
            strips, block_strip_map, _ = render_turn_to_strips(blocks, filters, console, width=80)
            td = TurnData(
                turn_index=i,
                blocks=blocks,
                strips=strips,
                block_strip_map=block_strip_map,
                _widest_strip=max((s.cell_length for s in strips), default=0),
            )
            td.compute_relevant_keys()
            td._last_filter_snapshot = {k: filters.get(k, ALWAYS_VISIBLE) for k in td.relevant_filter_keys}
            conv._turns.append(td)
        conv._recalculate_offsets()
        conv._last_filters = dict(filters)
        conv._last_width = 80
        return conv

    @contextlib.contextmanager
    def _patch_scroll(self, conv, scroll_y=0, height=50):
        region_mock = MagicMock()
        region_mock.width = 80
        region_mock.height = height
        app_mock = MagicMock(console=Console())
        cls = type(conv)

        conv.scroll_to = MagicMock()
        conv.refresh = MagicMock()
        with patch.object(cls, 'scroll_offset', new_callable=PropertyMock, return_value=Offset(0, scroll_y)), \
             patch.object(cls, 'scrollable_content_region', new_callable=PropertyMock, return_value=region_mock), \
             patch.object(cls, 'app', new_callable=PropertyMock, return_value=app_mock), \
             patch.object(cls, 'size', new_callable=PropertyMock, return_value=MagicMock(width=80)):
            yield

    def _make_search_ctx(self):
        from cc_dump.tui.search import SearchContext, SearchMode, compile_search_pattern
        pattern = compile_search_pattern("hello", SearchMode.CASE_INSENSITIVE)
        assert pattern is not None
        return SearchContext(
            pattern=pattern,
            pattern_str="hello",
            current_match=None,
            all_matches=[],
        )

    def test_search_rerender_skips_geometry_when_unchanged(self):
        """Search highlight is style-only — no offset tree or width tracker updates."""
        console = Console()
        filters = {}
        conv = self._make_conv_with_turns(console, 10, filters)
        search_ctx = self._make_search_ctx()

        with self._patch_scroll(conv, scroll_y=0, height=50):
            conv._follow_state = FollowState.OFF
            # First rerender establishes search-highlighted baseline strips.
            conv.rerender(filters, search_ctx=search_ctx)

            old_total_lines = conv._total_lines
            old_widest = conv._widest_line

            # Bump search revision so re_render detects a change and re-renders.
            conv._search_revision += 1

            with patch.object(conv, '_sync_turn_in_tree', wraps=conv._sync_turn_in_tree) as sync_mock, \
                 patch.object(conv, '_update_virtual_size', wraps=conv._update_virtual_size) as vsize_mock:
                conv.rerender(filters, search_ctx=search_ctx)

        # Geometry should be unchanged — search only changes styles.
        assert conv._total_lines == old_total_lines
        assert conv._widest_line == old_widest
        # _sync_turn_in_tree and _update_virtual_size should NOT have been called
        # because search highlighting doesn't change line counts or widths.
        assert sync_mock.call_count == 0, "geometry sync should be skipped for style-only search changes"
        assert vsize_mock.call_count == 0, "virtual size update should be skipped for style-only search changes"

    def test_search_rerender_invalidates_line_cache(self):
        """After search rerender, stale line cache entries for viewport turns are flushed."""
        console = Console()
        filters = {}
        conv = self._make_conv_with_turns(console, 5, filters)
        search_ctx = self._make_search_ctx()

        # Prime the line cache with some entries.
        for td in conv._turns:
            key = (td.turn_index, 0, 0, 80)
            conv._line_cache[key] = Strip.blank(80)
            conv._cache_keys_by_turn.setdefault(td.turn_index, set()).add(key)

        assert len(conv._line_cache) == 5

        with self._patch_scroll(conv, scroll_y=0, height=50):
            conv._follow_state = FollowState.OFF
            conv.rerender(filters, search_ctx=search_ctx)

        # Viewport cache entries should have been invalidated.
        for td in conv._turns:
            key = (td.turn_index, 0, 0, 80)
            assert key not in conv._line_cache, f"stale cache entry for turn {td.turn_index} should be flushed"

    def test_search_rerender_calls_refresh(self):
        """Search rerender must call refresh() to repaint visible lines."""
        console = Console()
        filters = {}
        conv = self._make_conv_with_turns(console, 5, filters)
        search_ctx = self._make_search_ctx()

        with self._patch_scroll(conv, scroll_y=0, height=50):
            conv._follow_state = FollowState.OFF
            conv.rerender(filters, search_ctx=search_ctx)
            assert conv.refresh.called, "refresh() should be called after search rerender"
