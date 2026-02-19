"""Visibility toggle tests using Textual in-process harness."""

import pytest

from cc_dump.formatting import VisState, HIDDEN, ALWAYS_VISIBLE
from tests.harness import (
    run_app,
    press_and_settle,
    get_vis_state,
    get_all_vis_states,
)

pytestmark = pytest.mark.textual

# Visibility state constants for testing
SUMMARY_COLLAPSED = VisState(True, False, False)
SUMMARY_EXPANDED = VisState(True, False, True)
FULL_COLLAPSED = VisState(True, True, False)
FULL_EXPANDED = VisState(True, True, True)


async def test_default_visibility_levels():
    """All 6 categories start at expected default levels."""
    async with run_app() as (pilot, app):
        states = get_all_vis_states(app)
        assert states["user"] == ALWAYS_VISIBLE
        assert states["assistant"] == ALWAYS_VISIBLE
        assert states["tools"] == SUMMARY_COLLAPSED
        assert states["system"] == SUMMARY_COLLAPSED
        assert states["metadata"] == HIDDEN
        assert states["thinking"] == SUMMARY_COLLAPSED


async def test_toggle_metadata_off_on():
    """Press '5' toggles metadata visibility: hidden -> visible -> hidden."""
    async with run_app() as (pilot, app):
        # Metadata starts hidden
        assert get_vis_state(app, "metadata") == HIDDEN

        # Toggle visible: should show at summary-collapsed
        await press_and_settle(pilot, "5")
        assert get_vis_state(app, "metadata") == SUMMARY_COLLAPSED

        # Toggle hidden: back to hidden
        await press_and_settle(pilot, "5")
        assert get_vis_state(app, "metadata") == HIDDEN


async def test_toggle_user_off_on():
    """Press '1' toggles user visibility: visible -> hidden -> visible."""
    async with run_app() as (pilot, app):
        # User starts visible at full-expanded
        assert get_vis_state(app, "user") == FULL_EXPANDED

        # Toggle hidden (preserves full and expanded state)
        await press_and_settle(pilot, "1")
        assert get_vis_state(app, "user") == VisState(False, True, True)

        # Toggle visible: restored to full-expanded
        await press_and_settle(pilot, "1")
        assert get_vis_state(app, "user") == FULL_EXPANDED


async def test_detail_toggle_shifts_summary_full():
    """Shift+5 (%) toggles detail between SUMMARY and FULL. Need to show metadata first."""
    async with run_app() as (pilot, app):
        # Metadata starts hidden. Show it first with '5'
        await press_and_settle(pilot, "5")
        assert get_vis_state(app, "metadata") == SUMMARY_COLLAPSED

        # Press %: toggle to FULL (preserves collapsed state)
        await press_and_settle(pilot, "%")
        assert get_vis_state(app, "metadata") == FULL_COLLAPSED

        # Press % again: toggle to SUMMARY (preserves collapsed state)
        await press_and_settle(pilot, "%")
        assert get_vis_state(app, "metadata") == SUMMARY_COLLAPSED

        # Press % again: toggle to FULL (preserves collapsed state)
        await press_and_settle(pilot, "%")
        assert get_vis_state(app, "metadata") == FULL_COLLAPSED


async def test_toggle_remembers_detail_level():
    """Visibility toggle preserves detail level independently."""
    async with run_app() as (pilot, app):
        # Tools start at summary-collapsed
        assert get_vis_state(app, "tools") == SUMMARY_COLLAPSED

        # Toggle detail to FULL with '#' (shift+3) - preserves collapsed
        await press_and_settle(pilot, "#")
        assert get_vis_state(app, "tools") == FULL_COLLAPSED

        # Hide with '3' (preserves full and collapsed)
        await press_and_settle(pilot, "3")
        assert get_vis_state(app, "tools") == VisState(False, True, False)

        # Show again with '3' — detail state preserved
        await press_and_settle(pilot, "3")
        assert get_vis_state(app, "tools") == FULL_COLLAPSED


