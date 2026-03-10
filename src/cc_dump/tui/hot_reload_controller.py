"""Hot-reload controller — widget replacement and module reload coordination.

// [LAW:one-way-deps] Depends on hot_reload, rendering, widget_factory, search. No upward deps.
// [LAW:locality-or-seam] All reload logic here — app.py keeps thin delegates.
// [LAW:single-enforcer] Debounce enforced via EventStream — callers just call start_file_watcher().

Not hot-reloadable (mutates app widget tree).
"""

from dataclasses import dataclass
from textual.widgets import Header
from typing import Protocol, cast

import cc_dump.app.hot_reload
import cc_dump.tui.rendering
import cc_dump.tui.search
import cc_dump.tui.widget_factory
import cc_dump.tui.info_panel
import cc_dump.tui.keys_panel
import cc_dump.tui.debug_settings_panel
import cc_dump.tui.settings_panel
import cc_dump.tui.custom_footer
import cc_dump.app.settings_store
import cc_dump.app.view_store
import cc_dump.tui.launch_config_panel
import cc_dump.tui.side_channel_panel
import cc_dump.tui.search_controller
import cc_dump.tui.theme_controller
import cc_dump.tui.protocols
import cc_dump.tui.category_config
import cc_dump.tui.panel_registry

from snarfx import EventStream

_DEBOUNCE_S = 2.0  # Quiet period before reload fires

_watcher_stream: EventStream | None = None


class _ConversationWidget(Protocol):
    id: str | None
    parent: object

    async def remove(self) -> object:
        ...

    def get_state(self) -> dict:
        ...

    def restore_state(self, state: dict) -> None:
        ...

    def rerender(self, filters: dict) -> None:
        ...


@dataclass(frozen=True)
class _ConversationSwap:
    session_key: str
    conv_id: str
    conv: _ConversationWidget
    parent: object
    state: dict
    domain_store: object


@dataclass(frozen=True)
class _WidgetSwapSnapshot:
    conversations: list[_ConversationSwap]
    old_logs: object | None
    old_info: object | None
    old_footer: object | None
    logs_state: dict
    info_state: dict
    old_panels: dict[str, object | None]
    panel_states: dict[str, dict]
    active_panel: str
    logs_visible: bool
    info_visible: bool


def stop_file_watcher() -> None:
    """Dispose watcher stream subscribers and clear global reference."""
    global _watcher_stream
    if _watcher_stream is None:
        return
    try:
        _watcher_stream.dispose()
    finally:
        _watcher_stream = None


def _has_reloadable_changes(changes) -> bool:
    """True if any changed file is a reloadable module."""
    for _change_type, path in changes:
        if cc_dump.app.hot_reload.is_reloadable(path):
            return True
    return False


def _update_staleness(app) -> None:
    """Sync excluded-file staleness state to view store."""
    stale = cc_dump.app.hot_reload.get_stale_excluded()
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

    paths = cc_dump.app.hot_reload.get_watch_paths()
    if not paths:
        return

    # // [LAW:single-enforcer] Existing watcher stream is disposed here before rebind.
    stop_file_watcher()
    stream: EventStream = EventStream()
    _watcher_stream = stream

    # Wire: reloadable file events → debounce → reload + replace widgets
    def _on_debounce_fire(_):
        app._app_log("DEBUG", "Hot-reload: debounce fired, scheduling reload")
        app.call_later(_do_hot_reload, app)

    stream.filter(_has_reloadable_changes) \
          .debounce(_DEBOUNCE_S) \
          .subscribe(_on_debounce_fire)

    # Wire: all events → update staleness state (immediate, no debounce)
    # call_later (not call_from_thread) — subscriber runs on event loop via async for
    stream.subscribe(lambda _: app.call_later(_update_staleness, app))

    app._app_log("INFO", f"File watcher started on {len(paths)} path(s)")

    # Consume watchfiles async iterator — runs forever until app exits
    async for changes in watchfiles.awatch(*paths):
        stream.emit(changes)


async def _do_hot_reload(app) -> None:
    """Execute the actual reload after debounce settles."""
    app._app_log("DEBUG", "Hot-reload: _do_hot_reload entered")
    reloaded_modules = _reload_modules(app)
    if not reloaded_modules:
        app._app_log("DEBUG", "Hot-reload: no modules to reload, skipping")
        return

    app._app_log("INFO", f"Hot-reload: {', '.join(reloaded_modules)}")

    search_was_active = _reset_search_state_for_reload(app)
    _rebuild_theme_and_reconcile_stores(app)

    # Any file change triggers full widget replacement
    # // [LAW:dataflow-not-control-flow] Unconditional — all reloads take same path
    try:
        await replace_all_widgets(app)
        # Single consolidated notification
        app.notify(
            f"\\[hot-reload] {len(reloaded_modules)} modules updated",
            severity="information",
        )
    except Exception as e:
        app.notify(f"\\[hot-reload] error applying: {e}", severity="error")
        app._app_log("ERROR", f"Hot-reload error applying: {e}")
        return

    _restore_search_state_after_reload(app, search_was_active)


