"""Tests for pure mode system and key dispatch.

Verifies that MODE_KEYMAP routes keys correctly per mode and that
mode transitions work as expected.
"""

import pytest

from tests.harness.app_runner import run_app


class TestNormalModeKeyDispatch:
    """Test key dispatch in NORMAL mode."""

    @pytest.fixture
    async def app_and_pilot(self):
        """Create app in test mode with scrollable content."""
        from tests.harness.builders import make_replay_data

        # Create enough messages to make content scrollable (20 turns)
        replay_data = make_replay_data(n=20)

        async with run_app(replay_data=replay_data) as (pilot, app):
            # Wait for replay to complete
            await pilot.pause()
            yield pilot, app

    async def test_navigation_j_scrolls(self, app_and_pilot):
        """Pressing 'j' scrolls down a line."""
        pilot, app = app_and_pilot
        conv = app._get_conv()
        if conv is None:
            pytest.skip("No conversation view")

        # Scroll to top first
        await pilot.press("g")
        await pilot.pause()

        initial_y = conv.scroll_y
        await pilot.press("j")
        await pilot.pause()

        # Should have scrolled down
        assert conv.scroll_y > initial_y

    async def test_filter_toggle_1_changes_user(self, app_and_pilot):
        """Pressing '1' toggles user visibility."""
        pilot, app = app_and_pilot
        initial = app._is_visible["user"]

        await pilot.press("1")
        await pilot.pause()

        # Should have toggled
        assert app._is_visible["user"] != initial

    async def test_theme_next_changes_theme(self, app_and_pilot):
        """Pressing ']' cycles to next theme."""
        pilot, app = app_and_pilot
        original = app.theme

        await pilot.press("]")
        await pilot.pause()

        # Should have changed
        assert app.theme != original

    async def test_theme_prev_changes_theme(self, app_and_pilot):
        """Pressing '[' cycles to previous theme."""
        pilot, app = app_and_pilot
        original = app.theme

        await pilot.press("[")
        await pilot.pause()

        # Should have changed
        assert app.theme != original

    async def test_keys_panel_toggle(self, app_and_pilot):
        """Pressing '?' mounts keys panel, pressing again removes it."""
        pilot, app = app_and_pilot
        from cc_dump.tui.keys_panel import KeysPanel

        # Initially no keys panel
        assert not app.screen.query(KeysPanel)

        await pilot.press("?")
        await pilot.pause()

        # Panel should be mounted
        panels = app.screen.query(KeysPanel)
        assert len(panels) == 1

        await pilot.press("?")
        await pilot.pause()

        # Panel should be removed
        assert not app.screen.query(KeysPanel)

    async def test_dot_cycles_active_panel(self, app_and_pilot):
        """Pressing '.' cycles active_panel through stats → economics → timeline → stats."""
        pilot, app = app_and_pilot
        assert app.active_panel == "stats"

        await pilot.press(".")
        await pilot.pause()
        assert app.active_panel == "economics"

        await pilot.press(".")
        await pilot.pause()
        assert app.active_panel == "timeline"

        await pilot.press(".")
        await pilot.pause()
        assert app.active_panel == "stats"

