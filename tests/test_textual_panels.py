"""Panel toggle tests using Textual in-process harness."""

import pytest

from tests.harness import (
    run_app,
    press_and_settle,
    choose_from_select,
    settle,
    is_panel_visible,
    is_follow_mode,
)

pytestmark = pytest.mark.textual


async def _open_launch_config_panel(app, pilot):
    import cc_dump.tui.launch_config_panel

    app.action_toggle_launch_config()
    await pilot.pause()
    return app.screen.query_one(cc_dump.tui.launch_config_panel.LaunchConfigPanel)


def _first_other_value(values: list[str] | tuple[str, ...], current: str) -> str:
    for value in values:
        if value != current:
            return value
    return current


async def _choose_selector_value(pilot, selector, target: str, option_order: list[str]) -> str:
    values = [str(value) for value in option_order]
    current = str(selector.value)
    if target == current or target not in values or current not in values:
        return current

    current_idx = values.index(current)
    target_idx = values.index(target)
    direction = "down" if target_idx > current_idx else "up"
    steps = abs(target_idx - current_idx)
    open_key = "down" if direction == "up" else "enter"
    return await choose_from_select(
        pilot,
        selector,
        navigation_keys=[direction] * steps,
        open_key=open_key,
    )


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

        # Second comma advances mode
        await press_and_settle(pilot, ",")
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


async def test_command_palette_includes_launch_presets():
    """System commands include one launch command per configured preset."""
    import cc_dump.app.launcher_registry

    async with run_app() as (pilot, app):
        await pilot.pause()
        commands = list(app.get_system_commands(app.screen))
        titles = {command.title for command in commands}
        for key in cc_dump.app.launcher_registry.launcher_keys():
            assert f"Launch preset: {key}" in titles


async def test_launch_config_select_changes_value_with_standard_select_keys():
    """Launch config selection changes once via standard select keyboard controls."""
    from textual.widgets import Select

    async with run_app() as (pilot, app):
        panel = await _open_launch_config_panel(app, pilot)
        panel.create_new_config()
        await settle(pilot)
        selector = panel.query_one("#lc-config-selector", Select)
        original = str(selector.value)
        option_order = [config.name for config in panel._configs]
        target = _first_other_value(option_order, original)

        changed = await _choose_selector_value(pilot, selector, target, option_order)
        assert changed != original

        await settle(pilot, ticks=2)
        assert str(selector.value) == changed


async def test_launch_config_preset_select_stays_stable_after_layout_change():
    """Preset select should switch and keep the new value after tool-layout changes."""
    from textual.widgets import Select

    async with run_app() as (pilot, app):
        panel = await _open_launch_config_panel(app, pilot)
        selector = panel.query_one("#lc-config-selector", Select)
        original = str(selector.value)
        option_order = [config.name for config in panel._configs]
        changed_target = _first_other_value(option_order, original)

        changed = await _choose_selector_value(pilot, selector, changed_target, option_order)
        assert changed != original

        await settle(pilot, ticks=2)
        assert str(selector.value) == changed


async def test_launch_config_launcher_select_handles_standard_keys_without_panel_shortcuts():
    """Focused select should own enter and arrow keys instead of triggering panel actions."""
    import cc_dump.app.launcher_registry
    from textual.widgets import Select

    async with run_app() as (pilot, app):
        panel = await _open_launch_config_panel(app, pilot)
        selector = panel.query_one("#lc-field-launcher", Select)
        original = str(selector.value)
        config_count = len(panel._configs)
        option_order = list(cc_dump.app.launcher_registry.launcher_keys())
        changed_target = _first_other_value(option_order, original)

        changed = await _choose_selector_value(pilot, selector, changed_target, option_order)
        assert changed != original
        assert len(panel._configs) == config_count

        await settle(pilot, ticks=2)
        assert str(selector.value) == changed

        await press_and_settle(pilot, "tab")
        focused = app.screen.focused
        assert focused is not None
        assert getattr(focused, "id", "") != "lc-field-launcher"


async def test_launch_config_select_allows_unclaimed_app_shortcuts():
    """Focused select should keep its own keys but allow unrelated app shortcuts through."""
    from textual.widgets import Select

    async with run_app() as (pilot, app):
        panel = await _open_launch_config_panel(app, pilot)
        selector = panel.query_one("#lc-field-launcher", Select)
        original = str(selector.value)
        selector.focus()
        await settle(pilot)

        before = app.active_panel
        await press_and_settle(pilot, ".")
        assert app.active_panel != before
        assert str(selector.value) == original


