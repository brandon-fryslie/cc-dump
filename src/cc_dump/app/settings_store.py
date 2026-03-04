"""Settings store schema and reactions. RELOADABLE.

// [LAW:one-source-of-truth] All known settings and their defaults live in SCHEMA.
// [LAW:single-enforcer] Persistence reaction is the single writer to disk.
"""

import logging
from collections.abc import Callable

import cc_dump.io.settings
from cc_dump.core.coerce import coerce_int, coerce_str_object_dict
from snarfx.hot_reload import HotReloadStore
from snarfx import reaction

logger = logging.getLogger(__name__)

# [LAW:one-source-of-truth] All known settings and their defaults
SCHEMA: dict[str, object] = {
    "auto_zoom_default": False,
    "side_channel_enabled": True,
    "side_channel_global_kill": False,
    "side_channel_max_concurrent": 1,
    "side_channel_purpose_enabled": {},
    "side_channel_timeout_by_purpose": {},
    "side_channel_budget_caps": {},
    "theme": None,
}


def create(initial_overrides: dict | None = None):
    """Create settings store, seeded from disk."""
    disk_data = cc_dump.io.settings.load_settings()
    # Filter disk data to known keys only
    merged = {k: disk_data.get(k, default) for k, default in SCHEMA.items()}
    if initial_overrides:
        merged.update(initial_overrides)
    return HotReloadStore(SCHEMA, initial=merged)


def _bind_setting(store, key: str, project: Callable[[object], object], apply: Callable[[object], None]):
    """Create one fire-immediately reaction from a setting key to a consumer.

    // [LAW:single-enforcer] Store→consumer projection happens through one helper.
    """
    return reaction(
        lambda: project(store.get(key)),
        apply,
        fire_immediately=True,
    )


def setup_reactions(store, context=None):
    """Register all reactions. Returns list of disposers.

    Called on create and on hot-reload reconcile.
    context: dict with live component refs (side_channel_manager, tmux_controller)
    """
    disposers = []

    # Persistence: any setting change writes to disk
    disposers.append(reaction(
        lambda: {k: store.get(k) for k in SCHEMA},
        lambda snapshot: _safe_persist(snapshot),
    ))

    # Consumer sync
    if context:
        mgr = context.get("side_channel_manager")
        view_store = context.get("view_store")

        if view_store is not None:
            for key, project, apply in (
                (
                    "side_channel_enabled",
                    bool,
                    lambda value: view_store.set("settings:side_channel_enabled", bool(value)),
                ),
            ):
                disposers.append(_bind_setting(store, key, project, apply))

        if mgr is not None:
            # // [LAW:dataflow-not-control-flow] Canonical setting→consumer map drives all bindings.
            manager_bindings: tuple[tuple[str, Callable[[object], object], Callable[[object], None]], ...] = (
                ("side_channel_enabled", bool, lambda value: setattr(mgr, "enabled", bool(value))),
                ("side_channel_global_kill", bool, lambda value: setattr(mgr, "global_kill", bool(value))),
                ("side_channel_max_concurrent", lambda value: coerce_int(value, 1), mgr.set_max_concurrent),
                ("side_channel_purpose_enabled", coerce_str_object_dict, mgr.set_purpose_enabled_map),
                ("side_channel_timeout_by_purpose", coerce_str_object_dict, mgr.set_timeout_overrides),
                ("side_channel_budget_caps", coerce_str_object_dict, mgr.set_budget_caps),
            )
            for key, project, apply in manager_bindings:
                disposers.append(_bind_setting(store, key, project, apply))

        tmux = context.get("tmux_controller")
        if tmux is not None:
            for key, project, apply in (
                ("auto_zoom_default", bool, lambda value: setattr(tmux, "auto_zoom", bool(value))),
            ):
                disposers.append(_bind_setting(store, key, project, apply))

    return disposers


def _safe_persist(snapshot: dict) -> None:
    """Write settings to disk. Catches and logs I/O errors."""
    try:
        existing = cc_dump.io.settings.load_settings()
        existing.update(snapshot)
        cc_dump.io.settings.save_settings(existing)
    except Exception:
        logger.exception("Failed to persist settings to disk")
