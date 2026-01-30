"""Unit tests for Sprint 1 widget architecture.

Tests the new widget architecture components:
- BLOCK_FILTER_KEY completeness
- render_turn_to_strips output
- TurnData.re_render skip logic
- ConversationView._find_turn_for_line binary search
- Sticky scroll anchor determinism across filter hide/show cycles
"""

import pytest
from unittest.mock import patch, PropertyMock, MagicMock
from rich.console import Console
from textual.geometry import Offset

from cc_dump.formatting import (
    SeparatorBlock,
    HeaderBlock,
    MetadataBlock,
    TurnBudgetBlock,
    SystemLabelBlock,
    TrackedContentBlock,
    RoleBlock,
    TextContentBlock,
    ToolUseBlock,
    ToolResultBlock,
    ImageBlock,
    UnknownTypeBlock,
    StreamInfoBlock,
    StreamToolUseBlock,
    TextDeltaBlock,
    StopReasonBlock,
    ErrorBlock,
    ProxyErrorBlock,
    LogBlock,
    NewlineBlock,
)
from cc_dump.tui.rendering import BLOCK_RENDERERS, BLOCK_FILTER_KEY, render_turn_to_strips
from cc_dump.tui.widget_factory import TurnData, ConversationView


class TestBlockFilterKeyCompleteness:
    """Test that BLOCK_FILTER_KEY covers all block types from BLOCK_RENDERERS."""

    def test_all_renderer_types_have_filter_keys(self):
        """Every block type in BLOCK_RENDERERS must have an entry in BLOCK_FILTER_KEY."""
        renderer_types = set(BLOCK_RENDERERS.keys())
        filter_key_types = set(BLOCK_FILTER_KEY.keys())

        assert renderer_types == filter_key_types, (
            f"BLOCK_FILTER_KEY missing types: {renderer_types - filter_key_types}\n"
            f"BLOCK_FILTER_KEY extra types: {filter_key_types - renderer_types}"
        )

    def test_filter_key_count_matches_block_count(self):
        """BLOCK_FILTER_KEY should have 20 entries (18+ block types)."""
        # Verify we have all expected block types
        assert len(BLOCK_FILTER_KEY) >= 18, (
            f"Expected at least 18 block types in BLOCK_FILTER_KEY, got {len(BLOCK_FILTER_KEY)}"
        )

    def test_filter_key_mappings_are_correct(self):
        """Verify key filter mappings match renderer behavior."""
        # Blocks that check specific filters
        assert BLOCK_FILTER_KEY[SeparatorBlock] == "headers"
        assert BLOCK_FILTER_KEY[HeaderBlock] == "headers"
        assert BLOCK_FILTER_KEY[MetadataBlock] == "metadata"
        assert BLOCK_FILTER_KEY[TurnBudgetBlock] == "expand"
        assert BLOCK_FILTER_KEY[SystemLabelBlock] == "system"
        assert BLOCK_FILTER_KEY[TrackedContentBlock] == "system"
        assert BLOCK_FILTER_KEY[RoleBlock] == "system"  # filters system roles
        assert BLOCK_FILTER_KEY[ToolUseBlock] == "tools"
        assert BLOCK_FILTER_KEY[ToolResultBlock] == "tools"
        assert BLOCK_FILTER_KEY[StreamInfoBlock] == "metadata"
        assert BLOCK_FILTER_KEY[StreamToolUseBlock] == "tools"
        assert BLOCK_FILTER_KEY[StopReasonBlock] == "metadata"

        # Blocks that are always visible (never filtered)
        assert BLOCK_FILTER_KEY[TextContentBlock] is None
        assert BLOCK_FILTER_KEY[ImageBlock] is None
        assert BLOCK_FILTER_KEY[UnknownTypeBlock] is None
        assert BLOCK_FILTER_KEY[TextDeltaBlock] is None
        assert BLOCK_FILTER_KEY[ErrorBlock] is None
        assert BLOCK_FILTER_KEY[ProxyErrorBlock] is None
        assert BLOCK_FILTER_KEY[LogBlock] is None
        assert BLOCK_FILTER_KEY[NewlineBlock] is None