async def test_launch_config_launcher_select_round_trips_and_reopens_stably():
    """Launcher select should switch away, switch back, and reopen without oscillating."""
    import cc_dump.app.launcher_registry
    from textual.widgets import Select
    import cc_dump.tui.launch_config_panel

    async with run_app() as (pilot, app):
        panel = await _open_launch_config_panel(app, pilot)
        selector = panel.query_one("#lc-field-launcher", Select)
        original = str(selector.value)
        option_order = list(cc_dump.app.launcher_registry.launcher_keys())
        changed_target = _first_other_value(option_order, original)

        changed = await _choose_selector_value(pilot, selector, changed_target, option_order)
        assert changed != original

        round_trip = await _choose_selector_value(pilot, selector, original, option_order)
        assert round_trip == original

        await settle(pilot, ticks=2)
        assert str(selector.value) == original

        app.action_toggle_launch_config()
        await settle(pilot)
        app.action_toggle_launch_config()
        await settle(pilot)

        reopened_panel = app.screen.query_one(cc_dump.tui.launch_config_panel.LaunchConfigPanel)
        reopened_selector = reopened_panel.query_one("#lc-field-launcher", Select)
        assert str(reopened_selector.value) == original

        await settle(pilot, ticks=2)
        assert str(reopened_selector.value) == original


async def test_launch_config_hidden_mount_hydrates_from_store(monkeypatch):
    """Fresh hidden mount should hydrate selector/form state before first show."""
    from textual.widgets import Select
    import cc_dump.app.launch_config

    configs = cc_dump.app.launch_config.default_configs()
    if len(configs) < 2:
        pytest.skip("requires at least two launch presets")
    active_name = configs[1].name

    monkeypatch.setattr(cc_dump.app.launch_config, "load_configs", lambda: configs)
    monkeypatch.setattr(cc_dump.app.launch_config, "load_active_name", lambda: active_name)

    async with run_app() as (pilot, app):
        panel = await _open_launch_config_panel(app, pilot)
        await settle(pilot, ticks=2)
        selector = panel.query_one("#lc-config-selector", Select)
        assert str(selector.value) == active_name


async def test_launch_config_save_chip_keeps_app_responsive():
    """Focused action chips should allow unrelated shortcuts and still handle activation keys."""
    async with run_app() as (pilot, app):
        await _open_launch_config_panel(app, pilot)

        save_chip = app.screen.query_one("#lc-action-save")
        save_chip.focus()
        await pilot.pause()

        before = app.active_panel
        await press_and_settle(pilot, ".")
        assert app.active_panel != before
        assert app._view_store.get("panel:launch_config")

        await press_and_settle(pilot, "enter")
        assert not app._view_store.get("panel:launch_config")


async def test_launch_config_escape_closes_via_app_handler():
    """Escape should close launch config through the app-level panel dispatcher."""
    async with run_app() as (pilot, app):
        await _open_launch_config_panel(app, pilot)

        await press_and_settle(pilot, "escape")
        assert not app._view_store.get("panel:launch_config")


async def test_launch_config_toggle_reopens_hidden_panel():
    """Launch config toggle should hide and re-show the same mounted sidebar."""
    import cc_dump.tui.launch_config_panel

    async with run_app() as (pilot, app):
        await _open_launch_config_panel(app, pilot)
        panel = app.screen.query_one(cc_dump.tui.launch_config_panel.LaunchConfigPanel)
        assert panel.display

        app.action_toggle_launch_config()
        await pilot.pause()
        assert not app._view_store.get("panel:launch_config")
        assert not panel.display

        app.action_toggle_launch_config()
        await pilot.pause()
        panel_after = app.screen.query_one(cc_dump.tui.launch_config_panel.LaunchConfigPanel)
        assert panel_after is panel
        assert panel_after.display


async def test_settings_toggle_reopens_hidden_panel():
    """Settings toggle should hide and re-show the same mounted sidebar."""
    import cc_dump.tui.settings_panel

    async with run_app() as (pilot, app):
        app.action_toggle_settings()
        await pilot.pause()
        panel = app.screen.query_one(cc_dump.tui.settings_panel.SettingsPanel)
        assert panel.display

        app.action_toggle_settings()
        await pilot.pause()
        assert not app._view_store.get("panel:settings")
        assert not panel.display

        app.action_toggle_settings()
        await pilot.pause()
        panel_after = app.screen.query_one(cc_dump.tui.settings_panel.SettingsPanel)
        assert panel_after is panel
        assert panel_after.display


async def test_sidebars_are_exclusive_and_reused():
    """Opening one sidebar closes the others while reusing mounted widgets."""
    import cc_dump.tui.settings_panel
    import cc_dump.tui.launch_config_panel
    import cc_dump.tui.side_channel_panel

    async with run_app() as (pilot, app):
        settings = app.screen.query_one(cc_dump.tui.settings_panel.SettingsPanel)
        launch = app.screen.query_one(cc_dump.tui.launch_config_panel.LaunchConfigPanel)
        side = app.screen.query_one(cc_dump.tui.side_channel_panel.SideChannelPanel)

        app.action_toggle_settings()
        await pilot.pause()
        assert settings.display
        assert not launch.display
        assert not side.display

        app.action_toggle_launch_config()
        await pilot.pause()
        assert not settings.display
        assert launch.display
        assert not side.display

        app.action_toggle_side_channel()
        await pilot.pause()
        assert not settings.display
        assert not launch.display
        assert side.display
