"""Unit tests for Sprint 2 scroll-nav features.

Tests the scroll and navigation components added in Sprint 2:
- Follow mode (auto-scroll to bottom on new content)
- Turn selection (visual highlight)
- Click to select turn
- Keyboard navigation (j/k/n/N/g/G)
- State persistence (follow_mode and selected_turn)
"""

import pytest
from unittest.mock import patch, PropertyMock, MagicMock
from textual.geometry import Offset
from textual.strip import Strip
from rich.console import Console

from cc_dump.formatting import (
    TextContentBlock,
    ToolUseBlock,
    ToolResultBlock,
    StreamToolUseBlock,
    RoleBlock,
)
from cc_dump.tui.widget_factory import ConversationView, TurnData
from cc_dump.tui.rendering import render_turn_to_strips


class TestFollowMode:
    """Test follow mode toggle and auto-scroll behavior."""

    def test_follow_mode_defaults_to_true(self):
        """ConversationView should have follow mode enabled by default."""
        conv = ConversationView()
        assert conv._follow_mode is True

    def test_toggle_follow_flips_state(self):
        """toggle_follow() should flip the follow mode state."""
        conv = ConversationView()

        # Start True
        assert conv._follow_mode is True

        # Mock scroll_end to prevent actual scrolling
        conv.scroll_end = MagicMock()

        # Toggle to False
        conv.toggle_follow()
        assert conv._follow_mode is False
        conv.scroll_end.assert_not_called()

        # Toggle back to True (should scroll)
        conv.toggle_follow()
        assert conv._follow_mode is True
        conv.scroll_end.assert_called_once_with(animate=False)

    def test_scroll_to_bottom_re_enables_follow_mode(self):
        """scroll_to_bottom() should re-enable follow mode."""
        conv = ConversationView()
        conv._follow_mode = False
        conv.scroll_end = MagicMock()

        conv.scroll_to_bottom()

        assert conv._follow_mode is True
        conv.scroll_end.assert_called_once_with(animate=False)

    def test_scrolling_programmatically_guard_exists(self):
        """_scrolling_programmatically flag should exist and be used."""
        conv = ConversationView()

        # Attribute exists
        assert hasattr(conv, '_scrolling_programmatically')
        assert conv._scrolling_programmatically is False

    def test_scrolling_programmatically_set_during_scroll_to_bottom(self):
        """scroll_to_bottom should set _scrolling_programmatically guard."""
        conv = ConversationView()

        # Track guard state during scroll_end call
        guard_states = []

        def mock_scroll_end(**kwargs):
            guard_states.append(conv._scrolling_programmatically)

        conv.scroll_end = mock_scroll_end
        conv.scroll_to_bottom()

        # Guard should have been True during scroll_end
        assert guard_states == [True]
        # Guard should be False after
        assert conv._scrolling_programmatically is False

    def test_watch_scroll_y_disables_follow_when_not_at_end(self):
        """watch_scroll_y should disable follow mode when scrolling away from bottom."""
        conv = ConversationView()
        conv._follow_mode = True

        # Mock is_vertical_scroll_end to return False
        with patch.object(type(conv), 'is_vertical_scroll_end', new_callable=PropertyMock, return_value=False):
            conv.watch_scroll_y(100.0, 50.0)

        assert conv._follow_mode is False

    def test_watch_scroll_y_enables_follow_when_at_end(self):
        """watch_scroll_y should enable follow mode when scrolling to bottom."""
        conv = ConversationView()
        conv._follow_mode = False

        # Mock is_vertical_scroll_end to return True
        with patch.object(type(conv), 'is_vertical_scroll_end', new_callable=PropertyMock, return_value=True):
            conv.watch_scroll_y(50.0, 100.0)

        assert conv._follow_mode is True

    def test_watch_scroll_y_ignores_programmatic_scrolling(self):
        """watch_scroll_y should not change follow mode when _scrolling_programmatically is True."""
        conv = ConversationView()
        conv._follow_mode = True
        conv._scrolling_programmatically = True

        # Mock is_vertical_scroll_end to return False (would normally disable follow)
        with patch.object(type(conv), 'is_vertical_scroll_end', new_callable=PropertyMock, return_value=False):
            conv.watch_scroll_y(100.0, 50.0)

        # Follow mode should remain True
        assert conv._follow_mode is True


