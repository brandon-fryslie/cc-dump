"""Unit tests for scroll and follow-mode features.

Tests the scroll components:
- Follow mode 3-state machine (OFF, ENGAGED, ACTIVE)
- State persistence (follow_state)
- Backward compatibility (old bool format)

Turn selection (j/k/n/N/g/G) was removed as part of the 3-Level visibility system.
"""

from unittest.mock import patch, PropertyMock, MagicMock

from cc_dump.tui.widget_factory import (
    ConversationView,
    FollowState,
    _FOLLOW_TOGGLE,
    _FOLLOW_TRANSITIONS,
    _FOLLOW_SCROLL_BOTTOM,
    _FOLLOW_DEACTIVATE,
)


class TestFollowMode:
    """Test follow mode 3-state machine."""

    def test_follow_mode_defaults_to_active(self):
        """ConversationView should start in ACTIVE state."""
        conv = ConversationView()
        assert conv._follow_state == FollowState.ACTIVE
        assert conv._is_following is True

    def test_toggle_from_active_goes_to_off(self):
        """toggle_follow() from ACTIVE should go to OFF."""
        conv = ConversationView()
        conv.scroll_end = MagicMock()

        conv.toggle_follow()
        assert conv._follow_state == FollowState.OFF
        assert conv._is_following is False
        conv.scroll_end.assert_not_called()

    def test_toggle_from_off_goes_to_active(self):
        """toggle_follow() from OFF should go to ACTIVE and scroll."""
        conv = ConversationView()
        conv._follow_state = FollowState.OFF
        conv.scroll_end = MagicMock()

        conv.toggle_follow()
        assert conv._follow_state == FollowState.ACTIVE
        assert conv._is_following is True
        conv.scroll_end.assert_called_once_with(animate=False)

    def test_toggle_from_engaged_goes_to_off(self):
        """toggle_follow() from ENGAGED should go to OFF."""
        conv = ConversationView()
        conv._follow_state = FollowState.ENGAGED
        conv.scroll_end = MagicMock()

        conv.toggle_follow()
        assert conv._follow_state == FollowState.OFF
        conv.scroll_end.assert_not_called()

    def test_scroll_away_from_active_goes_engaged(self):
        """User scroll away from bottom in ACTIVE should go to ENGAGED."""
        conv = ConversationView()
        assert conv._follow_state == FollowState.ACTIVE

        with patch.object(type(conv), 'is_vertical_scroll_end', new_callable=PropertyMock, return_value=False):
            conv.watch_scroll_y(100.0, 50.0)

        assert conv._follow_state == FollowState.ENGAGED

    def test_scroll_to_end_from_engaged_goes_active(self):
        """User scroll to bottom from ENGAGED should go to ACTIVE."""
        conv = ConversationView()
        conv._follow_state = FollowState.ENGAGED

        with patch.object(type(conv), 'is_vertical_scroll_end', new_callable=PropertyMock, return_value=True):
            conv.watch_scroll_y(50.0, 100.0)

        assert conv._follow_state == FollowState.ACTIVE

    def test_scroll_away_from_off_stays_off(self):
        """User scroll in OFF state should stay OFF."""
        conv = ConversationView()
        conv._follow_state = FollowState.OFF

        with patch.object(type(conv), 'is_vertical_scroll_end', new_callable=PropertyMock, return_value=False):
            conv.watch_scroll_y(100.0, 50.0)

        assert conv._follow_state == FollowState.OFF

    def test_scroll_to_end_from_off_stays_off(self):
        """User scroll to bottom in OFF state should stay OFF."""
        conv = ConversationView()
        conv._follow_state = FollowState.OFF

        with patch.object(type(conv), 'is_vertical_scroll_end', new_callable=PropertyMock, return_value=True):
            conv.watch_scroll_y(50.0, 100.0)

        assert conv._follow_state == FollowState.OFF

    def test_scroll_to_bottom_from_engaged_goes_active(self):
        """scroll_to_bottom() from ENGAGED should go to ACTIVE."""
        conv = ConversationView()
        conv._follow_state = FollowState.ENGAGED
        conv.scroll_end = MagicMock()

        conv.scroll_to_bottom()

        assert conv._follow_state == FollowState.ACTIVE
        conv.scroll_end.assert_called_once_with(animate=False)

    def test_scroll_to_bottom_from_off_stays_off(self):
        """scroll_to_bottom() from OFF should stay OFF (but still scroll)."""
        conv = ConversationView()
        conv._follow_state = FollowState.OFF
        conv.scroll_end = MagicMock()

        conv.scroll_to_bottom()

        assert conv._follow_state == FollowState.OFF
        conv.scroll_end.assert_called_once_with(animate=False)

    def test_scrolling_programmatically_guard_exists(self):
        """_scrolling_programmatically flag should exist and be used."""
        conv = ConversationView()
        assert conv._scrolling_programmatically is False

    def test_scrolling_programmatically_set_during_scroll_to_bottom(self):
        """scroll_to_bottom should set _scrolling_programmatically guard."""
        conv = ConversationView()
        conv._follow_state = FollowState.ENGAGED

        guard_states = []

        def mock_scroll_end(**kwargs):
            guard_states.append(conv._scrolling_programmatically)

        conv.scroll_end = mock_scroll_end
        conv.scroll_to_bottom()

        assert guard_states == [True]
        assert conv._scrolling_programmatically is False

    def test_watch_scroll_y_ignores_programmatic_scrolling(self):
        """watch_scroll_y should not change follow state when _scrolling_programmatically is True."""
        conv = ConversationView()
        conv._follow_state = FollowState.ACTIVE
        conv._scrolling_programmatically = True

        with patch.object(type(conv), 'is_vertical_scroll_end', new_callable=PropertyMock, return_value=False):
            conv.watch_scroll_y(100.0, 50.0)

        # Should remain ACTIVE (not ENGAGED)
        assert conv._follow_state == FollowState.ACTIVE