def _reload_modules(app) -> list[str]:
    """Reload modules and surface failures through app notifications."""
    try:
        return cc_dump.app.hot_reload.check_and_get_reloaded()
    except Exception as e:
        app.notify(f"\\[hot-reload] error reloading: {e}", severity="error")
        app._app_log("ERROR", f"Hot-reload error reloading: {e}")
        return []


def _reset_search_state_for_reload(app) -> bool:
    """Reset transient search state while preserving store-backed identity fields.

    // [LAW:one-source-of-truth] Search identity stays in view store; only transients reset.
    """
    SearchPhase = cc_dump.tui.search.SearchPhase
    old_search = app._search_state
    search_was_active = old_search.phase != SearchPhase.INACTIVE
    if old_search.debounce_timer is not None:
        old_search.debounce_timer.stop()

    app._search_state = cc_dump.tui.search.SearchState(app._view_store)
    bar = app._get_search_bar()
    if bar is not None:
        bar.display = False
    return search_was_active


def _rebuild_theme_and_reconcile_stores(app) -> None:
    """Rebuild runtime theme and reconcile reactive stores after module reload."""
    cc_dump.tui.rendering.set_theme(app.current_theme, runtime=app._render_runtime)
    cc_dump.tui.theme_controller.apply_markdown_theme(app)
    _reconcile_settings_store(app)
    _reconcile_view_store(app)


def _reconcile_settings_store(app) -> None:
    settings_store = getattr(app, "_settings_store", None)
    if settings_store is None:
        return
    try:
        settings_store.reconcile(
            cc_dump.app.settings_store.SCHEMA,
            lambda store: cc_dump.app.settings_store.setup_reactions(
                store, getattr(app, "_store_context", None)
            ),
        )
    except Exception as e:
        app._app_log("ERROR", f"Hot-reload: settings store reconcile failed: {e}")


def _reconcile_view_store(app) -> None:
    view_store = getattr(app, "_view_store", None)
    if view_store is None:
        return
    try:
        # // [LAW:locality-or-seam] App-owned context is passed directly to setup_reactions().
        ctx = getattr(app, "_store_context", None)
        view_store.reconcile(
            cc_dump.app.view_store.SCHEMA,
            lambda store: cc_dump.app.view_store.setup_reactions(store, ctx),
        )
    except Exception as e:
        app._app_log("ERROR", f"Hot-reload: view store reconcile failed: {e}")


def _restore_search_state_after_reload(app, search_was_active: bool) -> None:
    """Recompute search matches/state after widget replacement."""
    if not search_was_active or not app._search_state.query:
        return
    state = app._search_state
    store = app._view_store
    state.saved_filters = {
        name: (
            store.get(f"vis:{name}"),
            store.get(f"full:{name}"),
            store.get(f"exp:{name}"),
        )
        for _, name, _, _ in cc_dump.tui.category_config.CATEGORY_CONFIG
    }
    conv = app._get_conv()
    state.saved_scroll_y = conv.current_scroll_y() if conv is not None else None
    cc_dump.tui.search_controller.run_search(app)


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
    snapshot = _capture_widget_snapshot(app)
    if not snapshot.conversations:
        return

    new_conversations = _build_replacement_conversations(app, snapshot.conversations)
    new_panels = _build_replacement_panels(snapshot.panel_states)
    new_logs = _build_replacement_logs(snapshot.logs_state)
    new_info = _build_replacement_info(snapshot.info_state)

    await _remove_ephemeral_panels(app)
    await _remove_old_widgets(snapshot)
    await _mount_replacement_widgets(
        app,
        snapshot=snapshot,
        new_conversations=new_conversations,
        new_panels=new_panels,
        new_logs=new_logs,
        new_info=new_info,
    )

    for new_conv in new_conversations.values():
        new_conv.rerender(app.active_filters)
    if hasattr(app, "_get_active_domain_store"):
        # // [LAW:one-source-of-truth] _domain_store mirrors the active session store.
        app._domain_store = app._get_active_domain_store()


