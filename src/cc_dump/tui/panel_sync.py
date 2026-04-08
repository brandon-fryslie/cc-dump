"""Panel sync engine — data-driven toggle panel lifecycle.

// [LAW:single-enforcer] All toggle panel mount/display/focus logic lives here,
//   parameterized by TOGGLE_PANEL_SPECS. No per-panel sync methods.
// [LAW:dataflow-not-control-flow] Each spec row carries the variance; the
//   driver iterates unconditionally.
// [LAW:one-source-of-truth] Panel metadata (css_id, factory, store key,
//   presence mode, focus semantics, close priority) lives in exactly one place.

This module is RELOADABLE. Stable boundary modules import it as a module object.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

import cc_dump.app.launch_config
import cc_dump.tui.debug_settings_panel
import cc_dump.tui.info_panel
import cc_dump.tui.keys_panel
import cc_dump.tui.launch_config_panel
import cc_dump.tui.settings_panel
import cc_dump.tui.widget_factory


class PanelPresence(Enum):
    """How a panel's widget is managed through its lifecycle."""

    # Mount on first visible; keep mounted after; display-toggle thereafter.
    PERSISTENT = "persistent"
    # Mount when visible, remove when hidden. Never persists.
    EPHEMERAL = "ephemeral"


@dataclass(frozen=True)
class PanelSpec:
    """Specification for a toggle panel."""

    name: str
    css_id: str                         # may be "" when queried by class name
    store_key: str                      # "panel:logs", etc.
    presence: PanelPresence
    query_selector: str                 # "#logs-panel" or "SettingsPanel" (class name)
    factory: Callable[["object"], "object"]  # (app) -> widget
    focus_on_show: bool = False
    focus_conv_on_hide: bool = False
    close_priority: int = 0             # higher = closed first; 0 = not escape-closable
    on_close: str | None = None         # method name on app for custom close handling
    group: str = ""                     # "chrome" | "sidebar" | "aux" — for grouped reactions


# ─── Factory wrappers ─────────────────────────────────────────────────
# Each factory takes `app` and returns an unmounted widget with its css_id set.


def _create_logs(app):
    widget = cc_dump.tui.widget_factory.create_logs_panel()
    widget.id = "logs-panel"
    return widget


def _create_info(app):
    widget = cc_dump.tui.info_panel.create_info_panel()
    widget.id = "info-panel"
    return widget


def _create_settings(app):
    # Import locally to avoid circular import; settings_launch_controller
    # lives above this module in the dep graph.
    from cc_dump.tui import settings_launch_controller
    widget = cc_dump.tui.settings_panel.create_settings_panel(
        settings_launch_controller.initial_settings_values(app)
    )
    return widget


def _create_launch_config(app):
    configs = cc_dump.app.launch_config.load_configs()
    active_name = cc_dump.app.launch_config.load_active_name()
    widget = cc_dump.tui.launch_config_panel.create_launch_config_panel(
        configs, active_name
    )
    return widget


def _create_keys(app):
    return cc_dump.tui.keys_panel.create_keys_panel()


def _create_debug_settings(app):
    return cc_dump.tui.debug_settings_panel.create_debug_settings_panel(app_ref=app)


# ─── Spec table ────────────────────────────────────────────────────────


TOGGLE_PANEL_SPECS: tuple[PanelSpec, ...] = (
    PanelSpec(
        name="logs",
        css_id="logs-panel",
        store_key="panel:logs",
        presence=PanelPresence.PERSISTENT,
        query_selector="#logs-panel",
        factory=_create_logs,
        group="chrome",
    ),
    PanelSpec(
        name="info",
        css_id="info-panel",
        store_key="panel:info",
        presence=PanelPresence.PERSISTENT,
        query_selector="#info-panel",
        factory=_create_info,
        group="chrome",
    ),
    PanelSpec(
        name="settings",
        css_id="",
        store_key="panel:settings",
        presence=PanelPresence.PERSISTENT,
        query_selector="SettingsPanel",
        factory=_create_settings,
        focus_on_show=True,
        focus_conv_on_hide=True,
        close_priority=10,
        on_close="_close_settings",
        group="sidebar",
    ),
    PanelSpec(
        name="launch_config",
        css_id="",
        store_key="panel:launch_config",
        presence=PanelPresence.PERSISTENT,
        query_selector="LaunchConfigPanel",
        factory=_create_launch_config,
        focus_on_show=True,
        focus_conv_on_hide=True,
        close_priority=20,  # higher priority → closed first by escape
        on_close="_close_launch_config",
        group="sidebar",
    ),
    PanelSpec(
        name="keys",
        css_id="",
        store_key="panel:keys",
        presence=PanelPresence.PERSISTENT,
        query_selector="KeysPanel",
        factory=_create_keys,
        group="aux",
    ),
    PanelSpec(
        name="debug_settings",
        css_id="",
        store_key="panel:debug_settings",
        presence=PanelPresence.EPHEMERAL,
        query_selector="DebugSettingsPanel",
        factory=_create_debug_settings,
        focus_conv_on_hide=True,
        group="aux",
    ),
)