class TestTurnSelection:
    """Test turn selection state management and visual highlight."""

    def test_selected_turn_defaults_to_none(self):
        """_selected_turn should default to None."""
        conv = ConversationView()
        assert conv._selected_turn is None

    def test_select_turn_sets_selected_turn(self):
        """select_turn() should update _selected_turn."""
        conv = ConversationView()

        # Add a turn
        td = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="Hello", indent="")],
            strips=[Strip.blank(80)],
        )
        td.line_offset = 0
        conv._turns.append(td)
        conv._total_lines = 1

        # Mock refresh_lines to prevent actual rendering
        conv.refresh_lines = MagicMock()

        conv.select_turn(0)

        assert conv._selected_turn == 0

    def test_select_turn_clears_line_cache(self):
        """select_turn() should selectively clear cache entries for affected turns."""
        conv = ConversationView()

        # Add two turns
        td0 = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="Hello", indent="")],
            strips=[Strip.blank(80)],
        )
        td0.line_offset = 0
        conv._turns.append(td0)

        td1 = TurnData(
            turn_index=1,
            blocks=[TextContentBlock(text="World", indent="")],
            strips=[Strip.blank(80)],
        )
        td1.line_offset = 1
        conv._turns.append(td1)
        conv._total_lines = 2

        # Populate cache for both turns with tracking
        key0 = (0, 0, 80, 80, None)
        key1 = (1, 0, 80, 80, None)
        conv._line_cache[key0] = Strip.blank(80)
        conv._line_cache[key1] = Strip.blank(80)

        # Set up tracking as if render_line() had been called
        conv._cache_keys_by_turn[0] = {key0}
        conv._cache_keys_by_turn[1] = {key1}

        assert len(conv._line_cache) == 2

        # Mock refresh_lines
        conv.refresh_lines = MagicMock()

        conv.select_turn(0)

        # Only turn 0's cache entry should be cleared (selective invalidation)
        # Turn 1's entry should remain
        assert key0 not in conv._line_cache
        assert key1 in conv._line_cache

    def test_select_turn_refreshes_affected_lines(self):
        """select_turn() should refresh the selected turn's line range."""
        conv = ConversationView()

        # Add two turns
        td0 = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="A\nB\nC", indent="")],
            strips=[Strip.blank(80), Strip.blank(80), Strip.blank(80)],
        )
        td0.line_offset = 0

        td1 = TurnData(
            turn_index=1,
            blocks=[TextContentBlock(text="D\nE", indent="")],
            strips=[Strip.blank(80), Strip.blank(80)],
        )
        td1.line_offset = 3

        conv._turns.extend([td0, td1])
        conv._total_lines = 5

        conv.refresh_lines = MagicMock()

        # Select turn 1
        conv.select_turn(1)

        # Should refresh turn 1's lines (offset=3, count=2)
        conv.refresh_lines.assert_called_with(3, 2)

    def test_deselect_clears_selection(self):
        """deselect() should clear _selected_turn."""
        conv = ConversationView()

        # Add a turn and select it
        td = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="Hello", indent="")],
            strips=[Strip.blank(80)],
        )
        td.line_offset = 0
        conv._turns.append(td)
        conv._total_lines = 1

        conv.refresh_lines = MagicMock()
        conv.select_turn(0)
        assert conv._selected_turn == 0

        conv.deselect()

        assert conv._selected_turn is None

    def test_only_one_turn_selected_at_a_time(self):
        """Selecting a new turn should clear the old selection."""
        conv = ConversationView()

        # Add three turns
        for i in range(3):
            td = TurnData(
                turn_index=i,
                blocks=[TextContentBlock(text=f"Turn {i}", indent="")],
                strips=[Strip.blank(80)],
            )
            td.line_offset = i
            conv._turns.append(td)
        conv._total_lines = 3

        conv.refresh_lines = MagicMock()

        # Select turn 0
        conv.select_turn(0)
        assert conv._selected_turn == 0

        # Select turn 1 - should clear turn 0 and select turn 1
        conv.select_turn(1)
        assert conv._selected_turn == 1

        # Select turn 2 - should clear turn 1 and select turn 2
        conv.select_turn(2)
        assert conv._selected_turn == 2

    def test_selected_style_is_defined(self):
        """_SELECTED_STYLE should be defined as a class attribute."""
        assert hasattr(ConversationView, '_SELECTED_STYLE')
        from rich.style import Style
        assert isinstance(ConversationView._SELECTED_STYLE, Style)


