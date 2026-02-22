"""Hot-reload controller — widget replacement and module reload coordination.

// [LAW:one-way-deps] Depends on hot_reload, rendering, widget_factory, search. No upward deps.
// [LAW:locality-or-seam] All reload logic here — app.py keeps thin delegates.
// [LAW:single-enforcer] Debounce enforced via EventStream — callers just call start_file_watcher().

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
import cc_dump.settings_store
import cc_dump.view_store
import cc_dump.tui.launch_config_panel
import cc_dump.tui.side_channel_panel
import cc_dump.tui.search_controller
import cc_dump.tui.theme_controller
import cc_dump.tui.view_store_bridge
import cc_dump.tui.protocols
from cc_dump.tui.category_config import CATEGORY_CONFIG

from cc_dump.tui.panel_registry import PANEL_REGISTRY

from snarfx import EventStream

_DEBOUNCE_S = 2.0  # Quiet period before reload fires

_watcher_stream: EventStream | None = None


def _has_reloadable_changes(changes) -> bool:
    """True if any changed file is a reloadable module."""
    for _change_type, path in changes:
        if cc_dump.hot_reload.is_reloadable(path):
            return True
    return False


def _update_staleness(app) -> None:
    """Sync excluded-file staleness state to view store."""
    stale = cc_dump.hot_reload.get_stale_excluded()
    store = app._view_store
    old_stale = list(store.stale_files)
    if stale != old_stale:
        store.stale_files.clear()
        if stale:
            store.stale_files.extend(stale)


async def start_file_watcher(app) -> None:
    """Start OS-native file watcher. No-op if watchfiles unavailable.

    Wires two streams from the same source:
    1. reloadable changes → debounce → reload + replace widgets
    2. all changes → update staleness state (immediate, no debounce)
    """
    global _watcher_stream

    try:
        import watchfiles
    except ImportError:
        app._app_log("INFO", "watchfiles not installed — hot-reload disabled")
        return

    paths = cc_dump.hot_reload.get_watch_paths()
    if not paths:
        return

    stream: EventStream = EventStream()
    _watcher_stream = stream

    # Wire: reloadable file events → debounce → reload + replace widgets
    stream.filter(_has_reloadable_changes) \
          .debounce(_DEBOUNCE_S) \
          .subscribe(lambda _: app.call_later(_do_hot_reload, app))

    # Wire: all events → update staleness state (immediate, no debounce)
    stream.subscribe(lambda _: app.call_from_thread(_update_staleness, app))

    app._app_log("INFO", f"File watcher started on {len(paths)} path(s)")

    # Consume watchfiles async iterator — runs forever until app exits
    async for changes in watchfiles.awatch(*paths):
        stream.emit(changes)


async def _do_hot_reload(app) -> None:
    """Execute the actual reload after debounce settles."""
    try:
        reloaded_modules = cc_dump.hot_reload.check_and_get_reloaded()
    except Exception as e:
        app.notify(f"[hot-reload] error reloading: {e}", severity="error")
        app._app_log("ERROR", f"Hot-reload error reloading: {e}")
        return

    if not reloaded_modules:
        return

    app._app_log("INFO", f"Hot-reload: {', '.join(reloaded_modules)}")

    # // [LAW:one-source-of-truth] Identity fields (phase, query, modes, cursor_pos)
    # live in the view store — they survive reconcile() automatically.
    # Only transient fields (matches, expanded_blocks, debounce_timer) need reset.
    SearchPhase = cc_dump.tui.search.SearchPhase
    old_search = app._search_state
    search_was_active = old_search.phase != SearchPhase.INACTIVE

    # Cancel debounce timer and clear expansion overrides on old blocks
    if old_search.debounce_timer is not None:
        old_search.debounce_timer.stop()
    if search_was_active:
        cc_dump.tui.search_controller.clear_search_expand(app)

    # Fresh SearchState connected to same store — identity fields survive,
    # transient fields get fresh defaults
    app._search_state = cc_dump.tui.search.SearchState(app._view_store)
    bar = app._get_search_bar()
    if bar is not None:
        bar.display = False

    # Rebuild theme state after modules reload (before any rendering)
    cc_dump.tui.rendering.set_theme(app.current_theme)
    cc_dump.tui.theme_controller.apply_markdown_theme(app)

    # Reconcile settings store (values survive, reactions re-register)
    settings_store = getattr(app, "_settings_store", None)
    if settings_store is not None:
        try:
            settings_store.reconcile(
                cc_dump.settings_store.SCHEMA,
                lambda store: cc_dump.settings_store.setup_reactions(
                    store, getattr(app, "_store_context", None)
                ),
            )
        except Exception as e:
            app._app_log("ERROR", f"Hot-reload: settings store reconcile failed: {e}")

    # Reconcile view store (values survive, autorun re-registers)
    view_store = getattr(app, "_view_store", None)
    if view_store is not None:
        try:
            # Rebuild bridge context with freshly-reloaded module functions
            ctx = getattr(app, "_store_context", None)
            if ctx is not None:
                ctx.update(cc_dump.tui.view_store_bridge.build_reaction_context(app))
            view_store.reconcile(
                cc_dump.view_store.SCHEMA,
                lambda store: cc_dump.view_store.setup_reactions(store, ctx),
            )
        except Exception as e:
            app._app_log("ERROR", f"Hot-reload: view store reconcile failed: {e}")

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

    # Restore search after successful widget replacement.
    # Identity fields (query, modes, cursor_pos, phase) already in store.
    if search_was_active and app._search_state.query:
        state = app._search_state
        saved_phase = state.phase

        # Capture fresh filter state and scroll position from new widgets
        store = app._view_store
        state.saved_filters = {
            name: (
                store.get(f"vis:{name}"),
                store.get(f"full:{name}"),
                store.get(f"exp:{name}"),
            )
            for _, name, _, _ in CATEGORY_CONFIG
        }
        conv = app._get_conv()
        state.saved_scroll_y = conv.scroll_offset.y if conv is not None else None

        # Re-execute search against fresh blocks
        cc_dump.tui.search_controller.run_search(app)

        # Navigate if we were navigating and have results
        if saved_phase == SearchPhase.NAVIGATING and state.matches:
            cc_dump.tui.search_controller.navigate_to_current(app)

        cc_dump.tui.search_controller.update_search_bar(app)


async def replace_all_widgets(app) -> None:
    """Replace all widgets with fresh instances from the reloaded factory.

    Uses create-before-remove pattern: all new widgets are created and
    state-restored before any old widgets are touched. If creation fails,
    old widgets remain in the DOM and the app continues working.
    """
    if not app.is_running:
        return

    from snarfx import textual as stx
    with stx.pause(app):
        await _replace_all_widgets_inner(app)


async def _replace_all_widgets_inner(app) -> None:
    """Inner implementation of widget replacement.

    Strategy: Create all new widgets first (without IDs), then remove old
    widgets, then mount new ones with the correct IDs. The stx.pause() guard
    prevents any reaction from querying widgets during the gap.
    """
    from cc_dump.tui.app import _resolve_factory

    # 1. Capture state from old widgets
    old_conv = app._get_conv()
    old_logs = app._get_logs()
    old_info = app._get_info()
    old_footer = app._get_footer()

    if old_conv is None:
        return  # Widgets already missing — nothing to replace

    conv_state = old_conv.get_state()
    logs_state = old_logs.get_state() if old_logs else {}
    info_state = old_info.get_state() if old_info else {}

    # [LAW:one-source-of-truth] Capture cycling panel state from registry
    old_panels = {}
    panel_states = {}
    for spec in PANEL_REGISTRY:
        old_widget = app._get_panel(spec.name)
        old_panels[spec.name] = old_widget
        panel_states[spec.name] = old_widget.get_state() if old_widget else {}

    active_panel = app.active_panel
    logs_visible = old_logs.display if old_logs else app.show_logs
    info_visible = old_info.display if old_info else app.show_info

    # 2. Create ALL new widgets (without IDs yet — set after mounting).
    new_conv = cc_dump.tui.widget_factory.create_conversation_view(view_store=app._view_store, domain_store=app._domain_store)
    _validate_and_restore_widget_state(new_conv, conv_state, widget_name="ConversationView")

    # [LAW:one-source-of-truth] Create cycling panels from registry
    new_panels = {}
    for spec in PANEL_REGISTRY:
        factory = _resolve_factory(spec.factory)
        widget = factory()
        _validate_and_restore_widget_state(
            widget,
            panel_states[spec.name],
            widget_name=f"Panel:{spec.name}",
        )
        new_panels[spec.name] = widget

    new_logs = cc_dump.tui.widget_factory.create_logs_panel()
    _validate_and_restore_widget_state(new_logs, logs_state, widget_name="LogsPanel")

    new_info = cc_dump.tui.info_panel.create_info_panel()
    _validate_and_restore_widget_state(new_info, info_state, widget_name="InfoPanel")

    # Remove keys panel if mounted (stateless, no state transfer needed)
    for panel in app.screen.query(cc_dump.tui.keys_panel.KeysPanel):
        await panel.remove()

    # Remove settings panel if mounted (stateless, no state transfer needed)
    for panel in app.screen.query(cc_dump.tui.settings_panel.SettingsPanel):
        await panel.remove()
    app._view_store.set("panel:settings", False)

    # Remove launch config panel if mounted (stateless, no state transfer needed)
    for panel in app.screen.query(cc_dump.tui.launch_config_panel.LaunchConfigPanel):
        await panel.remove()
    app._view_store.set("panel:launch_config", False)

    # Remove side-channel panel if mounted (stateless, no state transfer needed)
    for panel in app.screen.query(cc_dump.tui.side_channel_panel.SideChannelPanel):
        await panel.remove()
    app._view_store.set("panel:side_channel", False)

    # 3. Remove old widgets
    await old_conv.remove()
    for spec in PANEL_REGISTRY:
        old_widget = old_panels[spec.name]
        if old_widget is not None:
            await old_widget.remove()
    if old_logs is not None:
        await old_logs.remove()
    if old_info is not None:
        await old_info.remove()
    if old_footer is not None:
        await old_footer.remove()

    # 4. Assign IDs, set visibility, and mount new widgets
    new_conv.id = app._conv_id
    new_logs.id = app._logs_id
    new_info.id = app._info_id

    for spec in PANEL_REGISTRY:
        w = new_panels[spec.name]
        w.id = app._panel_ids[spec.name]
        w.display = (spec.name == active_panel)

    new_logs.display = logs_visible
    new_info.display = info_visible

    header = app.query_one(Header)
    # Mount cycling panels in registry order
    prev_widget = header
    for spec in PANEL_REGISTRY:
        await app.mount(new_panels[spec.name], after=prev_widget)
        prev_widget = new_panels[spec.name]

    await app.mount(new_conv, after=prev_widget)
    await app.mount(new_logs, after=new_conv)
    await app.mount(new_info, after=new_logs)

    # StatusFooter is stateless — create fresh and hydrate from store
    new_footer = cc_dump.tui.custom_footer.StatusFooter()
    await app.mount(new_footer, after=new_info)
    new_footer.update_display(
        cc_dump.tui.view_store_bridge.enrich_footer_state(
            app._view_store.footer_state.get()
        )
    )

    # 5. Re-render with current filters
    new_conv.rerender(app.active_filters)
    _rehydrate_panels_from_store(app, new_panels)


def _rehydrate_panels_from_store(app, new_panels: dict[str, object]) -> None:
    """Rehydrate mounted panel data from canonical stores after widget swap.

    // [LAW:one-source-of-truth] Panel content is always derived from live stores.
    // [LAW:single-enforcer] Hot-reload panel hydration happens at this boundary.
    """
    analytics_store = getattr(app, "_analytics_store", None)
    domain_store = getattr(app, "_domain_store", None)
    app_state = getattr(app, "_app_state", {})

    stats_panel = new_panels.get("stats")
    if stats_panel is not None:
        stats_panel.refresh_from_store(analytics_store, domain_store=domain_store)

    economics_panel = new_panels.get("economics")
    if economics_panel is not None:
        economics_panel.refresh_from_store(analytics_store)

    timeline_panel = new_panels.get("timeline")
    if timeline_panel is not None:
        timeline_panel.refresh_from_store(analytics_store)

    session_panel = new_panels.get("session")
    if session_panel is not None:
        session_panel.refresh_session_state(
            session_id=getattr(app, "_session_id", None),
            last_message_time=app_state.get("last_message_time"),
        )


def _validate_and_restore_widget_state(widget, state: dict, *, widget_name: str) -> None:
    """Validate hot-swap protocol, then restore widget state.

    // [LAW:single-enforcer] One boundary validates hot-swap protocol adherence.
    // [LAW:one-source-of-truth] Protocol contract enforced by validate_widget_protocol().
    """
    try:
        cc_dump.tui.protocols.validate_widget_protocol(widget)
    except TypeError as exc:
        raise TypeError(
            f"Hot-reload widget protocol validation failed for {widget_name}: {exc}"
        ) from exc
    widget.restore_state(state)
