"""Settings store schema and reactions. RELOADABLE.

// [LAW:one-source-of-truth] All known settings and their defaults live in SCHEMA.
// [LAW:single-enforcer] Persistence reaction is the single writer to disk.
"""

import logging
from typing import cast

import cc_dump.io.settings
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


def _coerce_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str, bytes, bytearray)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return default


def _coerce_str_object_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return cast(dict[str, object], value)


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
            def _select_side_channel_enabled() -> bool:
                return bool(store.get("side_channel_enabled"))

            def _apply_side_channel_enabled(val: bool) -> None:
                mgr.enabled = val

            disposers.append(
                reaction(
                    _select_side_channel_enabled,
                    _apply_side_channel_enabled,
                    fire_immediately=True,
                )
            )

            def _select_side_channel_global_kill() -> bool:
                return bool(store.get("side_channel_global_kill"))

            def _apply_side_channel_global_kill(val: bool) -> None:
                mgr.global_kill = val

            disposers.append(
                reaction(
                    _select_side_channel_global_kill,
                    _apply_side_channel_global_kill,
                    fire_immediately=True,
                )
            )

            def _select_side_channel_max_concurrent() -> int:
                return _coerce_int(store.get("side_channel_max_concurrent"), 1)

            def _apply_side_channel_max_concurrent(val: int) -> None:
                mgr.set_max_concurrent(val)

            disposers.append(
                reaction(
                    _select_side_channel_max_concurrent,
                    _apply_side_channel_max_concurrent,
                    fire_immediately=True,
                )
            )

            def _select_side_channel_purpose_enabled() -> dict[str, object]:
                return _coerce_str_object_dict(store.get("side_channel_purpose_enabled"))

            def _apply_side_channel_purpose_enabled(val: dict[str, object]) -> None:
                mgr.set_purpose_enabled_map(val)

            disposers.append(
                reaction(
                    _select_side_channel_purpose_enabled,
                    _apply_side_channel_purpose_enabled,
                    fire_immediately=True,
                )
            )

            def _select_side_channel_timeout_by_purpose() -> dict[str, object]:
                return _coerce_str_object_dict(store.get("side_channel_timeout_by_purpose"))

            def _apply_side_channel_timeout_by_purpose(val: dict[str, object]) -> None:
                mgr.set_timeout_overrides(val)

            disposers.append(
                reaction(
                    _select_side_channel_timeout_by_purpose,
                    _apply_side_channel_timeout_by_purpose,
                    fire_immediately=True,
                )
            )

            def _select_side_channel_budget_caps() -> dict[str, object]:
                return _coerce_str_object_dict(store.get("side_channel_budget_caps"))

            def _apply_side_channel_budget_caps(val: dict[str, object]) -> None:
                mgr.set_budget_caps(val)

            disposers.append(
                reaction(
                    _select_side_channel_budget_caps,
                    _apply_side_channel_budget_caps,
                    fire_immediately=True,
                )
            )

        tmux = context.get("tmux_controller")
        if tmux is not None:
            def _select_auto_zoom_default() -> bool:
                return bool(store.get("auto_zoom_default"))

            def _apply_auto_zoom_default(val: bool) -> None:
                tmux.auto_zoom = val

            disposers.append(
                reaction(
                    _select_auto_zoom_default,
                    _apply_auto_zoom_default,
                    fire_immediately=True,
                )
            )

    return disposers


def _safe_persist(snapshot: dict) -> None:
    """Write settings to disk. Catches and logs I/O errors."""
    try:
        existing = cc_dump.io.settings.load_settings()
        existing.update(snapshot)
        cc_dump.io.settings.save_settings(existing)
    except Exception:
        logger.exception("Failed to persist settings to disk")
