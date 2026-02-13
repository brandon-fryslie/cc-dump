"""Hot-reload controller — widget replacement and module reload coordination.

// [LAW:one-way-deps] Depends on hot_reload, rendering, widget_factory, search. No upward deps.
// [LAW:locality-or-seam] All reload logic here — app.py keeps thin delegates.

Not hot-reloadable (mutates app widget tree).
"""

from textual.widgets import Header

import cc_dump.hot_reload
import cc_dump.tui.rendering
import cc_dump.tui.search
import cc_dump.tui.widget_factory
import cc_dump.tui.info_panel


async def check_hot_reload(app) -> None:
    """Check for file changes and reload modules if necessary."""
    try:
        reloaded_modules = cc_dump.hot_reload.check_and_get_reloaded()
    except Exception as e:
        app.notify(f"[hot-reload] error checking: {e}", severity="error")
        app._app_log("ERROR", f"Hot-reload error checking: {e}")
        return

    if not reloaded_modules:
        return

    # Notify user
    app.notify("[hot-reload] modules reloaded", severity="information")
    app._app_log("INFO", f"Hot-reload: {', '.join(reloaded_modules)}")

    # Cancel any active search on reload (state references may be stale)
    SearchPhase = cc_dump.tui.search.SearchPhase
    if app._search_state.phase != SearchPhase.INACTIVE:
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
    except Exception as e:
        app.notify(f"[hot-reload] error applying: {e}", severity="error")
        app._app_log("ERROR", f"Hot-reload error applying: {e}")


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

    if old_conv is None:
        return  # Widgets already missing — nothing to replace

    conv_state = old_conv.get_state()
    stats_state = old_stats.get_state() if old_stats else {}
    economics_state = old_economics.get_state() if old_economics else {}
    timeline_state = old_timeline.get_state() if old_timeline else {}
    logs_state = old_logs.get_state() if old_logs else {}
    info_state = old_info.get_state() if old_info else {}

    stats_visible = True  # stats always visible
    economics_visible = old_economics.display if old_economics else app.show_economics
    timeline_visible = old_timeline.display if old_timeline else app.show_timeline
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

    # 4. Assign IDs and mount new widgets
    new_conv.id = app._conv_id
    new_stats.id = app._stats_id
    new_economics.id = app._economics_id
    new_timeline.id = app._timeline_id
    new_logs.id = app._logs_id
    new_info.id = app._info_id

    new_stats.display = stats_visible
    new_economics.display = economics_visible
    new_timeline.display = timeline_visible
    new_logs.display = logs_visible
    new_info.display = info_visible

    header = app.query_one(Header)
    await app.mount(new_stats, after=header)
    await app.mount(new_conv, after=new_stats)
    await app.mount(new_economics, after=new_conv)
    await app.mount(new_timeline, after=new_economics)
    await app.mount(new_logs, after=new_timeline)
    await app.mount(new_info, after=new_logs)

    # 5. Re-render with current filters
    new_conv.rerender(app.active_filters)

    app.notify("[hot-reload] widgets replaced", severity="information")