@pytest.mark.parametrize(
    "key,category",
    [
        ("1", "user"),
        ("2", "assistant"),
        ("3", "tools"),
        ("4", "system"),
        ("5", "metadata"),
        ("6", "thinking"),
    ],
)
async def test_category_toggle(key, category):
    """Each number key toggles its category and restores on second press."""
    async with run_app() as (pilot, app):
        initial = get_vis_state(app, category)
        await press_and_settle(pilot, key)
        toggled = get_vis_state(app, category)
        # Should have changed
        assert toggled != initial, f"{category}: {initial} should change after pressing {key}"
        # Toggle back
        await press_and_settle(pilot, key)
        restored = get_vis_state(app, category)
        assert restored == initial, f"{category}: should restore to {initial}, got {restored}"


async def test_cycle_vis_five_state_cycle():
    """Click-to-cycle progresses through 5 states: hidden → summary-collapsed → summary-expanded → full-collapsed → full-expanded → hidden."""
    async with run_app() as (pilot, app):
        # Start with metadata hidden
        assert get_vis_state(app, "metadata") == HIDDEN

        # Cycle 1: Hidden → Summary Collapsed
        app.action_cycle_vis("metadata")
        assert get_vis_state(app, "metadata") == SUMMARY_COLLAPSED

        # Cycle 2: Summary Collapsed → Summary Expanded
        app.action_cycle_vis("metadata")
        assert get_vis_state(app, "metadata") == SUMMARY_EXPANDED

        # Cycle 3: Summary Expanded → Full Collapsed
        app.action_cycle_vis("metadata")
        assert get_vis_state(app, "metadata") == FULL_COLLAPSED

        # Cycle 4: Full Collapsed → Full Expanded
        app.action_cycle_vis("metadata")
        assert get_vis_state(app, "metadata") == FULL_EXPANDED

        # Cycle 5: Full Expanded → Hidden (wraps)
        app.action_cycle_vis("metadata")
        assert get_vis_state(app, "metadata") == HIDDEN


async def test_cycle_vis_all_categories():
    """cycle_vis works for all 6 categories and doesn't affect keyboard toggle behavior."""
    async with run_app() as (pilot, app):
        categories = ["user", "assistant", "tools", "system", "metadata", "thinking"]

        for cat in categories:
            initial = get_vis_state(app, cat)

            # Cycle once
            app.action_cycle_vis(cat)
            after_cycle = get_vis_state(app, cat)

            # State should have changed (different from initial)
            assert after_cycle != initial, f"{cat}: state should change after cycle_vis"

            # Cycling multiple times should cycle through states deterministically
            app.action_cycle_vis(cat)
            after_second = get_vis_state(app, cat)
            assert after_second != after_cycle, f"{cat}: second cycle should differ from first"


async def test_cycle_vis_clears_overrides_and_filterset():
    """cycle_vis clears per-block overrides and invalidates active filterset."""
    async with run_app() as (pilot, app):
        # Set a filterset slot
        app._active_filterset_slot = "1"

        # Cycle a category
        app.action_cycle_vis("tools")

        # Filterset should be invalidated (set to None)
        assert app._active_filterset_slot is None


async def test_next_filterset_applies_without_crash():
    """Pressing '=' applies next filterset and sets active slot."""
    async with run_app() as (pilot, app):
        assert app._active_filterset_slot is None

        # Apply next filterset via key press
        await press_and_settle(pilot, "=")

        # Should have set an active slot
        assert app._active_filterset_slot is not None

        # Visibility state should match the applied filterset defaults
        from cc_dump.settings import DEFAULT_FILTERSETS
        slot = app._active_filterset_slot
        expected = DEFAULT_FILTERSETS[slot]
        actual = get_all_vis_states(app)
        for cat, vs in expected.items():
            assert actual[cat] == vs, f"{cat}: expected {vs}, got {actual[cat]}"
