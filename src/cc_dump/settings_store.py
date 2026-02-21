"""Settings store schema and reactions. RELOADABLE.

// [LAW:one-source-of-truth] All known settings and their defaults live in SCHEMA.
// [LAW:single-enforcer] Persistence reaction is the single writer to disk.
"""

import logging

import cc_dump.settings
from snarfx.hot_reload import HotReloadStore
from snarfx import reaction

logger = logging.getLogger(__name__)

# [LAW:one-source-of-truth] All known settings and their defaults
SCHEMA: dict[str, object] = {
    "auto_zoom_default": False,
    "side_channel_enabled": True,
    "theme": None,
}


def create(initial_overrides: dict | None = None):
    """Create settings store, seeded from disk."""
    disk_data = cc_dump.settings.load_settings()
    # Filter disk data to known keys only
    merged = {k: disk_data.get(k, default) for k, default in SCHEMA.items()}
    if initial_overrides:
        merged.update(initial_overrides)
    return HotReloadStore(SCHEMA, initial=merged)


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
        if mgr is not None:
            disposers.append(reaction(
                lambda: store.get("side_channel_enabled"),
                lambda val, m=mgr: setattr(m, "enabled", val),
                fire_immediately=True,
            ))

        tmux = context.get("tmux_controller")
        if tmux is not None:
            disposers.append(reaction(
                lambda: store.get("auto_zoom_default"),
                lambda val, t=tmux: setattr(t, "auto_zoom", val),
                fire_immediately=True,
            ))

    return disposers


def _safe_persist(snapshot: dict) -> None:
    """Write settings to disk. Catches and logs I/O errors."""
    try:
        existing = cc_dump.settings.load_settings()
        existing.update(snapshot)
        cc_dump.settings.save_settings(existing)
    except Exception:
        logger.exception("Failed to persist settings to disk")
