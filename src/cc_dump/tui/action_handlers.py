"""Action handlers for navigation, visibility, and panel toggles.

// [LAW:one-way-deps] Depends on formatting, rendering. No upward deps.
// [LAW:locality-or-seam] All action logic here — app.py keeps thin delegates.
// [LAW:one-type-per-behavior] Scroll actions are instances of _conv_action.

Not hot-reloadable (accesses app widgets and reactive state).
"""

import cc_dump.formatting
import cc_dump.tui.rendering


# ─── Visibility actions ────────────────────────────────────────────────

# [LAW:dataflow-not-control-flow] Visibility toggle specs — data, not branches.
# Each tuple: (dict_attr, force_value_or_None) where None means "toggle".
_VIS_TOGGLE_SPECS = {
    "vis": [("_is_visible", None)],
    "detail": [("_is_visible", True), ("_is_full", None)],
    "expand": [("_is_visible", True), ("_is_expanded", None)],
}


def _toggle_vis_dicts(app, category: str, spec_key: str) -> None:
    """// [LAW:one-type-per-behavior] Single function for all visibility mutations."""
    for attr, force in _VIS_TOGGLE_SPECS[spec_key]:
        old = getattr(app, attr)
        new = dict(old)
        new[category] = (not old[category]) if force is None else force
        setattr(app, attr, new)
    clear_overrides(app, category)


def clear_overrides(app, category_name: str) -> None:
    """Reset per-block expanded overrides for a category."""
    cat = cc_dump.formatting.Category(category_name)
    conv = app._get_conv()
    if conv is None:
        return
    for td in conv._turns:
        for block in td.blocks:
            block_cat = cc_dump.tui.rendering.get_category(block)
            if block_cat == cat:
                block.expanded = None


def toggle_vis(app, category: str) -> None:
    _toggle_vis_dicts(app, category, "vis")


def toggle_detail(app, category: str) -> None:
    _toggle_vis_dicts(app, category, "detail")


def toggle_expand(app, category: str) -> None:
    _toggle_vis_dicts(app, category, "expand")


# ─── Panel toggles ─────────────────────────────────────────────────────

# [LAW:one-type-per-behavior] Panel toggle config — (reactive_attr, getter, on_show_fn)
_PANEL_TOGGLE_CONFIG = {
    "economics": ("show_economics", "_get_economics", "refresh_economics"),
    "timeline": ("show_timeline", "_get_timeline", "refresh_timeline"),
    "logs": ("show_logs", "_get_logs", None),
    "info": ("show_info", "_get_info", None),
}


def _toggle_panel(app, panel_key: str) -> None:
    """// [LAW:dataflow-not-control-flow] Panel toggling driven by config, not branches."""
    attr, getter_name, refresh_name = _PANEL_TOGGLE_CONFIG[panel_key]
    new_val = not getattr(app, attr)
    setattr(app, attr, new_val)
    widget = getattr(app, getter_name)()
    if widget is not None:
        widget.display = new_val
    # [LAW:dataflow-not-control-flow] refresh_name is None for panels without db refresh
    if new_val and refresh_name is not None:
        globals()[refresh_name](app)


def toggle_economics(app) -> None:
    _toggle_panel(app, "economics")


def toggle_timeline(app) -> None:
    _toggle_panel(app, "timeline")


def toggle_logs(app) -> None:
    _toggle_panel(app, "logs")


def toggle_info(app) -> None:
    _toggle_panel(app, "info")


def toggle_economics_breakdown(app) -> None:
    """Toggle between aggregate and per-model breakdown in economics panel."""
    economics = app._get_economics()
    if economics is not None:
        economics.toggle_breakdown()


# ─── Navigation actions ────────────────────────────────────────────────


def _conv_action(app, fn, update_footer=False):
    """// [LAW:one-type-per-behavior] All conv-widget actions share one flow."""
    conv = app._get_conv()
    if conv is not None:
        fn(conv)
    if update_footer:
        app._update_footer_state()


def toggle_follow(app) -> None:
    _conv_action(app, lambda c: c.toggle_follow(), update_footer=True)


def go_top(app) -> None:
    def _go(c):
        c._follow_mode = False
        c.scroll_home(animate=False)

    _conv_action(app, _go, update_footer=True)


def go_bottom(app) -> None:
    _conv_action(app, lambda c: c.scroll_to_bottom(), update_footer=True)


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


def _refresh_panel(app, getter_name: str) -> None:
    """// [LAW:one-type-per-behavior] Shared refresh logic for db-backed panels."""
    if not app.is_running or not app._db_path or not app._session_id:
        return
    panel = getattr(app, getter_name)()
    if panel is not None:
        panel.refresh_from_db(app._db_path, app._session_id)


def refresh_economics(app) -> None:
    _refresh_panel(app, "_get_economics")


def refresh_timeline(app) -> None:
    _refresh_panel(app, "_get_timeline")
