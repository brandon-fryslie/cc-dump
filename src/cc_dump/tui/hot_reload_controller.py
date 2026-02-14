"""Hot-reload controller — widget replacement and module reload coordination.

// [LAW:one-way-deps] Depends on hot_reload, rendering, widget_factory, search. No upward deps.
// [LAW:locality-or-seam] All reload logic here — app.py keeps thin delegates.
// [LAW:single-enforcer] Debounce enforced here — callers just call check_hot_reload().

Not hot-reloadable (mutates app widget tree).
"""

from textual.widgets import Header

import cc_dump.hot_reload
import cc_dump.tui.rendering
import cc_dump.tui.search
import cc_dump.tui.widget_factory
import cc_dump.tui.info_panel
import cc_dump.tui.keys_panel
import cc_dump.tui.settings_panel
import cc_dump.tui.custom_footer

_DEBOUNCE_S = 2.0  # Quiet period before reload fires


async def check_hot_reload(app) -> None:
    """Check for file changes; debounce before reloading.

    Uses has_changes() (cheap mtime scan, no side effects) to detect changes.
    On detection, resets a debounce timer. The actual reload only fires once
    no new changes arrive for _DEBOUNCE_S seconds.
    """
    try:
        changed = cc_dump.hot_reload.has_changes()
    except Exception as e:
        app.notify(f"[hot-reload] error checking: {e}", severity="error")
        app._app_log("ERROR", f"Hot-reload error checking: {e}")
        return

    # Check excluded files for staleness on every tick (cheap mtime scan)
    stale = cc_dump.hot_reload.get_stale_excluded()
    old_stale = getattr(app, "_stale_files", [])
    if stale != old_stale:
        app._stale_files = stale
        app._update_footer_state()

    if not changed:
        return

    # Cancel existing debounce timer if any
    timer = getattr(app, "_reload_debounce_timer", None)
    if timer is not None:
        timer.stop()

    # Schedule reload after quiet period
    app._reload_debounce_timer = app.set_timer(
        _DEBOUNCE_S, lambda: app.call_later(_do_hot_reload, app)
    )


async def _do_hot_reload(app) -> None:
    """Execute the actual reload after debounce settles."""
    app._reload_debounce_timer = None

    try:
        reloaded_modules = cc_dump.hot_reload.check_and_get_reloaded()
    except Exception as e:
        app.notify(f"[hot-reload] error reloading: {e}", severity="error")
        app._app_log("ERROR", f"Hot-reload error reloading: {e}")
        return

    if not reloaded_modules:
        return

    app._app_log("INFO", f"Hot-reload: {', '.join(reloaded_modules)}")

    # Save search scalars before resetting (stale matches/expanded_blocks are discarded)
    SearchPhase = cc_dump.tui.search.SearchPhase
    old_search = app._search_state
    search_was_active = old_search.phase != SearchPhase.INACTIVE
    saved_query = old_search.query
    saved_modes = old_search.modes
    saved_cursor_pos = old_search.cursor_pos
    saved_phase = old_search.phase

    # Cancel debounce timer and clear expansion overrides on old blocks
    if old_search.debounce_timer is not None:
        old_search.debounce_timer.stop()
    if search_was_active:
        from cc_dump.tui.search_controller import clear_search_expand
        clear_search_expand(app)

    # Reset to fresh state (matches, expanded_blocks, debounce_timer discarded)
    app._search_state = cc_dump.tui.search.SearchState()
    bar = app._get_search_bar()
    if bar is not None:
        bar.display = False

    # Rebuild theme state after modules reload (before any rendering)
    cc_dump.tui.rendering.set_theme(app.current_theme)
    from cc_dump.tui.theme_controller import apply_markdown_theme

    apply_markdown_theme(app)

    # Any file change triggers full widget replacement
    # // [LAW:dataflow-not-control-flow] Unconditional — all reloads take same path
    try:
        await replace_all_widgets(app)
        # Single consolidated notification
        app.notify(
            f"[hot-reload] {len(reloaded_modules)} modules updated",
            severity="information",
        )
    except Exception as e:
        app.notify(f"[hot-reload] error applying: {e}", severity="error")
        app._app_log("ERROR", f"Hot-reload error applying: {e}")
        return

    # Restore search state after successful widget replacement
    if search_was_active and saved_query:
        from cc_dump.tui.category_config import CATEGORY_CONFIG
        from cc_dump.tui.search_controller import (
            run_search,
            navigate_to_current,
            update_search_bar,
        )

        state = app._search_state
        state.query = saved_query
        state.modes = saved_modes
        state.cursor_pos = saved_cursor_pos

        # Capture fresh filter state and scroll position from new widgets
        state.saved_filters = {
            name: (
                app._is_visible[name],
                app._is_full[name],
                app._is_expanded[name],
            )
            for _, name, _, _ in CATEGORY_CONFIG
        }
        conv = app._get_conv()
        state.saved_scroll_y = conv.scroll_offset.y if conv is not None else None

        # Re-execute search against fresh blocks
        run_search(app)

        # Restore phase and navigate if we had results
        state.phase = saved_phase
        if saved_phase == SearchPhase.NAVIGATING and state.matches:
            navigate_to_current(app)

        update_search_bar(app)


