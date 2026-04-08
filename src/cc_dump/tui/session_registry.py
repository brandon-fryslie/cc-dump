"""Session registry — single source of truth for tab/conversation/store identity.

// [LAW:single-enforcer] Session identity is constructed exactly here.
// [LAW:one-source-of-truth] Active session lives in this registry, not on the
//   App, not on the tabs widget, not in N parallel dicts.
// [LAW:dataflow-not-control-flow] Sessions are typed records; downstream code
//   reads `session.is_default` instead of branching on `key == "__default__"`.

This module is RELOADABLE. Stable boundary modules import it as a module object.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

import cc_dump.providers

if TYPE_CHECKING:
    import cc_dump.app.domain_store


@dataclass
class Session:
    """A single conversation tab + its backing state.

    Constructed exclusively by SessionRegistry. `is_default` and `provider` are
    decided at construction time and never re-derived; downstream callers read
    these fields instead of branching on the raw key.
    """

    key: str
    tab_id: str
    conv_id: str
    domain_store: "cc_dump.app.domain_store.DomainStore"
    provider: str
    is_default: bool
    last_message_time: float | None = None

    def tab_title(self) -> str:
        """Compute the tab title for this session.

        // [LAW:dataflow-not-control-flow] Title is derived from typed fields,
        //   not from re-parsing the key string at every call site.
        """
        if self.is_default:
            return cc_dump.providers.get_provider_spec(
                cc_dump.providers.DEFAULT_PROVIDER_KEY
            ).tab_title
        spec = cc_dump.providers.get_provider_spec(self.provider)
        if self.provider != cc_dump.providers.DEFAULT_PROVIDER_KEY:
            _, _, suffix = self.key.partition(":")
            if suffix == cc_dump.providers.DEFAULT_SESSION_KEY:
                return spec.tab_title
            return f"{spec.tab_short_prefix} {suffix[:8]}"
        return self.key[:8]


SessionFactory = Callable[[str], Session]


def normalize_session_key(raw: str | None) -> str:
    """Normalize a raw session key string at the trust boundary.

    // [LAW:single-enforcer] Empty-string → default key collapses exactly here.
    """
    if not raw:
        return cc_dump.providers.DEFAULT_SESSION_KEY
    return raw


class SessionRegistry:
    """Owns all sessions, the active one, and request-id → session bindings.

    // [LAW:one-source-of-truth] All session-keyed state lives in this registry.
    //   The App holds exactly one reference to it.
    """

    def __init__(self, default: Session) -> None:
        self._sessions: dict[str, Session] = {default.key: default}
        self._default = default
        self._active_key: str = default.key
        self._request_bindings: dict[str, str] = {}

    # ─── Identity ──────────────────────────────────────────────────────

    def default(self) -> Session:
        return self._default

    def active(self) -> Session:
        # Active key always names a registered session by construction.
        return self._sessions[self._active_key]

    def get(self, key: str) -> Session | None:
        return self._sessions.get(normalize_session_key(key))

    def get_or_default(self, key: str) -> Session:
        """// [LAW:dataflow-not-control-flow] Missing key → default, no caller branch."""
        return self._sessions.get(normalize_session_key(key), self._default)

    def all(self) -> tuple[Session, ...]:
        return tuple(self._sessions.values())

    # ─── Mutation ──────────────────────────────────────────────────────

    def ensure(self, raw_key: str | None, *, factory: SessionFactory) -> Session:
        """Idempotently materialize a session for the given key.

        // [LAW:single-enforcer] The factory is the only way new Sessions enter
        //   the registry. Raw key is normalized exactly here.
        """
        key = normalize_session_key(raw_key)
        existing = self._sessions.get(key)
        if existing is not None:
            return existing
        session = factory(key)
        self._sessions[session.key] = session
        return session

    def set_active(self, key: str) -> Session:
        """Promote `key` to active. Returns the active session."""
        normalized = normalize_session_key(key)
        if normalized in self._sessions:
            self._active_key = normalized
        return self.active()

    def sync_from_tab_id(self, tab_id: str) -> Session:
        """Update active session from a Textual tab pane id (one-way: tabs → registry).

        // [LAW:dataflow-not-control-flow] Tabs widget is the source; registry is
        //   the sink. No mutating-getter side effects scattered across reads.
        """
        if tab_id:
            for session in self._sessions.values():
                if session.tab_id == tab_id:
                    self._active_key = session.key
                    return session
        return self.active()

    # ─── Request routing ───────────────────────────────────────────────

    def bind_request(self, request_id: str, key: str | None) -> None:
        if not request_id:
            return
        self._request_bindings[request_id] = normalize_session_key(key)

    def session_for_request(self, request_id: str) -> Session:
        """Resolve a request_id to its bound session, falling back to default.

        // [LAW:dataflow-not-control-flow] Always returns a Session — never None,
        //   never a raw key string.
        """
        key = self._request_bindings.get(request_id) if request_id else None
        if key is not None:
            session = self._sessions.get(key)
            if session is not None:
                return session
        return self._default
