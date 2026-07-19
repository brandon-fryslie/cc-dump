"""Request registry — single source of truth for per-request ephemeral state.

// [LAW:single-enforcer] All per-request state lives on Request records.
//   No parallel dicts; no isinstance guards; typed fields throughout.
// [LAW:one-source-of-truth] A request_id owns exactly one Request record;
//   all handlers mutate the same instance.
// [LAW:dataflow-not-control-flow] Handlers read/write typed attributes
//   instead of branching on `isinstance(app_state['key'], dict)`.

This module is RELOADABLE.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Request:
    """All ephemeral per-request state, constructed on first touch and popped on completion.

    Field lifecycle per HTTP roundtrip:

    - REQUEST_HEADERS   → sets `pending_headers`
    - REQUEST           → sets `turn_index`, `body`, `provider`
                          (consumes `pending_headers` — stays for complete-response cache zones)
    - RESPONSE_HEADERS  → sets `response_status`, `response_headers`
    - RESPONSE_PROGRESS → upserts `current_turn_usage`
    - RESPONSE_COMPLETE → reads everything, commits combined turn, registry pops the record
    """

    request_id: str
    pending_headers: dict[str, str] | None = None
    turn_index: int = -1
    body: object = None
    provider: str = ""
    response_status: int = 0
    response_headers: dict[str, str] = field(default_factory=dict)
    current_turn_usage: dict | None = None


class RequestRegistry:
    """Ephemeral per-request state. get_or_create on event arrival; pop on completion.

    // [LAW:single-enforcer] The only place Request records are constructed.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, Request] = {}

    def get_or_create(self, request_id: str) -> Request:
        """Idempotent lookup-or-create. Always returns a Request.

        // [LAW:dataflow-not-control-flow] Never returns None — caller never branches.
        """
        req = self._by_id.get(request_id)
        if req is None:
            req = Request(request_id=request_id)
            self._by_id[request_id] = req
        return req

    def get(self, request_id: str) -> Request | None:
        return self._by_id.get(request_id)

    def pop(self, request_id: str) -> Request | None:
        return self._by_id.pop(request_id, None)

    def focused_usage(self, focused_id: str | None) -> dict | None:
        """Return current_turn_usage for the focused request, or None.

        // [LAW:dataflow-not-control-flow] One typed read; no isinstance guards.
        """
        if not focused_id:
            return None
        req = self._by_id.get(focused_id)
        return req.current_turn_usage if req is not None else None