def _collect_conversation_swaps(app) -> list[_ConversationSwap]:
    """Collect existing conversation widgets and durable per-session state."""
    # // [LAW:one-source-of-truth] Conversation swap scope is owned by app._session_conv_ids.
    session_conv_ids = getattr(app, "_session_conv_ids", {})
    session_domain_stores = getattr(app, "_session_domain_stores", {})
    if not isinstance(session_conv_ids, dict) or not session_conv_ids:
        return []

    swaps: list[_ConversationSwap] = []
    for session_key, conv_id in session_conv_ids.items():
        old_conv = app._query_safe("#" + str(conv_id))
        if old_conv is None:
            continue
        if isinstance(session_domain_stores, dict):
            domain_store = session_domain_stores.get(
                session_key,
                getattr(app, "_domain_store", None),
            )
        else:
            domain_store = getattr(app, "_domain_store", None)
        conv_widget = cast(_ConversationWidget, old_conv)
        swaps.append(
            _ConversationSwap(
                session_key=str(session_key),
                conv_id=str(conv_id),
                conv=conv_widget,
                parent=conv_widget.parent,
                state=conv_widget.get_state(),
                domain_store=domain_store,
            )
        )
    return swaps


def _capture_widget_snapshot(app) -> _WidgetSwapSnapshot:
    """Capture old widgets, visibility, and serializable widget state."""
    old_conversations = _collect_conversation_swaps(app)
    old_logs = app._get_logs()
    old_info = app._get_info()
    old_footer = app._get_footer()
    logs_state = old_logs.get_state() if old_logs else {}
    info_state = old_info.get_state() if old_info else {}

    old_panels, panel_states = _capture_panel_swap_state(app)

    logs_visible = (
        old_logs.display
        if old_logs
        else bool(app._view_store.get("panel:logs"))
    )
    info_visible = (
        old_info.display
        if old_info
        else bool(app._view_store.get("panel:info"))
    )
    return _WidgetSwapSnapshot(
        conversations=old_conversations,
        old_logs=old_logs,
        old_info=old_info,
        old_footer=old_footer,
        logs_state=logs_state,
        info_state=info_state,
        old_panels=old_panels,
        panel_states=panel_states,
        active_panel=app.active_panel,
        logs_visible=logs_visible,
        info_visible=info_visible,
    )


def _capture_panel_swap_state(app) -> tuple[dict[str, object | None], dict[str, dict]]:
    """Capture mounted panel widgets/state using the app-owned panel ID map."""
    # [LAW:one-source-of-truth] Existing mounted panel IDs are owned by app._panel_ids.
    old_panels: dict[str, object | None] = {}
    panel_states: dict[str, dict] = {}
    panel_ids = getattr(app, "_panel_ids", {})
    if isinstance(panel_ids, dict):
        for name, css_id in panel_ids.items():
            if not isinstance(name, str) or not isinstance(css_id, str):
                continue
            old_widget = app._query_safe("#" + css_id)
            old_panels[name] = old_widget
            panel_states[name] = old_widget.get_state() if old_widget else {}
    # Ensure current registry names always have state entries for replacement creation.
    for spec in cc_dump.tui.panel_registry.PANEL_REGISTRY:
        panel_states.setdefault(spec.name, {})
    return old_panels, panel_states


def _build_replacement_conversations(
    app,
    payloads: list[_ConversationSwap],
) -> dict[str, _ConversationWidget]:
    new_conversations: dict[str, _ConversationWidget] = {}
    for payload in payloads:
        new_conv = cc_dump.tui.widget_factory.create_conversation_view(
            view_store=app._view_store,
            domain_store=payload.domain_store,
            runtime=app._render_runtime,
        )
        _validate_and_restore_widget_state(
            new_conv,
            payload.state,
            widget_name=f"ConversationView:{payload.session_key}",
        )
        new_conversations[payload.session_key] = cast(_ConversationWidget, new_conv)
    return new_conversations


def _build_replacement_panels(panel_states: dict[str, dict]) -> dict[str, object]:
    from cc_dump.tui.app import _resolve_factory

    # [LAW:one-source-of-truth] Create cycling panels from registry.
    new_panels: dict[str, object] = {}
    for spec in cc_dump.tui.panel_registry.PANEL_REGISTRY:
        factory = _resolve_factory(spec.factory)
        widget = factory()
        _validate_and_restore_widget_state(
            widget,
            panel_states.get(spec.name, {}),
            widget_name=f"Panel:{spec.name}",
        )
        new_panels[spec.name] = widget
    return new_panels


def _build_replacement_logs(logs_state: dict):
    new_logs = cc_dump.tui.widget_factory.create_logs_panel()
    _validate_and_restore_widget_state(new_logs, logs_state, widget_name="LogsPanel")
    return new_logs


def _build_replacement_info(info_state: dict):
    new_info = cc_dump.tui.info_panel.create_info_panel()
    _validate_and_restore_widget_state(new_info, info_state, widget_name="InfoPanel")
    return new_info


