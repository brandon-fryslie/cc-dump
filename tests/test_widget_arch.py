"""Unit tests for Sprint 1 widget architecture.

Tests the new widget architecture components:
- BLOCK_FILTER_KEY completeness
- render_turn_to_strips output
- TurnData.re_render skip logic
- ConversationView._find_turn_for_line binary search
- Saved scroll anchor determinism across filter hide/show cycles
"""

import contextlib
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
        """Verify key filter mappings match renderer behavior.

        BLOCK_FILTER_KEY uses class name strings as keys (for hot-reload safety).
        """
        # Blocks that check specific filters
        assert BLOCK_FILTER_KEY["SeparatorBlock"] == "headers"
        assert BLOCK_FILTER_KEY["HeaderBlock"] == "headers"
        assert BLOCK_FILTER_KEY["MetadataBlock"] == "metadata"
        assert BLOCK_FILTER_KEY["TurnBudgetBlock"] == "expand"
        assert BLOCK_FILTER_KEY["SystemLabelBlock"] == "system"
        assert BLOCK_FILTER_KEY["TrackedContentBlock"] == "system"
        assert BLOCK_FILTER_KEY["RoleBlock"] == "system"  # filters system roles
        assert BLOCK_FILTER_KEY["ToolUseBlock"] == "tools"
        assert BLOCK_FILTER_KEY["ToolResultBlock"] == "tools"  # filtered by tools; summary handled by render_blocks
        assert BLOCK_FILTER_KEY["StreamInfoBlock"] == "metadata"
        assert BLOCK_FILTER_KEY["StreamToolUseBlock"] == "tools"
        assert BLOCK_FILTER_KEY["StopReasonBlock"] == "metadata"

        # Blocks that are always visible (never filtered)
        assert BLOCK_FILTER_KEY["TextContentBlock"] is None
        assert BLOCK_FILTER_KEY["ImageBlock"] is None
        assert BLOCK_FILTER_KEY["UnknownTypeBlock"] is None
        assert BLOCK_FILTER_KEY["TextDeltaBlock"] is None
        assert BLOCK_FILTER_KEY["ErrorBlock"] is None
        assert BLOCK_FILTER_KEY["ProxyErrorBlock"] is None
        assert BLOCK_FILTER_KEY["LogBlock"] is None
        assert BLOCK_FILTER_KEY["NewlineBlock"] is None


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

        # Tools filtered out, but summary line appears via render_blocks
        assert len(td.strips) == 1  # summary line

        # Enable tools filter
        filters2 = {"tools": True}
        td.re_render(filters2, console, 80)

        # Should now have strips for the individual tool block
        assert len(td.strips) > 0


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


