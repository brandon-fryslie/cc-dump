"""Action handlers for navigation, visibility, and panel toggles.

// [LAW:one-way-deps] Depends on formatting, rendering. No upward deps.
// [LAW:locality-or-seam] All action logic here — app.py keeps thin delegates.
// [LAW:one-type-per-behavior] Scroll actions are instances of _conv_action.

Hot-reloadable — imported as module object in app.py, all functions take app as param.
"""

import cc_dump.formatting
import cc_dump.settings
import cc_dump.tui.action_config  # module-style for hot-reload
import cc_dump.tui.rendering

# [LAW:one-source-of-truth] Panel order derived from registry
from cc_dump.tui.panel_registry import PANEL_ORDER
from snarfx import transaction
import cc_dump.tui.keys_panel
import cc_dump.tui.settings_panel
import cc_dump.tui.launch_config_panel
import cc_dump.tui.side_channel_panel
import cc_dump.tui.widget_factory


# ─── Visibility actions ────────────────────────────────────────────────


def _toggle_vis_dicts(app, category: str, spec_key: str) -> None:
    """// [LAW:one-type-per-behavior] Single function for all visibility mutations."""
    store = app._view_store
    # Clear overrides BEFORE transaction so autorun sees clean block state
    clear_overrides(app, category)
    app._view_store.set("filter:active", None)
    with transaction():
        for prefix, force in cc_dump.tui.action_config.VIS_TOGGLE_SPECS[spec_key]:
            key = f"{prefix}:{category}"
            current = store.get(key)
            store.set(key, (not current) if force is None else force)


def clear_overrides(app, category_name: str) -> None:
    """Reset per-block expanded overrides and content region states for a category.

    // [LAW:one-source-of-truth] Clears via ViewOverrides.clear_category() only.
    """
    cat = cc_dump.formatting.Category(category_name)
    conv = app._get_conv()
    if conv is None:
        return

    all_blocks = [block for td in conv._turns for block in td.blocks]
    conv._view_overrides.clear_category(all_blocks, cat)


def toggle_vis(app, category: str) -> None:
    _toggle_vis_dicts(app, category, "vis")


def toggle_detail(app, category: str) -> None:
    _toggle_vis_dicts(app, category, "detail")


def toggle_expand(app, category: str) -> None:
    _toggle_vis_dicts(app, category, "expand")


def cycle_vis(app, category: str) -> None:
    """Cycle category through 5 visibility states: hidden → summary → full.

    // [LAW:dataflow-not-control-flow] State progression driven by _VIS_CYCLE list.
    // [LAW:one-type-per-behavior] Single function for all category visibility cycling.
    """
    store = app._view_store
    # Get current state from store
    current = cc_dump.formatting.VisState(
        store.get(f"vis:{category}"),
        store.get(f"full:{category}"),
        store.get(f"exp:{category}"),
    )

    # Find index in cycle (default to -1 if state not found, wraps to 0)
    try:
        idx = cc_dump.tui.action_config.VIS_CYCLE.index(current)
    except ValueError:
        idx = -1

    # Compute next state with modulo wrap
    vis_cycle = cc_dump.tui.action_config.VIS_CYCLE
    next_idx = (idx + 1) % len(vis_cycle)
    next_state = vis_cycle[next_idx]

    # Clear per-block overrides and invalidate active filterset
    clear_overrides(app, category)
    app._view_store.set("filter:active", None)

    # Batch-set all three keys — single autorun fire
    with transaction():
        store.set(f"vis:{category}", next_state.visible)
        store.set(f"full:{category}", next_state.full)
        store.set(f"exp:{category}", next_state.expanded)


# ─── Panel cycling ─────────────────────────────────────────────────────

def cycle_panel(app) -> None:
    """Cycle active_panel through PANEL_ORDER."""
    current = app.active_panel
    idx = PANEL_ORDER.index(current) if current in PANEL_ORDER else -1
    next_idx = (idx + 1) % len(PANEL_ORDER)
    app.active_panel = PANEL_ORDER[next_idx]


def cycle_panel_mode(app) -> None:
    """Cycle intra-panel mode for the active panel."""
    panel = app._get_panel(app.active_panel)
    if panel is not None:
        panel.cycle_mode()


def refresh_active_panel(app, panel_name: str) -> None:
    """Refresh data for the named panel.

    // [LAW:one-type-per-behavior] Generic refresh via _get_panel + refresh_from_store.
    Session panel uses a separate refresh path (no analytics store).
    """
    if panel_name == "session":
        refresh_session(app)
        return
    if app._analytics_store is None:
        return
    panel = app._get_panel(panel_name)
    if panel is not None:
        panel.refresh_from_store(app._analytics_store)


def _toggle_panel(app, panel_key: str) -> None:
    """// [LAW:dataflow-not-control-flow] Panel toggling driven by config, not branches."""
    attr, getter_name, refresh_name = cc_dump.tui.action_config.PANEL_TOGGLE_CONFIG[panel_key]
    new_val = not getattr(app, attr)
    setattr(app, attr, new_val)
    widget = getattr(app, getter_name)()
    if widget is not None:
        widget.display = new_val
    # [LAW:dataflow-not-control-flow] refresh_name is None for panels without db refresh
    if new_val and refresh_name is not None:
        globals()[refresh_name](app)


def toggle_logs(app) -> None:
    _toggle_panel(app, "logs")


def toggle_info(app) -> None:
    _toggle_panel(app, "info")