class TestClickToSelect:
    """Test click-to-select turn functionality."""

    def test_on_click_maps_coordinates_to_turn(self):
        """on_click should map event coordinates to turn via _find_turn_for_line."""
        conv = ConversationView()

        # Add two turns
        td0 = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="A\nB\nC", indent="")],
            strips=[Strip.blank(80), Strip.blank(80), Strip.blank(80)],
        )
        td0.line_offset = 0

        td1 = TurnData(
            turn_index=1,
            blocks=[TextContentBlock(text="D\nE", indent="")],
            strips=[Strip.blank(80), Strip.blank(80)],
        )
        td1.line_offset = 3

        conv._turns.extend([td0, td1])
        conv._total_lines = 5

        # Mock event and scroll offset
        event = MagicMock()
        event.y = 1  # viewport-relative

        cls = type(conv)
        with patch.object(cls, 'scroll_offset', new_callable=PropertyMock, return_value=Offset(0, 2)):
            # content_y = 1 + 2 = 3 → turn 1
            conv.refresh_lines = MagicMock()
            conv.on_click(event)

        # Should select turn 1 (line 3 is in turn 1)
        assert conv._selected_turn == 1

    def test_on_click_uses_find_turn_for_line(self):
        """on_click should use _find_turn_for_line to resolve turn."""
        conv = ConversationView()

        # Add a turn
        td = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="Hello", indent="")],
            strips=[Strip.blank(80)],
        )
        td.line_offset = 0
        conv._turns.append(td)
        conv._total_lines = 1

        # Mock _find_turn_for_line
        conv._find_turn_for_line = MagicMock(return_value=td)
        conv.refresh_lines = MagicMock()

        event = MagicMock()
        event.y = 0

        cls = type(conv)
        with patch.object(cls, 'scroll_offset', new_callable=PropertyMock, return_value=Offset(0, 0)):
            conv.on_click(event)

        # Should have called _find_turn_for_line with content_y
        conv._find_turn_for_line.assert_called_once_with(0)


class TestNavigationNextPrev:
    """Test next/prev turn navigation (j/k keys)."""

    def test_select_next_turn_forward_finds_next_visible_turn(self):
        """select_next_turn(forward=True) should select next visible turn."""
        conv = ConversationView()

        # Add three turns (middle one empty/filtered)
        td0 = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="First", indent="")],
            strips=[Strip.blank(80)],
        )
        td0.line_offset = 0

        td1 = TurnData(
            turn_index=1,
            blocks=[],
            strips=[],  # Empty - filtered out
        )
        td1.line_offset = 1

        td2 = TurnData(
            turn_index=2,
            blocks=[TextContentBlock(text="Third", indent="")],
            strips=[Strip.blank(80)],
        )
        td2.line_offset = 1

        conv._turns.extend([td0, td1, td2])
        conv._total_lines = 2

        conv.refresh_lines = MagicMock()
        conv.scroll_to = MagicMock()

        # Select turn 0, then move forward
        conv.select_turn(0)
        conv.select_next_turn(forward=True)

        # Should skip turn 1 (empty) and select turn 2
        assert conv._selected_turn == 2

    def test_select_next_turn_backward_finds_prev_visible_turn(self):
        """select_next_turn(forward=False) should select previous visible turn."""
        conv = ConversationView()

        # Add three turns (middle one empty)
        td0 = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="First", indent="")],
            strips=[Strip.blank(80)],
        )
        td0.line_offset = 0

        td1 = TurnData(
            turn_index=1,
            blocks=[],
            strips=[],  # Empty
        )
        td1.line_offset = 1

        td2 = TurnData(
            turn_index=2,
            blocks=[TextContentBlock(text="Third", indent="")],
            strips=[Strip.blank(80)],
        )
        td2.line_offset = 1

        conv._turns.extend([td0, td1, td2])
        conv._total_lines = 2

        conv.refresh_lines = MagicMock()
        conv.scroll_to = MagicMock()

        # Select turn 2, then move backward
        conv.select_turn(2)
        conv.select_next_turn(forward=False)

        # Should skip turn 1 and select turn 0
        assert conv._selected_turn == 0

    def test_select_next_turn_no_selection_picks_first_or_last(self):
        """select_next_turn with no selection should pick first (forward) or last (backward)."""
        conv = ConversationView()

        # Add two turns
        for i in range(2):
            td = TurnData(
                turn_index=i,
                blocks=[TextContentBlock(text=f"Turn {i}", indent="")],
                strips=[Strip.blank(80)],
            )
            td.line_offset = i
            conv._turns.append(td)
        conv._total_lines = 2

        conv.refresh_lines = MagicMock()
        conv.scroll_to = MagicMock()

        # Forward with no selection
        conv.select_next_turn(forward=True)
        assert conv._selected_turn == 0

        # Clear selection and go backward
        conv._selected_turn = None
        conv.select_next_turn(forward=False)
        assert conv._selected_turn == 1

    def test_select_next_turn_disables_follow_mode(self):
        """Navigation should disable follow mode."""
        conv = ConversationView()
        conv._follow_mode = True

        # Add a turn
        td = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="Hello", indent="")],
            strips=[Strip.blank(80)],
        )
        td.line_offset = 0
        conv._turns.append(td)
        conv._total_lines = 1

        conv.refresh_lines = MagicMock()
        conv.scroll_to = MagicMock()

        conv.select_next_turn(forward=True)

        assert conv._follow_mode is False


