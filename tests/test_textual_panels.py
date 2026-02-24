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

    Regression: importing cc_dump.app.launch_config inside on_mount shadowed the
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


async def test_ai_workbench_panel_opens_and_qa_action_dispatches():
    """Workbench panel should open and dispatch scoped QA action."""
    import cc_dump.tui.side_channel_panel

    async with run_app() as (pilot, app):
        app.action_toggle_side_channel()
        await pilot.pause()
        assert app._view_store.get("panel:side_channel") is True
        assert app.screen.query(cc_dump.tui.side_channel_panel.SideChannelPanel)

        app.action_sc_preview_qa()
        await pilot.pause()
        assert app._view_store.get("sc:loading") is False
        assert app._view_store.get("sc:active_action") == ""
        assert app._view_store.get("sc:result_source") == "fallback"
        assert "scoped Q&A blocked" in app._view_store.get("sc:result_text")
        assert "error:" in app._view_store.get("sc:result_text")
        tabs = app._get_conv_tabs()
        assert tabs is not None
        assert tabs.active == app._workbench_tab_id
        workbench_results = app._get_workbench_results_view()
        assert workbench_results is not None
        state = workbench_results.get_state()
        assert state["context_session_id"] == "__default__"
        assert "context=__default__" in str(state["meta"])