async def replace_all_widgets(app) -> None:
    """Replace all widgets with fresh instances from the reloaded factory.

    Uses create-before-remove pattern: all new widgets are created and
    state-restored before any old widgets are touched. If creation fails,
    old widgets remain in the DOM and the app continues working.
    """
    if not app.is_running:
        return

    app._replacing_widgets = True
    try:
        await _replace_all_widgets_inner(app)
    finally:
        app._replacing_widgets = False


async def _replace_all_widgets_inner(app) -> None:
    """Inner implementation of widget replacement.

    Strategy: Create all new widgets first (without IDs), then remove old
    widgets, then mount new ones with the correct IDs. The _replacing_widgets
    flag prevents any code from querying widgets during the gap.
    """
    # 1. Capture state from old widgets
    old_conv = app._get_conv()
    old_stats = app._get_stats()
    old_economics = app._get_economics()
    old_timeline = app._get_timeline()
    old_logs = app._get_logs()
    old_info = app._get_info()
    old_footer = app._get_footer()

    if old_conv is None:
        return  # Widgets already missing — nothing to replace

    conv_state = old_conv.get_state()
    stats_state = old_stats.get_state() if old_stats else {}
    economics_state = old_economics.get_state() if old_economics else {}
    timeline_state = old_timeline.get_state() if old_timeline else {}
    logs_state = old_logs.get_state() if old_logs else {}
    info_state = old_info.get_state() if old_info else {}

    active_panel = app.active_panel
    logs_visible = old_logs.display if old_logs else app.show_logs
    info_visible = old_info.display if old_info else app.show_info

    # 2. Create ALL new widgets (without IDs yet — set after mounting).
    new_conv = cc_dump.tui.widget_factory.create_conversation_view()
    new_conv.restore_state(conv_state)

    new_stats = cc_dump.tui.widget_factory.create_stats_panel()
    new_stats.restore_state(stats_state)

    new_economics = cc_dump.tui.widget_factory.create_economics_panel()
    new_economics.restore_state(economics_state)

    new_timeline = cc_dump.tui.widget_factory.create_timeline_panel()
    new_timeline.restore_state(timeline_state)

    new_logs = cc_dump.tui.widget_factory.create_logs_panel()
    new_logs.restore_state(logs_state)

    new_info = cc_dump.tui.info_panel.create_info_panel()
    new_info.restore_state(info_state)

    # Remove keys panel if mounted (stateless, no state transfer needed)
    for panel in app.screen.query(cc_dump.tui.keys_panel.KeysPanel):
        await panel.remove()

    # Remove settings panel if mounted (stateless, no state transfer needed)
    for panel in app.screen.query(cc_dump.tui.settings_panel.SettingsPanel):
        await panel.remove()
    app._settings_panel_open = False

    # 3. Remove old widgets
    await old_conv.remove()
    if old_stats is not None:
        await old_stats.remove()
    if old_economics is not None:
        await old_economics.remove()
    if old_timeline is not None:
        await old_timeline.remove()
    if old_logs is not None:
        await old_logs.remove()
    if old_info is not None:
        await old_info.remove()
    if old_footer is not None:
        await old_footer.remove()

    # 4. Assign IDs and mount new widgets
    new_conv.id = app._conv_id
    new_stats.id = app._stats_id
    new_economics.id = app._economics_id
    new_timeline.id = app._timeline_id
    new_logs.id = app._logs_id
    new_info.id = app._info_id

    from cc_dump.tui.action_handlers import PANEL_ORDER
    # [LAW:one-source-of-truth] Panel visibility driven by PANEL_ORDER, not hardcoded names
    _panel_widgets = {"stats": new_stats, "economics": new_economics, "timeline": new_timeline}
    for _name in PANEL_ORDER:
        _panel_widgets[_name].display = (active_panel == _name)
    new_logs.display = logs_visible
    new_info.display = info_visible

    header = app.query_one(Header)
    await app.mount(new_stats, after=header)
    await app.mount(new_economics, after=new_stats)
    await app.mount(new_timeline, after=new_economics)
    await app.mount(new_conv, after=new_timeline)
    await app.mount(new_logs, after=new_conv)
    await app.mount(new_info, after=new_logs)

    # StatusFooter is stateless — create fresh and push current visibility state
    new_footer = cc_dump.tui.custom_footer.StatusFooter()
    await app.mount(new_footer, after=new_info)
    app._update_footer_state()

    # 5. Re-render with current filters
    new_conv.rerender(app.active_filters)
