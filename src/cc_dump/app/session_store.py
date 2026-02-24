"""Session routing store schema and helpers. RELOADABLE.

// [LAW:one-source-of-truth] Session routing identity lives in this store.
// [LAW:single-enforcer] Store schema defaults are defined only here.
"""

from __future__ import annotations

from snarfx.hot_reload import HotReloadStore


SCHEMA: dict[str, object] = {
    "session:active_key": "__default__",
    "session:last_primary_key": "__default__",
    "session:request_keys": {},
}


def create(initial_overrides: dict | None = None):
    """Create session store with optional overrides."""
    initial = dict(SCHEMA)
    if initial_overrides:
        initial.update(initial_overrides)
    return HotReloadStore(SCHEMA, initial=initial)


def setup_reactions(store, context=None):
    """Session store currently has no reactive side effects."""
    return []
