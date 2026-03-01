"""Request-scoped stream identity.

// [LAW:one-source-of-truth] This module is the single owner of request_id ->
// stream context and session_id extraction.
"""

from dataclasses import dataclass

import cc_dump.core.formatting


@dataclass
class RequestStreamContext:
    """Per-request stream metadata used by UI."""

    request_id: str
    session_id: str
    seq: int = 0
    recv_ns: int = 0
    state: str = "requested"  # requested | streaming | done


def _extract_session_id(body: dict | None) -> str:
    """Extract Claude session_id from request body metadata.user_id."""
    if not isinstance(body, dict):
        return ""
    metadata = body.get("metadata", {})
    if not isinstance(metadata, dict):
        return ""
    user_id = metadata.get("user_id", "")
    if not isinstance(user_id, str) or not user_id:
        return ""
    parsed = cc_dump.core.formatting.parse_user_id(user_id)
    if not parsed:
        return ""
    session_id = parsed.get("session_id", "")
    return session_id if isinstance(session_id, str) else ""


class StreamRegistry:
    """Canonical registry for request stream identity."""

    def __init__(self) -> None:
        self._contexts: dict[str, RequestStreamContext] = {}

    def ensure_context(
        self,
        request_id: str,
        *,
        seq: int = 0,
        recv_ns: int = 0,
    ) -> RequestStreamContext:
        """Get or create context for request_id."""
        ctx = self._contexts.get(request_id)
        if ctx is None:
            ctx = RequestStreamContext(
                request_id=request_id,
                session_id="",
                seq=seq,
                recv_ns=recv_ns,
            )
            self._contexts[request_id] = ctx
            return ctx
        ctx.seq = seq
        ctx.recv_ns = recv_ns
        return ctx

    def register_request(
        self,
        request_id: str,
        body: dict | None,
        *,
        seq: int = 0,
        recv_ns: int = 0,
        session_hint: str = "",
    ) -> RequestStreamContext:
        """Register request metadata and return request context."""
        session_id = _extract_session_id(body) or session_hint

        ctx = self._contexts.get(request_id)
        if ctx is None:
            ctx = RequestStreamContext(
                request_id=request_id,
                session_id=session_id,
                seq=seq,
                recv_ns=recv_ns,
            )
            self._contexts[request_id] = ctx
            return ctx

        ctx.session_id = session_id
        ctx.seq = seq
        ctx.recv_ns = recv_ns
        return ctx

    def mark_streaming(self, request_id: str, *, seq: int = 0, recv_ns: int = 0) -> RequestStreamContext:
        ctx = self.ensure_context(request_id, seq=seq, recv_ns=recv_ns)
        ctx.state = "streaming"
        return ctx

    def mark_done(self, request_id: str, *, seq: int = 0, recv_ns: int = 0) -> RequestStreamContext:
        ctx = self.ensure_context(request_id, seq=seq, recv_ns=recv_ns)
        ctx.state = "done"
        return ctx

    def get(self, request_id: str) -> RequestStreamContext | None:
        return self._contexts.get(request_id)
