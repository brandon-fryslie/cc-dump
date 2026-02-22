"""Panel toggle tests using Textual in-process harness."""

import pytest

from tests.harness import (
    run_app,
    press_and_settle,
    is_panel_visible,
    is_follow_mode,
)

pytestmark = pytest.mark.textual


async def test_panel_cycling_dot():
    """Press '.' cycles active panel through all registered panels."""
    from cc_dump.tui.panel_registry import PANEL_ORDER

    async with run_app() as (pilot, app):
        # First panel starts visible, rest hidden
        assert is_panel_visible(app, PANEL_ORDER[0])
        for name in PANEL_ORDER[1:]:
            assert not is_panel_visible(app, name)

        # Cycle through remaining panels
        for i in range(1, len(PANEL_ORDER)):
            await press_and_settle(pilot, ".")
            for j, name in enumerate(PANEL_ORDER):
                assert is_panel_visible(app, name) == (j == i)

        # One more press wraps back to first
        await press_and_settle(pilot, ".")
        assert is_panel_visible(app, PANEL_ORDER[0])
        for name in PANEL_ORDER[1:]:
            assert not is_panel_visible(app, name)


async def test_follow_mode_toggle():
    """Press 'f' toggles follow mode."""
    async with run_app() as (pilot, app):
        assert is_follow_mode(app)

        await press_and_settle(pilot, "f")
        assert not is_follow_mode(app)

        await press_and_settle(pilot, "f")
        assert is_follow_mode(app)


async def test_panel_mode_cycling_comma():
    """Press ',' and Tab cycles analytics dashboard views on the active panel."""
    async with run_app() as (pilot, app):
        # Cycle to stats/analytics panel (has summary/timeline/models modes)
        from cc_dump.tui.panel_registry import PANEL_ORDER

        stats_idx = PANEL_ORDER.index("stats")
        for _ in range(stats_idx):
            await press_and_settle(pilot, ".")
        assert is_panel_visible(app, "stats")

        stats = app._get_stats()
        assert stats is not None
        assert stats._view_index == 0

        # Comma advances mode
        await press_and_settle(pilot, ",")
        assert stats._view_index == 1

        # Tab also advances mode
        await press_and_settle(pilot, "tab")
        assert stats._view_index == 2

        # Wraps back to first mode
        await press_and_settle(pilot, ",")
        assert stats._view_index == 0


async def test_panels_initial_state():
    """First cycling panel starts visible, rest hidden, logs hidden."""
    from cc_dump.tui.panel_registry import PANEL_ORDER

    async with run_app() as (pilot, app):
        assert is_panel_visible(app, PANEL_ORDER[0])
        for name in PANEL_ORDER[1:]:
            assert not is_panel_visible(app, name)
        assert not is_panel_visible(app, "logs")


async def test_on_mount_seeds_footer_state():
    """on_mount must seed view store and hydrate footer without UnboundLocalError.

    Regression: importing cc_dump.launch_config inside on_mount shadowed the
    module-level `cc_dump` binding, causing UnboundLocalError on earlier lines
    that use cc_dump.tui.rendering etc.
    """
    async with run_app() as (pilot, app):
        # App started successfully (no UnboundLocalError in on_mount)
        assert app.is_running

        # Footer state was seeded — active_launch_config_name is in store
        assert app._view_store.get("launch:active_name") is not None

        # Footer widget exists and was hydrated
        footer = app._get_footer()
        assert footer is not None