class TestRenderTurnToStrips:
    """Test render_turn_to_strips rendering pipeline."""

    def test_empty_block_list_returns_empty_strips(self):
        """Empty block list should return empty strip list."""
        console = Console()
        filters = {}
        blocks = []

        strips, block_map = render_turn_to_strips(blocks, filters, console, width=80)

        assert strips == []
        assert block_map == {}

    def test_filtered_out_blocks_return_empty_strips(self):
        """All blocks filtered out should return empty strip list."""
        console = Console()
        filters = {"headers": False}  # Filter out headers
        blocks = [
            SeparatorBlock(style="light"),
            HeaderBlock(header_type="request", label="REQUEST 1", timestamp="12:00:00"),
        ]

        strips, block_map = render_turn_to_strips(blocks, filters, console, width=80)

        # Both blocks are filtered out, should get empty list
        assert strips == []
        assert block_map == {}

    def test_basic_rendering_produces_strips(self):
        """Basic text content should produce strips."""
        console = Console()
        filters = {}
        blocks = [
            TextContentBlock(text="Hello, world!", indent=""),
        ]

        strips, block_map = render_turn_to_strips(blocks, filters, console, width=80)

        # Should produce at least one strip
        assert len(strips) > 0
        # Each strip should be a Strip object with cell_length
        assert all(hasattr(strip, 'cell_length') for strip in strips)
        # Block map should map block 0 to strip 0
        assert block_map == {0: 0}

    def test_multiline_text_produces_multiple_strips(self):
        """Multi-line text should produce multiple strips."""
        console = Console()
        filters = {}
        blocks = [
            TextContentBlock(text="Line 1\nLine 2\nLine 3", indent=""),
        ]

        strips, block_map = render_turn_to_strips(blocks, filters, console, width=80)

        # Should produce 3 strips (one per line)
        assert len(strips) == 3
        assert block_map == {0: 0}

    def test_mixed_filtered_and_visible_blocks(self):
        """Mix of filtered and visible blocks should only render visible ones."""
        console = Console()
        filters = {"headers": False, "tools": True}
        blocks = [
            HeaderBlock(header_type="request", label="REQUEST 1", timestamp="12:00:00"),  # filtered out
            TextContentBlock(text="User message", indent=""),  # visible
            ToolUseBlock(name="read_file", input_size=100, msg_color_idx=0),  # visible
        ]

        strips, block_map = render_turn_to_strips(blocks, filters, console, width=80)

        # Should have at least 2 strips (text + tool)
        assert len(strips) >= 2
        # Block 0 (header) filtered out, blocks 1 and 2 visible
        assert 0 not in block_map
        assert 1 in block_map
        assert 2 in block_map
        assert block_map[1] == 0  # text block starts at strip 0


class TestTurnDataReRender:
    """Test TurnData.re_render skip logic."""

    def test_compute_relevant_keys_finds_filter_dependencies(self):
        """compute_relevant_keys should identify which filters affect this turn."""
        blocks = [
            TextContentBlock(text="Hello", indent=""),
            ToolUseBlock(name="test", input_size=10, msg_color_idx=0),
            MetadataBlock(model="claude-3", max_tokens=100, stream=True, tool_count=0),
        ]
        console = Console()
        td = TurnData(turn_index=0, blocks=blocks, strips=[])
        td.compute_relevant_keys()

        # Should find "tools" and "metadata" but not "headers" or "system"
        assert "tools" in td.relevant_filter_keys
        assert "metadata" in td.relevant_filter_keys
        assert "headers" not in td.relevant_filter_keys
        assert "system" not in td.relevant_filter_keys

    def test_re_render_skips_when_irrelevant_filter_changes(self):
        """re_render should skip when changed filter is not relevant."""
        blocks = [
            TextContentBlock(text="Hello", indent=""),
        ]
        console = Console()
        filters1 = {"headers": False, "tools": False}

        td = TurnData(
            turn_index=0,
            blocks=blocks,
            strips=render_turn_to_strips(blocks, filters1, console, width=80),
        )
        td.compute_relevant_keys()
        # Initial render
        td.re_render(filters1, console, 80)

        # Change a filter that doesn't affect this turn
        filters2 = {"headers": True, "tools": False}  # headers changed, but no header blocks
        result = td.re_render(filters2, console, 80)

        # Should skip re-render (return False)
        assert result is False

    def test_re_render_executes_when_relevant_filter_changes(self):
        """re_render should execute when a relevant filter changes."""
        blocks = [
            TextContentBlock(text="Hello", indent=""),
            ToolUseBlock(name="test", input_size=10, msg_color_idx=0),
        ]
        console = Console()
        filters1 = {"tools": False}

        td = TurnData(
            turn_index=0,
            blocks=blocks,
            strips=render_turn_to_strips(blocks, filters1, console, width=80),
        )
        td.compute_relevant_keys()
        # Initial render
        td.re_render(filters1, console, 80)

        # Change a filter that affects this turn
        filters2 = {"tools": True}  # tools changed, and we have ToolUseBlock
        result = td.re_render(filters2, console, 80)

        # Should execute re-render (return True)
        assert result is True

    def test_re_render_updates_strips(self):
        """re_render should update strips when executed."""
        blocks = [
            ToolUseBlock(name="test", input_size=10, msg_color_idx=0),
        ]
        console = Console()
        filters1 = {"tools": False}

        td = TurnData(
            turn_index=0,
            blocks=blocks,
            strips=render_turn_to_strips(blocks, filters1, console, width=80),
        )
        td.compute_relevant_keys()
        td.re_render(filters1, console, 80)

        # Tools filtered out, should have empty strips
        assert len(td.strips) == 0

        # Enable tools filter
        filters2 = {"tools": True}
        td.re_render(filters2, console, 80)

        # Should now have strips for the tool block
        assert len(td.strips) > 0