def toggle_keys(app) -> None:
    """Toggle the keys panel via mount/remove."""
    panel_class = cc_dump.tui.keys_panel.KeysPanel
    existing = app.screen.query(panel_class)
    if existing:
        existing.first().remove()
    else:
        app.screen.mount(cc_dump.tui.keys_panel.create_keys_panel())


def toggle_settings(app) -> None:
    """Toggle the settings panel via mount/remove."""
    panel_class = cc_dump.tui.settings_panel.SettingsPanel
    existing = app.screen.query(panel_class)
    if existing:
        app._close_settings()
    else:
        app._open_settings()


def toggle_launch_config(app) -> None:
    """Toggle the launch config panel via mount/remove."""
    panel_class = cc_dump.tui.launch_config_panel.LaunchConfigPanel
    existing = app.screen.query(panel_class)
    if existing:
        app._close_launch_config()
    else:
        app._open_launch_config()


def toggle_side_channel(app) -> None:
    """Toggle the side-channel AI panel via mount/remove."""
    panel_class = cc_dump.tui.side_channel_panel.SideChannelPanel
    existing = app.screen.query(panel_class)
    if existing:
        app._close_side_channel()
    else:
        app._open_side_channel()


# ─── Filterset actions ─────────────────────────────────────────────────


def _cycle_filterset(app, direction: int) -> None:
    """Cycle through filterset slots. direction: +1 forward, -1 backward."""
    slots = cc_dump.tui.action_config.FILTERSET_SLOTS
    current = app._view_store.get("filter:active")
    idx = slots.index(current) if current in slots else -1
    next_idx = (idx + direction) % len(slots)
    apply_filterset(app, slots[next_idx])


def next_filterset(app) -> None:
    _cycle_filterset(app, 1)


def prev_filterset(app) -> None:
    _cycle_filterset(app, -1)


def apply_filterset(app, slot: str) -> None:
    """Apply a saved filterset slot to the current visibility state."""
    filters = cc_dump.settings.get_filterset(slot)
    if filters is None:
        app.notify(f"Preset F{slot} is empty", severity="warning")
        return
    # Batch-set all visibility keys from loaded VisState values
    updates = {}
    for name, vs in filters.items():
        updates[f"vis:{name}"] = vs.visible
        updates[f"full:{name}"] = vs.full
        updates[f"exp:{name}"] = vs.expanded
    app._view_store.update(updates)
    app._view_store.set("filter:active", slot)
    # Show name for built-in presets, just slot number for user-defined
    name = cc_dump.tui.action_config.FILTERSET_NAMES.get(slot, "")
    label = f"F{slot} {name}" if name else f"F{slot}"
    app.notify(label)


# ─── Navigation actions ────────────────────────────────────────────────


def _conv_action(app, fn):
    """// [LAW:one-type-per-behavior] All conv-widget actions share one flow."""
    conv = app._get_conv()
    if conv is not None:
        fn(conv)


def toggle_follow(app) -> None:
    _conv_action(app, lambda c: c.toggle_follow())


def focus_stream(app, request_id: str) -> None:
    """Focus a live request stream from footer chips."""
    conv = app._get_conv()
    if conv is None:
        return
    if not conv.set_focused_stream(request_id):
        return
    app._view_store.set("streams:active", conv.get_active_stream_chips())
    app._view_store.set("streams:focused", conv.get_focused_stream_id() or "")


def go_top(app) -> None:
    def _go(c):
        # // [LAW:dataflow-not-control-flow] Deactivate via table lookup.
        c._follow_state = cc_dump.tui.widget_factory._FOLLOW_DEACTIVATE[c._follow_state]
        c.scroll_home(animate=False)

    _conv_action(app, _go)


def go_bottom(app) -> None:
    _conv_action(app, lambda c: c.scroll_to_bottom())


def scroll_down_line(app) -> None:
    _conv_action(app, lambda c: c.scroll_relative(y=1))


def scroll_up_line(app) -> None:
    _conv_action(app, lambda c: c.scroll_relative(y=-1))


def scroll_left_col(app) -> None:
    _conv_action(app, lambda c: c.scroll_relative(x=-1))


def scroll_right_col(app) -> None:
    _conv_action(app, lambda c: c.scroll_relative(x=1))


def page_down(app) -> None:
    _conv_action(app, lambda c: c.action_page_down())


def page_up(app) -> None:
    _conv_action(app, lambda c: c.action_page_up())


def half_page_down(app) -> None:
    def _half(c):
        c.scroll_relative(y=c.scrollable_content_region.height // 2)

    _conv_action(app, _half)


def half_page_up(app) -> None:
    def _half(c):
        c.scroll_relative(y=-(c.scrollable_content_region.height // 2))

    _conv_action(app, _half)


# ─── Panel refresh ─────────────────────────────────────────────────────


def refresh_panel(app, name: str) -> None:
    """// [LAW:one-type-per-behavior] Generic refresh for store-backed panels."""
    if not app.is_running or app._analytics_store is None:
        return
    panel = app._get_panel(name)
    if panel is not None:
        panel.refresh_from_store(app._analytics_store)


def refresh_stats(app) -> None:
    refresh_panel(app, "stats")


def refresh_economics(app) -> None:
    refresh_panel(app, "economics")


def refresh_timeline(app) -> None:
    refresh_panel(app, "timeline")


def refresh_session(app) -> None:
    """Refresh the session panel with current app state."""
    panel = app._get_panel("session")
    if panel is None:
        return
    panel.refresh_session_state(
        session_id=app._session_id,
        last_message_time=app._app_state.get("last_message_time"),
    )