async def _remove_ephemeral_panels(app) -> None:
    """Drop transient overlays before remounting persisted widgets."""
    for ephemeral_panel_type in (
        cc_dump.tui.keys_panel.KeysPanel,
        cc_dump.tui.debug_settings_panel.DebugSettingsPanel,
    ):
        await _remove_panels_by_type(app, ephemeral_panel_type)

    removals = (
        (cc_dump.tui.settings_panel.SettingsPanel, "panel:settings"),
        (cc_dump.tui.launch_config_panel.LaunchConfigPanel, "panel:launch_config"),
        (cc_dump.tui.side_channel_panel.SideChannelPanel, "panel:side_channel"),
    )
    for removal_panel_type, store_key in removals:
        await _remove_panels_by_type(app, removal_panel_type)
        app._view_store.set(store_key, False)


async def _remove_panels_by_type(app, panel_type) -> None:
    for panel in app.screen.query(panel_type):
        await panel.remove()


async def _remove_old_widgets(snapshot: _WidgetSwapSnapshot) -> None:
    for payload in snapshot.conversations:
        await payload.conv.remove()
    # [LAW:dataflow-not-control-flow] Always process all captured panels, including
    # names removed from the current registry.
    for old_widget in snapshot.old_panels.values():
        if old_widget is not None:
            await old_widget.remove()
    if snapshot.old_logs is not None:
        await snapshot.old_logs.remove()
    if snapshot.old_info is not None:
        await snapshot.old_info.remove()
    if snapshot.old_footer is not None:
        await snapshot.old_footer.remove()


def _assign_replacement_identity(
    app,
    *,
    snapshot: _WidgetSwapSnapshot,
    new_conversations: dict[str, _ConversationWidget],
    new_panels: dict[str, object],
    new_logs,
    new_info,
) -> None:
    new_logs.id = app._logs_id
    new_logs.display = snapshot.logs_visible
    new_info.id = app._info_id
    new_info.display = snapshot.info_visible

    for payload in snapshot.conversations:
        new_conversations[payload.session_key].id = payload.conv_id

    _assign_panel_identity_from_registry(
        app,
        new_panels=new_panels,
        active_panel=snapshot.active_panel,
    )


def _assign_panel_identity_from_registry(
    app,
    *,
    new_panels: dict[str, object],
    active_panel: str,
) -> None:
    """Assign panel IDs/display from live registry and reconcile app panel ID map."""
    resolved_panel_ids: dict[str, str] = {}
    for spec in cc_dump.tui.panel_registry.PANEL_REGISTRY:
        panel = new_panels.get(spec.name)
        if panel is None:
            continue
        css_id = spec.css_id
        resolved_panel_ids[spec.name] = css_id
        panel.id = css_id
        panel.display = spec.name == active_panel
    # [LAW:one-source-of-truth] Registry-derived IDs are canonical after each reload.
    app._panel_ids = resolved_panel_ids


async def _mount_replacement_widgets(
    app,
    *,
    snapshot: _WidgetSwapSnapshot,
    new_conversations: dict[str, _ConversationWidget],
    new_panels: dict[str, object],
    new_logs,
    new_info,
) -> None:
    """Mount all replacement widgets in deterministic order."""
    _assign_replacement_identity(
        app,
        snapshot=snapshot,
        new_conversations=new_conversations,
        new_panels=new_panels,
        new_logs=new_logs,
        new_info=new_info,
    )

    header = app.query_one(Header)
    prev_widget = header
    for spec in cc_dump.tui.panel_registry.PANEL_REGISTRY:
        await app.mount(new_panels[spec.name], after=prev_widget)
        prev_widget = new_panels[spec.name]

    for payload in snapshot.conversations:
        await _mount_replacement_conversation(
            app,
            new_conversations[payload.session_key],
            prev_widget=prev_widget,
            old_conv_parent=payload.parent,
        )

    conv_tabs = app._get_conv_tabs() if hasattr(app, "_get_conv_tabs") else None
    mount_after = conv_tabs if conv_tabs is not None else prev_widget
    await app.mount(new_logs, after=mount_after)
    await app.mount(new_info, after=new_logs)

    new_footer = cc_dump.tui.custom_footer.StatusFooter()
    await app.mount(new_footer, after=new_info)

async def _mount_replacement_conversation(
    app,
    new_conv,
    *,
    prev_widget,
    old_conv_parent,
) -> None:
    """Mount replacement conversation view in its original parent container.

    // [LAW:locality-or-seam] Parent-aware mount is centralized here to enable
    // future tabbed/multi-container layouts without changing swap logic.
    """
    if old_conv_parent is app:
        await app.mount(new_conv, after=prev_widget)
        return
    if old_conv_parent is not None:
        await old_conv_parent.mount(new_conv)
        return
    await app.mount(new_conv, after=prev_widget)


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
