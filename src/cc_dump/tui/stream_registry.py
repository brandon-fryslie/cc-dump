"""Request-scoped stream identity and lane attribution.

// [LAW:one-source-of-truth] This module is the single owner of request_id ->
// stream context and session_id -> lane assignment.
// [LAW:single-enforcer] Agent/main/subagent classification happens only here.
"""

from dataclasses import dataclass

import cc_dump.formatting


LaneKind = str  # "main" | "subagent" | "unknown"


@dataclass(frozen=True)
class StreamLane:
    """Stable lane identity for one API session."""

    lane_id: str
    lane_kind: LaneKind
    agent_label: str
    session_id: str


@dataclass
class RequestStreamContext:
    """Per-request stream metadata used by UI and block attribution."""

    request_id: str
    session_id: str
    lane_id: str
    agent_kind: LaneKind
    agent_label: str
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
    parsed = cc_dump.formatting.parse_user_id(user_id)
    if not parsed:
        return ""
    session_id = parsed.get("session_id", "")
    return session_id if isinstance(session_id, str) else ""


class StreamRegistry:
    """Canonical registry for request and lane identity."""

    def __init__(self) -> None:
        self._contexts: dict[str, RequestStreamContext] = {}
        self._session_lanes: dict[str, StreamLane] = {}
        self._next_subagent_index: int = 1

    def _allocate_lane(self, session_id: str, request_id: str) -> StreamLane:
        """Return lane for a session, allocating if needed."""
        if not session_id:
            rid = request_id[:8]
            return StreamLane(
                lane_id=f"unknown-{rid}",
                lane_kind="unknown",
                agent_label=f"unknown {rid}",
                session_id="",
            )
        existing = self._session_lanes.get(session_id)
        if existing is not None:
            return existing

        # // [LAW:dataflow-not-control-flow] Lane kind is derived from the count
        # of known sessions, not branched by ad-hoc flags.
        if not self._session_lanes:
            lane = StreamLane(
                lane_id="main",
                lane_kind="main",
                agent_label="main",
                session_id=session_id,
            )
        else:
            idx = self._next_subagent_index
            self._next_subagent_index += 1
            lane = StreamLane(
                lane_id=f"subagent-{idx}",
                lane_kind="subagent",
                agent_label=f"subagent {idx}",
                session_id=session_id,
            )
        self._session_lanes[session_id] = lane
        return lane

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
            lane = self._allocate_lane("", request_id)
            ctx = RequestStreamContext(
                request_id=request_id,
                session_id=lane.session_id,
                lane_id=lane.lane_id,
                agent_kind=lane.lane_kind,
                agent_label=lane.agent_label,
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
    ) -> RequestStreamContext:
        """Register request metadata and return request context."""
        session_id = _extract_session_id(body)
        lane = self._allocate_lane(session_id, request_id)

        ctx = self._contexts.get(request_id)
        if ctx is None:
            ctx = RequestStreamContext(
                request_id=request_id,
                session_id=lane.session_id,
                lane_id=lane.lane_id,
                agent_kind=lane.lane_kind,
                agent_label=lane.agent_label,
                seq=seq,
                recv_ns=recv_ns,
            )
            self._contexts[request_id] = ctx
            return ctx

        ctx.session_id = lane.session_id
        ctx.lane_id = lane.lane_id
        ctx.agent_kind = lane.lane_kind
        ctx.agent_label = lane.agent_label
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