class TestConversationViewBinarySearch:
    """Test ConversationView._find_turn_for_line binary search correctness.

    These are unit tests that directly test the binary search algorithm
    without requiring a full Textual app context.
    """

    def test_find_turn_for_line_empty_list(self):
        """Binary search on empty turns list should return None."""
        from cc_dump.tui.widget_factory import ConversationView

        conv = ConversationView()
        result = conv._find_turn_for_line(0)
        assert result is None

    def test_find_turn_for_line_single_turn_creates_turn_data(self):
        """Test with a single TurnData directly without app."""
        from cc_dump.tui.widget_factory import ConversationView
        from textual.strip import Strip

        conv = ConversationView()

        # Manually create and add TurnData
        td = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="Hello", indent="")],
            strips=[Strip.blank(80), Strip.blank(80)],  # 2 lines
        )
        td.line_offset = 0
        conv._turns.append(td)
        conv._total_lines = 2

        # Should find the turn for any line within its range
        turn = conv._find_turn_for_line(0)
        assert turn is not None
        assert turn.turn_index == 0

        turn = conv._find_turn_for_line(1)
        assert turn is not None
        assert turn.turn_index == 0

    def test_find_turn_for_line_multiple_turns_manual(self):
        """Binary search with multiple turns should find correct turn."""
        from cc_dump.tui.widget_factory import ConversationView
        from textual.strip import Strip

        conv = ConversationView()

        # Create multiple turns with known line counts
        # Turn 0: 3 lines (line 0-2)
        td0 = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="A\nB\nC", indent="")],
            strips=[Strip.blank(80), Strip.blank(80), Strip.blank(80)],
        )
        td0.line_offset = 0

        # Turn 1: 2 lines (line 3-4)
        td1 = TurnData(
            turn_index=1,
            blocks=[TextContentBlock(text="D\nE", indent="")],
            strips=[Strip.blank(80), Strip.blank(80)],
        )
        td1.line_offset = 3

        # Turn 2: 1 line (line 5)
        td2 = TurnData(
            turn_index=2,
            blocks=[TextContentBlock(text="F", indent="")],
            strips=[Strip.blank(80)],
        )
        td2.line_offset = 5

        conv._turns.extend([td0, td1, td2])
        conv._total_lines = 6

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
        from cc_dump.tui.widget_factory import ConversationView
        from textual.strip import Strip

        conv = ConversationView()

        # Create a turn with 2 lines
        td = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="Line 1\nLine 2", indent="")],
            strips=[Strip.blank(80), Strip.blank(80)],
        )
        td.line_offset = 0
        conv._turns.append(td)
        conv._total_lines = 2

        # Line 0-1 are valid, line 10 is beyond
        turn = conv._find_turn_for_line(10)
        assert turn is None

    def test_find_turn_for_line_boundary_conditions(self):
        """Test boundary conditions at turn edges."""
        from cc_dump.tui.widget_factory import ConversationView
        from textual.strip import Strip

        conv = ConversationView()

        # Turn 0: lines 0-2 (3 lines)
        td0 = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="A\nB\nC", indent="")],
            strips=[Strip.blank(80), Strip.blank(80), Strip.blank(80)],
        )
        td0.line_offset = 0

        # Turn 1: lines 3-5 (3 lines)
        td1 = TurnData(
            turn_index=1,
            blocks=[TextContentBlock(text="D\nE\nF", indent="")],
            strips=[Strip.blank(80), Strip.blank(80), Strip.blank(80)],
        )
        td1.line_offset = 3

        conv._turns.extend([td0, td1])
        conv._total_lines = 6

        # Test first line of each turn
        assert conv._find_turn_for_line(0).turn_index == 0
        assert conv._find_turn_for_line(3).turn_index == 1

        # Test last line of each turn
        assert conv._find_turn_for_line(2).turn_index == 0
        assert conv._find_turn_for_line(5).turn_index == 1