def specs_for_group(group: str) -> tuple[PanelSpec, ...]:
    return tuple(s for s in TOGGLE_PANEL_SPECS if s.group == group)


# ─── Query helpers ─────────────────────────────────────────────────────


def _query_existing(app, spec: PanelSpec):
    """Return the first existing widget matching the spec, or None."""
    try:
        results = app.screen.query(spec.query_selector)
    except Exception:
        return None
    try:
        return results.first()
    except Exception:
        return None


# ─── Presence resolution ───────────────────────────────────────────────


def _apply_presence(app, spec: PanelSpec, existing, will_visible: bool):
    """Mount/remove per presence mode. Returns the widget to display-toggle, or None.

    // [LAW:dataflow-not-control-flow] Presence is a typed enum; dispatch over it
    //   instead of scattered if-ladders.
    """
    if spec.presence == PanelPresence.EPHEMERAL:
        if will_visible and existing is None:
            widget = spec.factory(app)
            app.screen.mount(widget)
            return widget
        if not will_visible and existing is not None:
            existing.remove()
            return None
        return existing
    # PERSISTENT: always have a widget, even hidden. Mount if missing.
    if existing is None:
        widget = spec.factory(app)
        app.screen.mount(widget)
        return widget
    return existing


# ─── The driver ────────────────────────────────────────────────────────


def _should_focus_conv_on_transition(spec: PanelSpec, was: bool, will: bool) -> bool:
    """// [LAW:dataflow-not-control-flow] Focus-conv eligibility is data."""
    return spec.focus_conv_on_hide and was and not will


def _should_focus_show(spec: PanelSpec, widget, will: bool) -> bool:
    """// [LAW:dataflow-not-control-flow] Focus-show eligibility is data."""
    return will and spec.focus_on_show and widget is not None


def _higher_priority(
    candidate: tuple[object, PanelSpec],
    current: tuple[object, PanelSpec] | None,
) -> bool:
    """// [LAW:dataflow-not-control-flow] Priority comparison is data."""
    return current is None or candidate[1].close_priority > current[1].close_priority


def _resolve_focus_action(
    app,
    focus_show_target: tuple[object, PanelSpec] | None,
    focus_conv: bool,
) -> None:
    """Apply the decided focus action at end of sync pass."""
    if focus_show_target is not None:
        _focus_default(app, focus_show_target[0])
        return
    if focus_conv:
        _focus_conv(app)


def sync_group(app, specs: tuple[PanelSpec, ...], visible_flags: tuple[bool, ...]) -> None:
    """Sync a group of toggle panels to their store-driven visibility.

    // [LAW:single-enforcer] All per-panel mount/display/focus branching lives here.
    // [LAW:dataflow-not-control-flow] Every spec runs the same unconditional steps;
    //   the spec row carries what differs.
    """
    focus_conv = False
    focus_show_target: tuple[object, PanelSpec] | None = None

    for spec, will_visible in zip(specs, visible_flags):
        existing = _query_existing(app, spec)
        was_visible = bool(existing.display) if existing is not None else False

        widget = _apply_presence(app, spec, existing, will_visible)
        if widget is not None:
            widget.display = will_visible

        if _should_focus_conv_on_transition(spec, was_visible, will_visible):
            focus_conv = True

        if _should_focus_show(spec, widget, will_visible):
            candidate = (widget, spec)
            if _higher_priority(candidate, focus_show_target):
                focus_show_target = candidate

    _resolve_focus_action(app, focus_show_target, focus_conv)


def _focus_default(app, widget) -> None:
    focus_default = getattr(widget, "focus_default_control", None)
    if callable(focus_default):
        app.call_after_refresh(focus_default)


def _focus_conv(app) -> None:
    conv = app._get_conv()
    if conv is not None:
        app.call_after_refresh(conv.focus)


# ─── Close topmost ─────────────────────────────────────────────────────


def close_topmost(app) -> bool:
    """Close the highest-priority visible closable panel.

    // [LAW:dataflow-not-control-flow] Priority order is a data property of the
    //   specs, not a hand-coded if-ladder.
    """
    closable = sorted(
        (s for s in TOGGLE_PANEL_SPECS if s.close_priority > 0 and s.on_close),
        key=lambda s: s.close_priority,
        reverse=True,
    )
    for spec in closable:
        if app._view_store.get(spec.store_key):
            handler = getattr(app, spec.on_close, None)
            if callable(handler):
                handler()
                return True
    return False
