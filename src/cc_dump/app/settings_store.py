"""Settings store schema and reactions. RELOADABLE.

// [LAW:one-source-of-truth] All known settings and their defaults live in SCHEMA.
// [LAW:single-enforcer] Persistence reaction is the single writer to disk.
"""

import logging

import cc_dump.io.settings
import cc_dump.proxies.registry
from snarfx.hot_reload import HotReloadStore
from snarfx import reaction

logger = logging.getLogger(__name__)

# [LAW:one-source-of-truth] Core (non-provider-specific) settings defaults.
_BASE_SCHEMA: dict[str, object] = {
    "auto_zoom_default": False,
    "side_channel_enabled": True,
    "side_channel_global_kill": False,
    "side_channel_max_concurrent": 1,
    "side_channel_purpose_enabled": {},
    "side_channel_timeout_by_purpose": {},
    "side_channel_budget_caps": {},
    "proxy_provider": "anthropic",
    "theme": None,
}


def _provider_settings_defaults() -> dict[str, object]:
    defaults: dict[str, object] = {}
    for descriptor in cc_dump.proxies.registry.all_setting_descriptors():
        key = str(descriptor.key or "").strip()
        if not key:
            continue
        defaults.setdefault(key, descriptor.default)
    return defaults


def build_schema() -> dict[str, object]:
    # // [LAW:one-source-of-truth] Effective schema is computed from core defaults + provider descriptors.
    merged = dict(_BASE_SCHEMA)
    merged.update(_provider_settings_defaults())
    return merged


# [LAW:one-source-of-truth] All known settings and defaults.
SCHEMA: dict[str, object] = build_schema()


def create(initial_overrides: dict | None = None):
    """Create settings store, seeded from disk."""
    disk_data = cc_dump.io.settings.load_settings()
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
            disposers.append(reaction(
                lambda: store.get("side_channel_global_kill"),
                lambda val, m=mgr: setattr(m, "global_kill", bool(val)),
                fire_immediately=True,
            ))
            disposers.append(reaction(
                lambda: int(store.get("side_channel_max_concurrent") or 1),
                lambda val, m=mgr: m.set_max_concurrent(int(val)),
                fire_immediately=True,
            ))
            disposers.append(reaction(
                lambda: store.get("side_channel_purpose_enabled"),
                lambda val, m=mgr: m.set_purpose_enabled_map(
                    val if isinstance(val, dict) else {}
                ),
                fire_immediately=True,
            ))
            disposers.append(reaction(
                lambda: store.get("side_channel_timeout_by_purpose"),
                lambda val, m=mgr: m.set_timeout_overrides(
                    val if isinstance(val, dict) else {}
                ),
                fire_immediately=True,
            ))
            disposers.append(reaction(
                lambda: store.get("side_channel_budget_caps"),
                lambda val, m=mgr: m.set_budget_caps(
                    val if isinstance(val, dict) else {}
                ),
                fire_immediately=True,
            ))

        tmux = context.get("tmux_controller")
        if tmux is not None:
            disposers.append(reaction(
                lambda: store.get("auto_zoom_default"),
                lambda val, t=tmux: setattr(t, "auto_zoom", val),
                fire_immediately=True,
            ))

        proxy_runtime = context.get("proxy_runtime")
        if proxy_runtime is not None:
            # [LAW:single-enforcer] Runtime proxy config synchronization happens in one reaction.
            disposers.append(reaction(
                lambda: {k: store.get(k) for k in SCHEMA},
                lambda snapshot, runtime=proxy_runtime: runtime.update_from_settings(snapshot),
                fire_immediately=True,
            ))

    return disposers


def _safe_persist(snapshot: dict) -> None:
    """Write settings to disk. Catches and logs I/O errors."""
    try:
        existing = cc_dump.io.settings.load_settings()
        existing.update(snapshot)
        cc_dump.io.settings.save_settings(existing)
    except Exception:
        logger.exception("Failed to persist settings to disk")