class TestFollowTransitionTables:
    """Test the transition tables are complete and correct."""

    def test_toggle_table_complete(self):
        """_FOLLOW_TOGGLE covers all states."""
        for state in FollowState:
            assert state in _FOLLOW_TOGGLE

    def test_transitions_table_complete(self):
        """_FOLLOW_TRANSITIONS covers all (state, bool) pairs."""
        for state in FollowState:
            for at_bottom in (True, False):
                assert (state, at_bottom) in _FOLLOW_TRANSITIONS

    def test_scroll_bottom_table_complete(self):
        """_FOLLOW_SCROLL_BOTTOM covers all states."""
        for state in FollowState:
            assert state in _FOLLOW_SCROLL_BOTTOM

    def test_deactivate_table_complete(self):
        """_FOLLOW_DEACTIVATE covers all states."""
        for state in FollowState:
            assert state in _FOLLOW_DEACTIVATE


class TestStatePersistence:
    """Test state persistence for follow_state."""

    def test_get_state_includes_follow_state(self):
        """get_state() should include follow_state as a string."""
        conv = ConversationView()
        conv._follow_state = FollowState.ENGAGED

        state = conv.get_state()

        assert "follow_state" in state
        assert state["follow_state"] == "engaged"

    def test_restore_state_restores_follow_state(self):
        """restore_state() should restore follow_state from string."""
        conv = ConversationView()

        state = {"follow_state": "off", "all_blocks": []}
        conv.restore_state(state)

        assert conv._follow_state == FollowState.OFF

    def test_restore_state_backward_compat_true(self):
        """restore_state() should handle old follow_mode=True format."""
        conv = ConversationView()
        conv._follow_state = FollowState.OFF

        state = {"follow_mode": True, "all_blocks": []}
        conv.restore_state(state)

        assert conv._follow_state == FollowState.ACTIVE

    def test_restore_state_backward_compat_false(self):
        """restore_state() should handle old follow_mode=False format."""
        conv = ConversationView()

        state = {"follow_mode": False, "all_blocks": []}
        conv.restore_state(state)

        assert conv._follow_state == FollowState.OFF

    def test_restore_state_defaults_to_active(self):
        """restore_state() with no follow key should default to ACTIVE."""
        conv = ConversationView()
        conv._follow_state = FollowState.OFF

        state = {"all_blocks": []}
        conv.restore_state(state)

        assert conv._follow_state == FollowState.ACTIVE
