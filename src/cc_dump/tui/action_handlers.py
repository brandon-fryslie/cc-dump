"""Action handlers for navigation, visibility, and panel toggles.

// [LAW:one-way-deps] Depends on formatting, rendering. No upward deps.
// [LAW:locality-or-seam] All action logic here — app.py keeps thin delegates.
// [LAW:one-type-per-behavior] Scroll actions are instances of _conv_action.

Hot-reloadable — imported as module object in app.py, all functions take app as param.
"""

from dataclasses import dataclass

import cc_dump.core.formatting
import cc_dump.core.special_content
import cc_dump.io.settings
import cc_dump.tui.action_config  # module-style for hot-reload
import cc_dump.tui.location_navigation
import cc_dump.tui.rendering

# [LAW:one-source-of-truth] Panel order derived from registry
import cc_dump.tui.panel_registry
from snarfx import transaction
import cc_dump.tui.keys_panel
import cc_dump.tui.settings_panel
import cc_dump.tui.proxy_settings_panel
import cc_dump.tui.launch_config_panel
import cc_dump.tui.side_channel_panel
import cc_dump.tui.widget_factory


# ─── Visibility actions ────────────────────────────────────────────────


def _active_domain_store(app):
    """Return active tab domain store when available, fallback to singleton field."""
    getter = getattr(app, "_get_active_domain_store", None)
    if callable(getter):
        return getter()
    return getattr(app, "_domain_store", None)


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
    // [LAW:one-source-of-truth] Reads blocks from domain store.
    """
    cat = cc_dump.core.formatting.Category(category_name)
    conv = app._get_conv()
    if conv is None:
        return

    ds = _active_domain_store(app)
    if ds is not None:
        all_blocks = [block for block_list in ds.iter_completed_blocks() for block in block_list]
    else:
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
    current = cc_dump.core.formatting.VisState(
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
    panel_order = cc_dump.tui.panel_registry.PANEL_ORDER
    idx = panel_order.index(current) if current in panel_order else -1
    next_idx = (idx + 1) % len(panel_order)
    app.active_panel = panel_order[next_idx]


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
    panel = app._get_panel(panel_name)
    if panel is None:
        return
    if panel_name == "perf":
        panel.refresh_from_store(app._analytics_store, app=app)
        return
    if app._analytics_store is None:
        return
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


def toggle_proxy_settings(app) -> None:
    """Toggle the proxy settings panel via mount/remove."""
    panel_class = cc_dump.tui.proxy_settings_panel.ProxySettingsPanel
    existing = app.screen.query(panel_class)
    if existing:
        app._close_proxy_settings()
    else:
        app._open_proxy_settings()


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
    filters = cc_dump.io.settings.get_filterset(slot)
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
    ds = _active_domain_store(app)
    if ds is None:
        return
    if not ds.set_focused_stream(request_id):
        return
    app._view_store.set("streams:active", ds.get_active_stream_chips())
    app._view_store.set("streams:focused", ds.get_focused_stream_id() or "")


def toggle_stream_view_mode(app) -> None:
    """Toggle live stream viewport mode between focused and side-by-side lanes."""
    current = app._view_store.get("streams:view")
    next_mode = "lanes" if current == "focused" else "focused"
    app._view_store.set("streams:view", next_mode)
    conv = app._get_conv()
    if conv is not None:
        conv.set_stream_view_mode(next_mode)


def _special_nav_cursor_map(app) -> dict[str, int]:
    """Return mutable cursor map for special-navigation markers."""
    cursor_map = app._app_state.get("special_nav_cursor")
    if not isinstance(cursor_map, dict):
        cursor_map = {}
        app._app_state["special_nav_cursor"] = cursor_map
    return cursor_map


def _region_nav_cursor_map(app) -> dict[str, int]:
    """Return mutable cursor map for region-tag navigation."""
    cursor_map = app._app_state.get("region_nav_cursor")
    if not isinstance(cursor_map, dict):
        cursor_map = {}
        app._app_state["region_nav_cursor"] = cursor_map
    return cursor_map


@dataclass(frozen=True)
class _RegionTagLocation:
    tag: str
    turn_index: int
    block_index: int
    block: object


def _iter_descendants_with_top_index(block, top_index: int):
    """Yield (top_index, block) for a block tree in pre-order."""
    yield top_index, block
    for child in getattr(block, "children", []) or []:
        yield from _iter_descendants_with_top_index(child, top_index)


def _collect_region_tag_locations(turns: list, tag: str) -> list[_RegionTagLocation]:
    """Collect region-tag locations in chronological render order.

    // [LAW:one-source-of-truth] Region tags originate from ContentRegion.tags only.
    """
    locations: list[_RegionTagLocation] = []
    for turn_index, turn in enumerate(turns):
        if getattr(turn, "is_streaming", False):
            continue
        for block_index, top_block in enumerate(turn.blocks):
            for top_idx, block in _iter_descendants_with_top_index(top_block, block_index):
                for region in getattr(block, "content_regions", []) or []:
                    for region_tag in region.tags:
                        if tag != "all" and region_tag != tag:
                            continue
                        locations.append(
                            _RegionTagLocation(
                                tag=region_tag,
                                turn_index=turn_index,
                                block_index=top_idx,
                                block=block,
                            )
                        )
    return locations


def _navigate_special(app, marker_key: str, direction: int) -> None:
    """Navigate to next/previous special request marker.

    // [LAW:one-source-of-truth] Marker classification comes from special_content.
    // [LAW:single-enforcer] Location jump executes through location_navigation.go_to_location.
    """
    conv = app._get_conv()
    if conv is None:
        return

    locations = cc_dump.core.special_content.collect_special_locations(conv._turns, marker_key=marker_key)
    if not locations:
        app.notify("No matching special sections")
        return

    cursor_key = marker_key
    cursor_map = _special_nav_cursor_map(app)
    default_idx = -1 if direction > 0 else 0
    idx = int(cursor_map.get(cursor_key, default_idx))
    idx = (idx + direction) % len(locations)
    cursor_map[cursor_key] = idx

    loc = locations[idx]
    location = cc_dump.tui.location_navigation.BlockLocation(
        turn_index=loc.turn_index,
        block_index=loc.block_index,
        block=loc.block,
    )
    ok = cc_dump.tui.location_navigation.go_to_location(
        conv,
        location,
        rerender=lambda: conv.rerender(app.active_filters),
    )
    if not ok:
        app.notify("Special section unavailable")
        return

    app.notify(
        f"{loc.marker.label}: {idx + 1}/{len(locations)}"
    )


def next_special(app, marker_key: str = "all") -> None:
    _navigate_special(app, marker_key, 1)


def prev_special(app, marker_key: str = "all") -> None:
    _navigate_special(app, marker_key, -1)


def _navigate_region_tag(app, tag: str, direction: int) -> None:
    """Navigate to next/previous ContentRegion tag location."""
    conv = app._get_conv()
    if conv is None:
        return

    locations = _collect_region_tag_locations(conv._turns, tag=tag)
    if not locations:
        app.notify("No matching region tags")
        return

    cursor_map = _region_nav_cursor_map(app)
    default_idx = -1 if direction > 0 else 0
    idx = int(cursor_map.get(tag, default_idx))
    idx = (idx + direction) % len(locations)
    cursor_map[tag] = idx

    loc = locations[idx]
    location = cc_dump.tui.location_navigation.BlockLocation(
        turn_index=loc.turn_index,
        block_index=loc.block_index,
        block=loc.block,
    )
    ok = cc_dump.tui.location_navigation.go_to_location(
        conv,
        location,
        rerender=lambda: conv.rerender(app.active_filters),
    )
    if not ok:
        app.notify("Region tag location unavailable")
        return
    app.notify(f"{loc.tag}: {idx + 1}/{len(locations)}")


def next_region_tag(app, tag: str = "all") -> None:
    _navigate_region_tag(app, tag, 1)


def prev_region_tag(app, tag: str = "all") -> None:
    _navigate_region_tag(app, tag, -1)


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
    if not app.is_running:
        return
    panel = app._get_panel(name)
    if panel is None:
        return
    if name == "perf":
        panel.refresh_from_store(app._analytics_store, app=app)
        return
    if app._analytics_store is None:
        return
    # [LAW:dataflow-not-control-flow] Per-panel refresh kwargs via lookup table.
    all_domain_stores = ()
    iter_stores = getattr(app, "_iter_domain_stores", None)
    if callable(iter_stores):
        all_domain_stores = iter_stores()
    panel_kwargs = {
        "stats": {"domain_store": _active_domain_store(app), "all_domain_stores": all_domain_stores},
    }
    panel.refresh_from_store(app._analytics_store, **panel_kwargs.get(name, {}))


def refresh_stats(app) -> None:
    refresh_panel(app, "stats")


def refresh_economics(app) -> None:
    refresh_panel(app, "economics")


def refresh_timeline(app) -> None:
    refresh_panel(app, "timeline")


def refresh_perf(app) -> None:
    refresh_panel(app, "perf")


def refresh_session(app) -> None:
    """Refresh the session panel with current app state."""
    panel = app._get_panel("session")
    if panel is None:
        return
    if hasattr(app, "_get_active_session_panel_state"):
        session_id, last_message_time = app._get_active_session_panel_state()
    else:
        session_id = app._session_id
        last_message_time = app._app_state.get("last_message_time")
    panel.refresh_session_state(
        session_id=session_id,
        last_message_time=last_message_time,
    )
