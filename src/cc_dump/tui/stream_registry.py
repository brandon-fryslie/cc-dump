"""Request-scoped stream identity and lane attribution.

// [LAW:one-source-of-truth] This module is the single owner of request_id ->
// stream context and session_id -> lane assignment.
// [LAW:single-enforcer] Agent/main/subagent classification happens only here.
"""

from dataclasses import dataclass

import cc_dump.core.formatting


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
    parsed = cc_dump.core.formatting.parse_user_id(user_id)
    if not parsed:
        return ""
    session_id = parsed.get("session_id", "")
    return session_id if isinstance(session_id, str) else ""


def _extract_task_lineage_ids(body: dict | None) -> set[str]:
    """Return Task tool_use IDs that have matching user tool_result IDs.

    // [LAW:one-source-of-truth] Task lineage is derived from in-band request
    messages; no runtime dependency on external Claude logs.
    """
    if not isinstance(body, dict):
        return set()
    raw_messages = body.get("messages", [])
    if not isinstance(raw_messages, list):
        return set()

    task_use_ids: set[str] = set()
    tool_result_ids: set[str] = set()
    for msg in raw_messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "")
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            if block_type == "tool_use" and role == "assistant" and block.get("name", "") == "Task":
                tool_use_id = block.get("id", "")
                if isinstance(tool_use_id, str) and tool_use_id:
                    task_use_ids.add(tool_use_id)
                continue
            if block_type == "tool_result" and role == "user":
                tool_result_id = block.get("tool_use_id", "")
                if isinstance(tool_result_id, str) and tool_result_id:
                    tool_result_ids.add(tool_result_id)
    return task_use_ids & tool_result_ids


class StreamRegistry:
    """Canonical registry for request and lane identity."""

    def __init__(self) -> None:
        self._contexts: dict[str, RequestStreamContext] = {}
        self._session_lanes: dict[str, StreamLane] = {}
        self._next_subagent_index: int = 1
        self._main_session_id: str = ""
        self._pending_task_request_ids: set[str] = set()

    def _sync_session_contexts(self, session_id: str, lane: StreamLane) -> None:
        """Update all known request contexts for one session."""
        if not session_id:
            return
        for ctx in self._contexts.values():
            if ctx.session_id != session_id:
                continue
            ctx.lane_id = lane.lane_id
            ctx.agent_kind = lane.lane_kind
            ctx.agent_label = lane.agent_label

    def _make_subagent_lane(self, session_id: str) -> StreamLane:
        idx = self._next_subagent_index
        self._next_subagent_index += 1
        return StreamLane(
            lane_id=f"subagent-{idx}",
            lane_kind="subagent",
            agent_label=f"subagent {idx}",
            session_id=session_id,
        )

    def _adopt_main_session(self, session_id: str) -> None:
        """Promote session_id to canonical main session lane."""
        if not session_id:
            return

        previous_main = self._main_session_id
        if previous_main and previous_main != session_id:
            previous_lane = self._session_lanes.get(previous_main)
            if previous_lane is not None and previous_lane.lane_kind == "main":
                demoted = self._make_subagent_lane(previous_main)
                self._session_lanes[previous_main] = demoted
                self._sync_session_contexts(previous_main, demoted)

        main_lane = StreamLane(
            lane_id="main",
            lane_kind="main",
            agent_label="main",
            session_id=session_id,
        )
        self._main_session_id = session_id
        self._session_lanes[session_id] = main_lane
        self._sync_session_contexts(session_id, main_lane)

    def _allocate_lane(self, session_id: str, request_id: str, *, session_hint: str = "") -> StreamLane:
        """Return lane for a session, allocating if needed."""
        if not session_id:
            rid = request_id[:8]
            return StreamLane(
                lane_id=f"unknown-{rid}",
                lane_kind="unknown",
                agent_label=f"unknown {rid}",
                session_id="",
            )

        if session_hint and not self._main_session_id:
            self._adopt_main_session(session_hint)

        existing = self._session_lanes.get(session_id)
        if existing is not None:
            return existing

        if not self._main_session_id:
            # // [LAW:dataflow-not-control-flow] Startup fallback seeds canonical
            # main lane, then all later sessions are data-classified from it.
            self._adopt_main_session(session_id)
            return self._session_lanes[session_id]

        lane = self._make_subagent_lane(session_id)
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
        session_hint: str = "",
    ) -> RequestStreamContext:
        """Register request metadata and return request context."""
        session_id = _extract_session_id(body)
        has_pending_task = request_id in self._pending_task_request_ids

        # // [LAW:single-enforcer] Task lineage-based main-session promotion is
        # centralized in StreamRegistry and runs for every request.
        if _extract_task_lineage_ids(body) or (has_pending_task and session_id):
            self._adopt_main_session(session_id)
        if has_pending_task and session_id:
            self._pending_task_request_ids.discard(request_id)

        lane = self._allocate_lane(session_id, request_id, session_hint=session_hint)

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

    def note_task_tool_use(
        self,
        request_id: str,
        tool_use_id: str,
        *,
        seq: int = 0,
        recv_ns: int = 0,
    ) -> RequestStreamContext:
        """Promote the emitting request session to main via Task tool lineage."""
        _ = tool_use_id
        ctx = self.ensure_context(request_id, seq=seq, recv_ns=recv_ns)
        self._pending_task_request_ids.add(request_id)
        if ctx.session_id:
            self._adopt_main_session(ctx.session_id)
            self._pending_task_request_ids.discard(request_id)
            lane = self._session_lanes.get(ctx.session_id)
            if lane is not None:
                ctx.lane_id = lane.lane_id
                ctx.agent_kind = lane.lane_kind
                ctx.agent_label = lane.agent_label
        return ctx

    def mark_streaming(self, request_id: str, *, seq: int = 0, recv_ns: int = 0) -> RequestStreamContext:
        ctx = self.ensure_context(request_id, seq=seq, recv_ns=recv_ns)
        ctx.state = "streaming"
        return ctx

    def mark_done(self, request_id: str, *, seq: int = 0, recv_ns: int = 0) -> RequestStreamContext:
        ctx = self.ensure_context(request_id, seq=seq, recv_ns=recv_ns)
        ctx.state = "done"
        self._pending_task_request_ids.discard(request_id)
        return ctx

    def get(self, request_id: str) -> RequestStreamContext | None:
        return self._contexts.get(request_id)