class TestNavigationToolTurns:
    """Test next/prev tool turn navigation (n/N keys)."""

    def test_next_tool_turn_finds_turns_with_tool_blocks(self):
        """next_tool_turn should find turns containing ToolUseBlock, ToolResultBlock, or StreamToolUseBlock."""
        conv = ConversationView()

        # Turn 0: text only
        td0 = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="No tools", indent="")],
            strips=[Strip.blank(80)],
        )
        td0.line_offset = 0

        # Turn 1: has tool
        td1 = TurnData(
            turn_index=1,
            blocks=[
                TextContentBlock(text="Using tool", indent=""),
                ToolUseBlock(name="read_file", input_size=100, msg_color_idx=0),
            ],
            strips=[Strip.blank(80), Strip.blank(80)],
        )
        td1.line_offset = 1

        # Turn 2: text only
        td2 = TurnData(
            turn_index=2,
            blocks=[TextContentBlock(text="No tools", indent="")],
            strips=[Strip.blank(80)],
        )
        td2.line_offset = 3

        conv._turns.extend([td0, td1, td2])
        conv._total_lines = 4

        conv.refresh_lines = MagicMock()
        conv.scroll_to = MagicMock()

        # Start at turn 0, jump to next tool turn
        conv.select_turn(0)
        conv.next_tool_turn(forward=True)

        # Should select turn 1 (has tool)
        assert conv._selected_turn == 1

    def test_next_tool_turn_backward(self):
        """next_tool_turn(forward=False) should find previous tool turn."""
        conv = ConversationView()

        # Turn 0: has tool
        td0 = TurnData(
            turn_index=0,
            blocks=[ToolResultBlock(size=100, is_error=False, msg_color_idx=0)],
            strips=[Strip.blank(80)],
        )
        td0.line_offset = 0

        # Turn 1: text only
        td1 = TurnData(
            turn_index=1,
            blocks=[TextContentBlock(text="No tools", indent="")],
            strips=[Strip.blank(80)],
        )
        td1.line_offset = 1

        # Turn 2: has tool
        td2 = TurnData(
            turn_index=2,
            blocks=[StreamToolUseBlock(name="test")],
            strips=[Strip.blank(80)],
        )
        td2.line_offset = 2

        conv._turns.extend([td0, td1, td2])
        conv._total_lines = 3

        conv.refresh_lines = MagicMock()
        conv.scroll_to = MagicMock()

        # Start at turn 2, jump to previous tool turn
        conv.select_turn(2)
        conv.next_tool_turn(forward=False)

        # Should select turn 0 (has tool)
        assert conv._selected_turn == 0

    def test_next_tool_turn_wraps_to_first_when_at_end(self):
        """next_tool_turn should wrap to first tool turn when at end."""
        conv = ConversationView()

        # Turn 0: has tool
        td0 = TurnData(
            turn_index=0,
            blocks=[ToolUseBlock(name="test", input_size=10, msg_color_idx=0)],
            strips=[Strip.blank(80)],
        )
        td0.line_offset = 0

        # Turn 1: has tool
        td1 = TurnData(
            turn_index=1,
            blocks=[ToolResultBlock(size=50, is_error=False, msg_color_idx=0)],
            strips=[Strip.blank(80)],
        )
        td1.line_offset = 1

        conv._turns.extend([td0, td1])
        conv._total_lines = 2

        conv.refresh_lines = MagicMock()
        conv.scroll_to = MagicMock()

        # Start at turn 1 (last tool turn), jump forward
        conv.select_turn(1)
        conv.next_tool_turn(forward=True)

        # Should wrap to turn 0
        assert conv._selected_turn == 0


