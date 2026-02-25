"""Session routing store schema and helpers. RELOADABLE.

// [LAW:one-source-of-truth] Session routing identity lives in this store.
// [LAW:single-enforcer] Store schema defaults are defined only here.
"""

from __future__ import annotations

from snarfx.hot_reload import HotReloadStore


DEFAULT_SESSION_KEY = "__default__"

SCHEMA: dict[str, object] = {
    "session:active_key": DEFAULT_SESSION_KEY,
    "session:last_primary_key": DEFAULT_SESSION_KEY,
    "session:request_keys": {},
}


def create(initial_overrides: dict | None = None):
    """Create session store with optional overrides."""
    initial = dict(SCHEMA)
    if initial_overrides:
        initial.update(initial_overrides)
    store = HotReloadStore(SCHEMA, initial=initial)
    ensure_routing_state(store)
    return store


def setup_reactions(store, context=None):
    """Session store currently has no reactive side effects."""
    return []


def normalize_session_key(session_key: str, default_key: str = DEFAULT_SESSION_KEY) -> str:
    """Canonicalize empty keys to the configured default key.

    // [LAW:single-enforcer] Session-key normalization is enforced only here.
    """
    return session_key if session_key else default_key


def ensure_routing_state(store, default_key: str = DEFAULT_SESSION_KEY) -> None:
    """Normalize routing keys/map after create/reconcile.

    // [LAW:single-enforcer] Runtime shape repair for routing state is enforced only here.
    """
    store.set(
        "session:active_key",
        normalize_session_key(str(store.get("session:active_key") or ""), default_key),
    )
    store.set(
        "session:last_primary_key",
        normalize_session_key(str(store.get("session:last_primary_key") or ""), default_key),
    )
    request_keys = store.get("session:request_keys")
    if not isinstance(request_keys, dict):
        store.set("session:request_keys", {})


def get_active_key(store, default_key: str = DEFAULT_SESSION_KEY) -> str:
    return normalize_session_key(str(store.get("session:active_key") or ""), default_key)


def set_active_key(store, session_key: str, default_key: str = DEFAULT_SESSION_KEY) -> None:
    store.set("session:active_key", normalize_session_key(session_key, default_key))


def get_last_primary_key(store, default_key: str = DEFAULT_SESSION_KEY) -> str:
    return normalize_session_key(str(store.get("session:last_primary_key") or ""), default_key)


def set_last_primary_key(store, session_key: str, default_key: str = DEFAULT_SESSION_KEY) -> None:
    store.set("session:last_primary_key", normalize_session_key(session_key, default_key))


def get_request_keys(store) -> dict[str, str]:
    request_keys = store.get("session:request_keys")
    return dict(request_keys) if isinstance(request_keys, dict) else {}


def set_request_key(store, request_id: str, session_key: str, default_key: str = DEFAULT_SESSION_KEY) -> None:
    request_keys = get_request_keys(store)
    request_keys[request_id] = normalize_session_key(session_key, default_key)
    store.set("session:request_keys", request_keys)
