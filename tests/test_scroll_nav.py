"""Unit tests for scroll and follow-mode features.

Tests the scroll components:
- Follow mode (auto-scroll to bottom on new content)
- State persistence (follow_mode)

Turn selection (j/k/n/N/g/G) was removed as part of the 3-Level visibility system.
"""

from unittest.mock import patch, PropertyMock, MagicMock

from cc_dump.tui.widget_factory import ConversationView


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


class TestStatePersistence:
    """Test state persistence for follow_mode."""

    def test_get_state_includes_follow_mode(self):
        """get_state() should include follow_mode."""
        conv = ConversationView()
        conv._follow_mode = False

        state = conv.get_state()

        assert "follow_mode" in state
        assert state["follow_mode"] is False

    def test_restore_state_restores_follow_mode(self):
        """restore_state() should restore follow_mode."""
        conv = ConversationView()
        conv._follow_mode = True

        state = {"follow_mode": False, "all_blocks": []}
        conv.restore_state(state)

        assert conv._follow_mode is False