class TestSearchModeGating:
    """Test that non-navigation keys are blocked during search modes."""

    @pytest.fixture
    async def app_and_pilot(self):
        """Create app in test mode with scrollable content."""
        from tests.harness.builders import make_replay_data

        # Create enough messages to make content scrollable (20 turns)
        replay_data = make_replay_data(n=20)

        async with run_app(replay_data=replay_data) as (pilot, app):
            await pilot.pause()
            yield pilot, app

    async def test_filter_blocked_during_search_nav(self, app_and_pilot):
        """During SEARCH_NAV, pressing '1' does NOT toggle filter."""
        pilot, app = app_and_pilot

        # Start search
        await pilot.press("/")
        await pilot.pause()

        # Commit (enter NAVIGATING mode)
        await pilot.press("enter")
        await pilot.pause()

        # Try to toggle filter
        initial_user = app._is_visible["user"]
        await pilot.press("1")
        await pilot.pause()

        # Filter should NOT have changed
        assert app._is_visible["user"] == initial_user

    async def test_theme_blocked_during_search_nav(self, app_and_pilot):
        """During SEARCH_NAV, pressing ']' does NOT change theme."""
        pilot, app = app_and_pilot

        # Start search
        await pilot.press("/")
        await pilot.pause()

        # Commit
        await pilot.press("enter")
        await pilot.pause()

        # Try to change theme
        original_theme = app.theme
        await pilot.press("]")
        await pilot.pause()

        # Theme should NOT have changed
        assert app.theme == original_theme

    async def test_navigation_works_during_search_nav(self, app_and_pilot):
        """During SEARCH_NAV, navigation keys (j/k) still work."""
        pilot, app = app_and_pilot
        conv = app._get_conv()
        if conv is None:
            pytest.skip("No conversation view")

        # Start search and commit
        await pilot.press("/")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        # Try navigation
        initial_y = conv.scroll_y
        await pilot.press("j")
        await pilot.pause()

        # Should still scroll
        assert conv.scroll_y > initial_y


class TestModeTransitions:
    """Test mode transitions via special keys."""

    @pytest.fixture
    async def app_and_pilot(self):
        """Create app in test mode."""
        async with run_app() as (pilot, app):
            yield pilot, app

    async def test_slash_enters_search_edit(self, app_and_pilot):
        """Pressing '/' transitions to SEARCH_EDIT mode."""
        pilot, app = app_and_pilot
        from cc_dump.tui.input_modes import InputMode

        # Initially NORMAL
        assert app._input_mode == InputMode.NORMAL

        await pilot.press("/")
        await pilot.pause()

        # Now SEARCH_EDIT
        assert app._input_mode == InputMode.SEARCH_EDIT

    async def test_enter_transitions_to_search_nav(self, app_and_pilot):
        """Pressing 'enter' in SEARCH_EDIT transitions to SEARCH_NAV."""
        pilot, app = app_and_pilot
        from cc_dump.tui.input_modes import InputMode

        # Start search
        await pilot.press("/")
        await pilot.pause()
        assert app._input_mode == InputMode.SEARCH_EDIT

        # Commit
        await pilot.press("enter")
        await pilot.pause()

        # Now SEARCH_NAV
        assert app._input_mode == InputMode.SEARCH_NAV

    async def test_escape_returns_to_normal(self, app_and_pilot):
        """Pressing 'escape' in search returns to NORMAL."""
        pilot, app = app_and_pilot
        from cc_dump.tui.input_modes import InputMode

        # Start and commit search
        await pilot.press("/")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app._input_mode == InputMode.SEARCH_NAV

        # Exit
        await pilot.press("escape")
        await pilot.pause()

        # Back to NORMAL
        assert app._input_mode == InputMode.NORMAL


class TestKeymapCompleteness:
    """Test that all action methods have corresponding keymap entries."""

    def test_all_actions_have_keymap_entries(self):
        """Verify MODE_KEYMAP covers all action methods (sanity check)."""
        from cc_dump.tui.input_modes import MODE_KEYMAP, InputMode

        # Collect all actions from NORMAL mode keymap (strip parameters)
        normal_keymap = MODE_KEYMAP[InputMode.NORMAL]
        mapped_actions = set()
        for action_str in normal_keymap.values():
            # Extract action name before '(' if present
            action_name = action_str.split("(")[0]
            mapped_actions.add(action_name)

        # Check that common actions are mapped
        expected_actions = {
            "go_top",
            "go_bottom",
            "scroll_down_line",
            "scroll_up_line",
            "toggle_vis",
            "toggle_detail",
            "cycle_panel",
            "cycle_panel_mode",
            "toggle_follow",
            "toggle_keys",
            "next_theme",
            "prev_theme",
        }

        missing = expected_actions - mapped_actions
        assert not missing, f"Actions missing from MODE_KEYMAP: {missing}"
