"""Settings store schema and reactions. RELOADABLE.

// [LAW:one-source-of-truth] All known settings and their defaults live in SCHEMA.
// [LAW:single-enforcer] Persistence reaction is the single writer to disk.
"""

import logging

from cc_dump.io.settings import load_settings, save_settings
from snarfx.hot_reload import HotReloadStore
from snarfx import reaction

logger = logging.getLogger(__name__)

# [LAW:one-source-of-truth] All known settings and their defaults
SCHEMA: dict[str, object] = {
    "theme": None,
}


def create(initial_overrides: dict | None = None):
    """Create settings store, seeded from disk."""
    disk_data = load_settings()
    # Filter disk data to known keys only
    merged = {k: disk_data.get(k, default) for k, default in SCHEMA.items()}
    if initial_overrides:
        merged.update(initial_overrides)
    return HotReloadStore(SCHEMA, initial=merged)


def setup_reactions(store, context=None):
    """Register all reactions. Returns list of disposers.

    Called on create and on hot-reload reconcile.
    context: dict with live component refs (tmux_controller, etc.)
    """
    disposers = []

    # Persistence: any setting change writes to disk
    disposers.append(reaction(
        lambda: {k: store.get(k) for k in SCHEMA},
        lambda snapshot: _safe_persist(snapshot),
    ))

    return disposers


def _safe_persist(snapshot: dict) -> None:
    """Write settings to disk. Catches and logs I/O errors."""
    try:
        existing = load_settings()
        existing.update(snapshot)
        save_settings(existing)
    except Exception:
        logger.exception("Failed to persist settings to disk")