class TestSavedScrollAnchor:
    """Test that hide→show filter cycles preserve scroll position.

    When a filter hides the block the user was viewing, the anchor is
    saved. When the block reappears, the saved anchor restores the exact
    scroll position. No ScrollView internals are overridden.
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

    @contextlib.contextmanager
    def _patch_scroll(self, conv, scroll_y=0):
        """Mock scroll infrastructure on ConversationView.

        Patches class-level properties (scroll_offset, scrollable_content_region,
        app) since Textual defines them as properties/descriptors.
        """
        region_mock = MagicMock()
        region_mock.width = 80
        region_mock.height = 50
        app_mock = MagicMock(console=Console())
        cls = type(conv)

        conv.scroll_to = MagicMock()
        with patch.object(cls, 'scroll_offset', new_callable=PropertyMock, return_value=Offset(0, scroll_y)), \
             patch.object(cls, 'scrollable_content_region', new_callable=PropertyMock, return_value=region_mock), \
             patch.object(cls, 'app', new_callable=PropertyMock, return_value=app_mock):
            yield

    def test_compute_anchor_identifies_block_and_line(self):
        """_compute_anchor_from_scroll returns (turn, block, line_within_block)."""
        console = Console()
        blocks = [
            RoleBlock(role="user", msg_index=0),
            TextContentBlock(text="Line 0\nLine 1\nLine 2\nLine 3\nLine 4", indent=""),
        ]
        filters = {}

        conv = self._make_conv(console, blocks, filters)
        td = conv._turns[0]

        assert 0 in td.block_strip_map
        assert 1 in td.block_strip_map
        text_block_start = td.block_strip_map[1]

        target_scroll_y = text_block_start + 2
        with self._patch_scroll(conv, scroll_y=target_scroll_y):
            anchor = conv._compute_anchor_from_scroll()

        assert anchor is not None
        turn_idx, block_idx, line_in_block = anchor
        assert turn_idx == 0
        assert block_idx == 1  # TextContentBlock
        assert line_in_block == 2  # 3rd line within the block

    def test_saved_anchor_set_when_block_hidden(self):
        """When a filter hides the anchor block, _saved_anchor is set."""
        console = Console()
        blocks = [
            TextContentBlock(text="Always visible", indent=""),
            SystemLabelBlock(),
            TrackedContentBlock(
                status="new", tag_id="sys", color_idx=0,
                content="System content",
            ),
        ]
        filters_show = {"system": True}
        conv = self._make_conv(console, blocks, filters_show)

        assert conv._saved_anchor is None

        # Scroll is at the SystemLabelBlock
        system_start = conv._turns[0].block_strip_map[1]
        with self._patch_scroll(conv, scroll_y=system_start):
            conv.rerender({"system": False})

        # Anchor should be saved (block 1 = SystemLabelBlock is now hidden)
        assert conv._saved_anchor is not None
        assert conv._saved_anchor[1] == 1  # block_index of SystemLabelBlock

    def test_saved_anchor_cleared_when_block_reappears(self):
        """When a saved anchor's block becomes visible, _saved_anchor is cleared."""
        console = Console()
        blocks = [
            TextContentBlock(text="Always visible", indent=""),
            SystemLabelBlock(),
        ]
        filters_show = {"system": True}
        conv = self._make_conv(console, blocks, filters_show)

        # Pre-set saved anchor as if block was previously hidden
        conv._saved_anchor = (0, 1, 0)

        # Show system — block 1 becomes visible again
        with self._patch_scroll(conv, scroll_y=0):
            conv.rerender({"system": True})

        # Saved anchor should be cleared (block restored successfully)
        assert conv._saved_anchor is None

    def test_anchor_survives_hide_show_cycle(self):
        """Core invariant: hide block → show block → scroll_to called with correct target."""
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

        assert 2 in td.block_strip_map
        system_block_start = td.block_strip_map[2]

        # --- Step 1: Hide system (user was viewing SystemLabelBlock) ---
        with self._patch_scroll(conv, scroll_y=system_block_start):
            conv.rerender({"system": False})

        assert 2 not in conv._turns[0].block_strip_map
        assert conv._saved_anchor is not None
        assert conv._saved_anchor == (0, 2, 0)

        # --- Step 2: Show system again ---
        with self._patch_scroll(conv, scroll_y=0):
            conv.rerender({"system": True})

        # Saved anchor should be cleared
        assert conv._saved_anchor is None
        # Verify scroll_to was called to restore the system block position
        assert 2 in conv._turns[0].block_strip_map
        new_system_start = conv._turns[0].block_strip_map[2]
        expected_y = conv._turns[0].line_offset + new_system_start
        conv.scroll_to.assert_called_with(y=expected_y, animate=False)

    def test_multiple_hide_show_cycles_are_stable(self):
        """Repeated hide→show should always restore and clear saved anchor."""
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
        system_start = conv._turns[0].block_strip_map[1]

        for cycle in range(3):
            # Hide — saved anchor set
            with self._patch_scroll(conv, scroll_y=system_start):
                conv.rerender({"system": False})
            assert conv._saved_anchor is not None, f"No saved anchor on hide cycle {cycle}"
            assert conv._saved_anchor[1] == 1, f"Wrong block in saved anchor cycle {cycle}"

            # Show — saved anchor cleared, scroll restored
            with self._patch_scroll(conv, scroll_y=0):
                conv.rerender({"system": True})
            assert conv._saved_anchor is None, f"Saved anchor not cleared on show cycle {cycle}"

    def test_saved_anchor_preserved_across_unrelated_filter_changes(self):
        """Changing a different filter while saved anchor exists should keep it."""
        console = Console()
        blocks = [
            TextContentBlock(text="Visible", indent=""),
            SystemLabelBlock(),
            ToolUseBlock(name="test", input_size=10, msg_color_idx=0),
        ]
        conv = self._make_conv(console, blocks, {"system": True, "tools": True})

        # Hide system — anchor saved for system block
        system_start = conv._turns[0].block_strip_map[1]
        with self._patch_scroll(conv, scroll_y=system_start):
            conv.rerender({"system": False, "tools": True})

        saved = conv._saved_anchor
        assert saved is not None

        # Toggle tools (unrelated to saved anchor's system block)
        with self._patch_scroll(conv, scroll_y=0):
            conv.rerender({"system": False, "tools": False})

        # Saved anchor should still be there (system block still hidden)
        assert conv._saved_anchor == saved


class TestWidestStripCache:
    """Test _widest_strip caching on TurnData."""

    def test_widest_strip_set_after_re_render(self):
        """_widest_strip matches actual max strip cell_length after re_render."""
        from rich.console import Console
        blocks = [TextContentBlock(text="Short\nA much longer line of text here", indent="")]
        console = Console()
        filters = {}
        td = TurnData(turn_index=0, blocks=blocks, strips=[])
        td.compute_relevant_keys()
        td.re_render(filters, console, 80, force=True)

        expected = max(s.cell_length for s in td.strips) if td.strips else 0
        assert td._widest_strip == expected
        assert td._widest_strip > 0

    def test_widest_strip_zero_for_empty_strips(self):
        """_widest_strip is 0 when all blocks filtered out."""
        from rich.console import Console
        blocks = [SystemLabelBlock()]
        console = Console()
        td = TurnData(turn_index=0, blocks=blocks, strips=[])
        td.compute_relevant_keys()
        # System labels filtered with system: False
        td.re_render({"system": False}, console, 80, force=True)
        # No strips rendered when filtered
        assert len(td.strips) == 0
        assert td._widest_strip == 0