class TestNavigationJumpFirstLast:
    """Test jump to first/last turn (g/G keys)."""

    def test_jump_to_first_selects_first_visible_turn(self):
        """jump_to_first() should select first visible turn."""
        conv = ConversationView()

        # Turn 0: empty
        td0 = TurnData(
            turn_index=0,
            blocks=[],
            strips=[],
        )
        td0.line_offset = 0

        # Turn 1: visible
        td1 = TurnData(
            turn_index=1,
            blocks=[TextContentBlock(text="First visible", indent="")],
            strips=[Strip.blank(80)],
        )
        td1.line_offset = 0

        conv._turns.extend([td0, td1])
        conv._total_lines = 1

        conv.refresh_lines = MagicMock()
        conv.scroll_to = MagicMock()

        conv.jump_to_first()

        # Should select turn 1 (first visible)
        assert conv._selected_turn == 1

    def test_jump_to_last_selects_last_visible_turn(self):
        """jump_to_last() should select last visible turn."""
        conv = ConversationView()

        # Turn 0: visible
        td0 = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="First", indent="")],
            strips=[Strip.blank(80)],
        )
        td0.line_offset = 0

        # Turn 1: visible (last)
        td1 = TurnData(
            turn_index=1,
            blocks=[TextContentBlock(text="Last visible", indent="")],
            strips=[Strip.blank(80)],
        )
        td1.line_offset = 1

        # Turn 2: empty
        td2 = TurnData(
            turn_index=2,
            blocks=[],
            strips=[],
        )
        td2.line_offset = 2

        conv._turns.extend([td0, td1, td2])
        conv._total_lines = 2

        conv.refresh_lines = MagicMock()
        conv.scroll_end = MagicMock()

        conv.jump_to_last()

        # Should select turn 1 (last visible)
        assert conv._selected_turn == 1

    def test_jump_to_first_disables_follow_mode(self):
        """jump_to_first() should disable follow mode."""
        conv = ConversationView()
        conv._follow_mode = True

        # Add a turn
        td = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="Hello", indent="")],
            strips=[Strip.blank(80)],
        )
        td.line_offset = 0
        conv._turns.append(td)
        conv._total_lines = 1

        conv.refresh_lines = MagicMock()
        conv.scroll_to = MagicMock()

        conv.jump_to_first()

        assert conv._follow_mode is False

    def test_jump_to_last_re_enables_follow_mode(self):
        """jump_to_last() should re-enable follow mode."""
        conv = ConversationView()
        conv._follow_mode = False

        # Add a turn
        td = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="Hello", indent="")],
            strips=[Strip.blank(80)],
        )
        td.line_offset = 0
        conv._turns.append(td)
        conv._total_lines = 1

        conv.refresh_lines = MagicMock()
        conv.scroll_end = MagicMock()

        conv.jump_to_last()

        assert conv._follow_mode is True


class TestStatePersistence:
    """Test state persistence for follow_mode and selected_turn."""

    def test_get_state_includes_follow_mode(self):
        """get_state() should include follow_mode."""
        conv = ConversationView()
        conv._follow_mode = False

        state = conv.get_state()

        assert "follow_mode" in state
        assert state["follow_mode"] is False

    def test_get_state_includes_selected_turn(self):
        """get_state() should include selected_turn."""
        conv = ConversationView()

        # Add a turn and select it
        td = TurnData(
            turn_index=0,
            blocks=[TextContentBlock(text="Hello", indent="")],
            strips=[Strip.blank(80)],
        )
        td.line_offset = 0
        conv._turns.append(td)
        conv._total_lines = 1

        conv.refresh_lines = MagicMock()
        conv.select_turn(0)

        state = conv.get_state()

        assert "selected_turn" in state
        assert state["selected_turn"] == 0

    def test_restore_state_restores_follow_mode(self):
        """restore_state() should restore follow_mode."""
        conv = ConversationView()
        conv._follow_mode = True

        state = {"follow_mode": False, "selected_turn": None, "all_blocks": []}
        conv.restore_state(state)

        assert conv._follow_mode is False

    def test_restore_state_restores_selected_turn(self):
        """restore_state() should restore selected_turn."""
        conv = ConversationView()
        conv._selected_turn = None

        state = {"follow_mode": True, "selected_turn": 5, "all_blocks": []}
        conv.restore_state(state)

        assert conv._selected_turn == 5
