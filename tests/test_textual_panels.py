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
    """Press ',' cycles intra-panel mode on the active panel."""
    async with run_app() as (pilot, app):
        # Cycle to economics panel (has breakdown mode)
        from cc_dump.tui.panel_registry import PANEL_ORDER

        econ_idx = PANEL_ORDER.index("economics")
        for _ in range(econ_idx):
            await press_and_settle(pilot, ".")
        assert is_panel_visible(app, "economics")

        # Get economics widget and check initial mode
        economics = app._get_economics()
        assert economics is not None
        assert economics._breakdown_mode is False

        # Press comma to toggle breakdown mode
        await press_and_settle(pilot, ",")
        assert economics._breakdown_mode is True

        # Press comma again to toggle back
        await press_and_settle(pilot, ",")
        assert economics._breakdown_mode is False


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
        assert app._view_store.get("active_launch_config_name") is not None

        # Footer widget exists and was hydrated
        footer = app._get_footer()
        assert footer is not None