class TestIncrementalOffsets:
    """Test _recalculate_offsets_from correctness."""

    def test_incremental_matches_full_recalc(self):
        """Incremental from index K produces same offsets as full recalc."""
        from textual.strip import Strip

        conv = ConversationView()
        # Build 5 turns with known strip counts
        for i in range(5):
            strip_count = (i + 1) * 2  # 2, 4, 6, 8, 10
            td = TurnData(
                turn_index=i,
                blocks=[],
                strips=[Strip.blank(80 + i * 10)] * strip_count,
                _widest_strip=80 + i * 10,
            )
            conv._turns.append(td)

        # Full recalc to establish baseline
        conv._recalculate_offsets()
        baseline_offsets = [t.line_offset for t in conv._turns]
        baseline_total = conv._total_lines
        baseline_widest = conv._widest_line

        # Modify turn 2 (change strip count)
        conv._turns[2].strips = [Strip.blank(90)] * 3  # was 6 strips, now 3
        conv._turns[2]._widest_strip = 90

        # Incremental from index 2
        conv._recalculate_offsets_from(2)
        incr_offsets = [t.line_offset for t in conv._turns]

        # Turns 0-1 offsets unchanged
        assert incr_offsets[0] == baseline_offsets[0]
        assert incr_offsets[1] == baseline_offsets[1]

        # Full recalc for comparison
        conv._recalculate_offsets()
        full_offsets = [t.line_offset for t in conv._turns]

        # Incremental and full must match
        assert incr_offsets == full_offsets

    def test_incremental_from_zero_matches_full(self):
        """_recalculate_offsets_from(0) is identical to _recalculate_offsets()."""
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
        offsets_from = [t.line_offset for t in conv._turns]
        total_from = conv._total_lines

        conv._recalculate_offsets()
        offsets_full = [t.line_offset for t in conv._turns]
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
                blocks=[TextContentBlock(text="x", indent="")],
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
                TextContentBlock(text=f"Turn {i}", indent=""),
                ToolUseBlock(name="test", input_size=10, msg_color_idx=0),
            ]
            strips, block_strip_map = render_turn_to_strips(blocks, filters, console, width=80)
            td = TurnData(
                turn_index=i,
                blocks=blocks,
                strips=strips,
                block_strip_map=block_strip_map,
                _widest_strip=max((s.cell_length for s in strips), default=0),
            )
            td.compute_relevant_keys()
            td._last_filter_snapshot = {k: filters.get(k, False) for k in td.relevant_filter_keys}
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

    def test_off_viewport_turns_get_pending_snapshot(self):
        """Off-viewport turns should get _pending_filter_snapshot set, not re-rendered."""
        console = Console()
        filters_initial = {"tools": True}
        # 200 turns × ~2 lines = ~400 total lines.  With viewport=10 + buffer=20,
        # only turns covering lines 0..30 are in-range — the rest are off-viewport.
        conv = self._make_conv_with_turns(console, 200, filters_initial)

        with self._patch_scroll(conv, scroll_y=0, height=10):
            conv._follow_mode = False
            conv.rerender({"tools": False})

        # Compute viewport range to know which turns were deferred
        with self._patch_scroll(conv, scroll_y=0, height=10):
            vp_start, vp_end = conv._viewport_turn_range()

        has_pending = False
        for idx, td in enumerate(conv._turns):
            if idx >= vp_end:
                if td._pending_filter_snapshot is not None:
                    has_pending = True
                    assert "tools" in td._pending_filter_snapshot
                    assert td._pending_filter_snapshot["tools"] is False

        assert has_pending, (
            f"No off-viewport turns got _pending_filter_snapshot "
            f"(vp_end={vp_end}, total_turns={len(conv._turns)})"
        )

    def test_viewport_turns_get_re_rendered(self):
        """Viewport turns should be re-rendered, not deferred."""
        console = Console()
        filters_initial = {"tools": True}
        conv = self._make_conv_with_turns(console, 50, filters_initial)

        with self._patch_scroll(conv, scroll_y=0, height=10):
            vp_start, vp_end = conv._viewport_turn_range()
            conv._follow_mode = False
            conv.rerender({"tools": False})

        # Viewport turns should have no pending snapshot
        for idx in range(vp_start, min(vp_end, len(conv._turns))):
            td = conv._turns[idx]
            assert td._pending_filter_snapshot is None, (
                f"Viewport turn {idx} should not have pending snapshot"
            )

    def test_pending_snapshot_cleared_on_re_render(self):
        """When a turn with _pending_filter_snapshot is re-rendered, pending is cleared."""
        console = Console()
        blocks = [
            TextContentBlock(text="Hello", indent=""),
            ToolUseBlock(name="test", input_size=10, msg_color_idx=0),
        ]
        td = TurnData(
            turn_index=0,
            blocks=blocks,
            strips=[],
        )
        td.compute_relevant_keys()
        td._pending_filter_snapshot = {"tools": False}

        # re_render should clear pending
        td.re_render({"tools": True}, console, 80, force=True)
        assert td._pending_filter_snapshot is None