class TestStickyScrollAnchor:
    """Test that hide→show filter cycles preserve scroll position.

    The sticky anchor is only updated on user scroll, not programmatic
    scrolls from filter restores. This makes filter toggling deterministic:
    hiding a block then showing it returns to the exact same line.
    """

    def _make_conv(self, console: Console, blocks: list, filters: dict) -> ConversationView:
        """Create a ConversationView with one turn, mocking Textual internals."""
        conv = ConversationView()

        strips, block_strip_map = render_turn_to_strips(blocks, filters, console, width=80)
        td = TurnData(
            turn_index=0,
            blocks=blocks,
            strips=strips,
            block_strip_map=block_strip_map,
        )
        td.compute_relevant_keys()
        td._last_filter_snapshot = {k: filters.get(k, False) for k in td.relevant_filter_keys}

        conv._turns.append(td)
        conv._total_lines = len(strips)
        conv._last_filters = dict(filters)
        conv._last_width = 80
        return conv

    def _patch_scroll(self, conv, scroll_y=0):
        """Context manager that mocks scroll infrastructure on ConversationView.

        Patches class-level properties (scroll_offset, scrollable_content_region,
        app) since Textual defines them as properties/descriptors.
        """
        import contextlib
        region_mock = MagicMock()
        region_mock.width = 80
        app_mock = MagicMock(console=Console())
        cls = type(conv)

        @contextlib.contextmanager
        def _ctx():
            conv.scroll_to = MagicMock()
            with patch.object(cls, 'scroll_offset', new_callable=PropertyMock, return_value=Offset(0, scroll_y)), \
                 patch.object(cls, 'scrollable_content_region', new_callable=PropertyMock, return_value=region_mock), \
                 patch.object(cls, 'app', new_callable=PropertyMock, return_value=app_mock):
                yield

        return _ctx()

    def test_compute_anchor_identifies_block_and_line(self):
        """_compute_anchor should return (turn_index, block_index, line_within_block)."""
        console = Console()
        blocks = [
            RoleBlock(role="user", msg_index=0),
            TextContentBlock(text="Line 0\nLine 1\nLine 2\nLine 3\nLine 4", indent=""),
        ]
        filters = {}

        conv = self._make_conv(console, blocks, filters)
        td = conv._turns[0]

        # Verify block map: block 0 (RoleBlock) at strip 0, block 1 (TextContent) at some offset
        assert 0 in td.block_strip_map
        assert 1 in td.block_strip_map
        text_block_start = td.block_strip_map[1]

        # Simulate scroll to line 2 within the text block
        target_scroll_y = text_block_start + 2
        with self._patch_scroll(conv, scroll_y=target_scroll_y):
            anchor = conv._compute_anchor()

        assert anchor is not None
        turn_idx, block_idx, line_in_block = anchor
        assert turn_idx == 0
        assert block_idx == 1  # TextContentBlock
        assert line_in_block == 2  # 3rd line within the block

    def test_anchor_not_overwritten_on_programmatic_scroll(self):
        """When _suppress_anchor_update is True, watch_scroll_y must not change _anchor."""
        conv = ConversationView()
        original_anchor = (0, 3, 25)
        conv._anchor = original_anchor

        # Simulate programmatic scroll (suppress flag set)
        conv._suppress_anchor_update = True
        conv.watch_scroll_y(0.0, 100.0)
        conv._suppress_anchor_update = False

        assert conv._anchor == original_anchor

    def test_anchor_updated_on_user_scroll(self):
        """When _suppress_anchor_update is False, watch_scroll_y updates _anchor."""
        console = Console()
        blocks = [
            TextContentBlock(text="Line\n" * 10, indent=""),
        ]
        filters = {}

        conv = self._make_conv(console, blocks, filters)

        # Simulate user scrolling to line 5
        with self._patch_scroll(conv, scroll_y=5):
            conv._suppress_anchor_update = False
            conv.watch_scroll_y(0.0, 5.0)

        assert conv._anchor is not None
        assert conv._anchor[2] == 5  # line 5 within block 0

    def test_anchor_survives_hide_show_cycle(self):
        """Core invariant: hide block → show block → same scroll position.

        Scenario: user is at line 1 within a system content block (which
        renders to 2 strips: tag line + collapsed content). They hide
        system (block disappears), then show system again.
        The anchor should be preserved exactly.
        """
        console = Console()
        blocks = [
            RoleBlock(role="user", msg_index=0),
            TextContentBlock(text="User says hello", indent=""),
            SystemLabelBlock(),
            TrackedContentBlock(
                status="new", tag_id="sys", color_idx=0,
                content="System content here",
            ),
        ]
        filters_show = {"system": True}

        conv = self._make_conv(console, blocks, filters_show)
        td = conv._turns[0]

        # Verify system blocks are visible
        assert 2 in td.block_strip_map  # SystemLabelBlock
        assert 3 in td.block_strip_map  # TrackedContentBlock
        system_block_start = td.block_strip_map[2]

        # --- Step 1: User is viewing the system label block (line 0 within it) ---
        original_anchor = (0, 2, 0)
        conv._anchor = original_anchor

        # --- Step 2: Hide system filter ---
        filters_hide = {"system": False}
        with self._patch_scroll(conv, scroll_y=system_block_start):
            conv.rerender(filters_hide)

        # System blocks should now be filtered out
        assert 2 not in conv._turns[0].block_strip_map
        assert 3 not in conv._turns[0].block_strip_map
        # Anchor must be preserved (not overwritten by fallback scroll)
        assert conv._anchor == original_anchor, (
            f"Anchor was overwritten during hide! Got {conv._anchor}, expected {original_anchor}"
        )

        # --- Step 3: Show system filter again ---
        with self._patch_scroll(conv, scroll_y=0):  # currently at fallback position
            conv.rerender(filters_show)

        # System blocks should be visible again
        assert 2 in conv._turns[0].block_strip_map
        # Anchor must still be the original
        assert conv._anchor == original_anchor, (
            f"Anchor was overwritten during show! Got {conv._anchor}, expected {original_anchor}"
        )

        # Verify scroll_to was called with the correct target on show
        new_system_start = conv._turns[0].block_strip_map[2]
        expected_y = conv._turns[0].line_offset + new_system_start + 0
        conv.scroll_to.assert_called_with(y=expected_y, animate=False)

    def test_anchor_updates_after_user_scrolls_post_restore(self):
        """After a restore, if the user scrolls, the anchor updates normally."""
        console = Console()
        blocks = [
            TextContentBlock(text="\n".join(f"Line {i}" for i in range(20)), indent=""),
        ]
        filters = {}

        conv = self._make_conv(console, blocks, filters)
        conv._anchor = (0, 0, 10)

        # Simulate user scrolling to line 5 (not suppressed)
        with self._patch_scroll(conv, scroll_y=5):
            conv._suppress_anchor_update = False
            conv.watch_scroll_y(10.0, 5.0)

        assert conv._anchor is not None
        assert conv._anchor == (0, 0, 5)

    def test_multiple_hide_show_cycles_are_stable(self):
        """Repeated hide→show should always return to same position."""
        console = Console()
        blocks = [
            TextContentBlock(text="Visible text", indent=""),
            SystemLabelBlock(),
            TrackedContentBlock(
                status="new", tag_id="sys", color_idx=0,
                content="System content",
            ),
        ]
        filters_show = {"system": True}

        conv = self._make_conv(console, blocks, filters_show)
        # Anchor at the SystemLabelBlock
        original_anchor = (0, 1, 0)
        conv._anchor = original_anchor

        # Cycle 3 times: hide → show
        for cycle in range(3):
            with self._patch_scroll(conv, scroll_y=0):
                conv.rerender({"system": False})
            assert conv._anchor == original_anchor, f"Anchor lost on hide cycle {cycle}"

            with self._patch_scroll(conv, scroll_y=0):
                conv.rerender({"system": True})
            assert conv._anchor == original_anchor, f"Anchor lost on show cycle {cycle}"
