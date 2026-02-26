"""Domain store — append-only domain data for FormattedBlock trees.

// [LAW:one-source-of-truth] All block lists live here.
// [LAW:one-way-deps] No widget imports. No rendering imports.

RELOADABLE — hot-reload can update this module's code. The DomainStore
instance persists on the app object across widget replacement.
"""

import os
from collections.abc import Callable

import cc_dump.core.formatting


class DomainStore:
    """Append-only domain data. Single owner of FormattedBlock trees.

    Callbacks are registered by ConversationView for rendering notifications.
    All mutations go through public methods; callbacks fire after mutation.
    """

    def __init__(self, max_completed_turns: int | None = None):
        if max_completed_turns is None:
            raw = str(os.environ.get("CC_DUMP_MAX_COMPLETED_TURNS", "5000") or "").strip()
            try:
                max_completed_turns = int(raw)
            except ValueError:
                max_completed_turns = 5000
        self._max_completed_turns = max(0, max_completed_turns)
        self._completed: list[list] = []  # sealed turn block lists
        self._stream_turns: dict[str, list] = {}  # active stream block lists
        self._stream_delta_buffers: dict[str, list[str]] = {}  # text delta accumulators
        self._stream_delta_text: dict[str, str] = {}  # incremental joined text
        self._stream_delta_versions: dict[str, int] = {}  # incremented per appended delta
        self._stream_meta: dict[str, dict] = {}
        self._stream_order: list[str] = []
        # Recently completed stream chips retained until a new stream begins.
        # Item shape: (request_id, label, kind)
        self._recent_stream_chips: list[tuple[str, str, str]] = []
        self._focused_stream_id: str | None = None
        # Session boundary index: (session_id, turn_index) pairs for within-tab navigation.
        # // [LAW:one-source-of-truth] Derived from NewSessionBlock presence in turn data.
        self._session_boundaries: list[tuple[str, int]] = []

        # Callbacks — ConversationView registers these
        self.on_turn_added: Callable | None = None
        self.on_stream_started: Callable | None = None
        self.on_stream_block: Callable | None = None
        self.on_stream_finalized: Callable | None = None
        self.on_focus_changed: Callable | None = None
        self.on_turns_pruned: Callable[[int], None] | None = None

    # ─── Completed turns ──────────────────────────────────────────────

    def add_turn(self, blocks: list) -> None:
        """Add a completed turn (sealed block list)."""
        index = len(self._completed)
        self._completed.append(blocks)
        # Index session boundaries for within-tab navigation.
        for block in blocks:
            if type(block).__name__ == "NewSessionBlock":
                sid = getattr(block, "session_id", "")
                if sid:
                    self._session_boundaries.append((sid, index))
                break
        if self.on_turn_added is not None:
            self.on_turn_added(blocks, index)
        self._enforce_completed_retention()

    # ─── Request-scoped streaming ─────────────────────────────────────

    def begin_stream(self, request_id: str, meta: dict | None = None) -> None:
        """Create an active stream bucket for request_id.

        // [LAW:one-source-of-truth] request_id is canonical stream identity.
        """
        if request_id in self._stream_turns:
            if meta:
                self._stream_meta[request_id] = dict(meta)
            return

        # [LAW:one-source-of-truth] Recent chip lifecycle is owned here.
        self._recent_stream_chips = []
        self._stream_turns[request_id] = []
        self._stream_delta_buffers[request_id] = []
        self._stream_delta_text[request_id] = ""
        self._stream_delta_versions[request_id] = 0
        self._stream_meta[request_id] = dict(meta or {})
        self._stream_order.append(request_id)

        if self._focused_stream_id is None:
            self._focused_stream_id = request_id

        if self.on_stream_started is not None:
            self.on_stream_started(request_id, self._stream_meta[request_id])

    def append_stream_block(self, request_id: str, block) -> None:
        """Append a block to the request-scoped stream."""
        if request_id not in self._stream_turns:
            self.begin_stream(request_id)

        self._stream_turns[request_id].append(block)

        # // [LAW:dataflow-not-control-flow] Block declares streaming behavior via property
        if block.show_during_streaming:
            self._stream_delta_buffers[request_id].append(block.content)
            # // [LAW:one-source-of-truth] Incremental text buffer avoids repeated joins in render path.
            self._stream_delta_text[request_id] = self._stream_delta_text.get(request_id, "") + block.content
            self._stream_delta_versions[request_id] = self._stream_delta_versions.get(request_id, 0) + 1

        if self.on_stream_block is not None:
            self.on_stream_block(request_id, block)

    def finalize_stream(self, request_id: str) -> list:
        """Finalize a request-scoped stream.

        Consolidates TextDeltaBlocks into TextContentBlocks, wraps content
        in MessageBlock container, populates content_regions. Removes from
        active stream registries. Adds to completed turns.

        Returns the final consolidated block list.
        """
        blocks = self._stream_turns.get(request_id)
        if blocks is None:
            return []

        was_focused = request_id == self._focused_stream_id

        # ── Domain logic: consolidate deltas ──
        consolidated: list = []
        delta_buffer: list[str] = []

        for block in blocks:
            if type(block).__name__ == "TextDeltaBlock":
                delta_buffer.append(block.content)
            else:
                if delta_buffer:
                    combined_text = "".join(delta_buffer)
                    consolidated.append(
                        cc_dump.core.formatting.TextContentBlock(
                            content=combined_text,
                            category=cc_dump.core.formatting.Category.ASSISTANT,
                        )
                    )
                    delta_buffer.clear()
                consolidated.append(block)

        if delta_buffer:
            combined_text = "".join(delta_buffer)
            consolidated.append(
                cc_dump.core.formatting.TextContentBlock(
                    content=combined_text,
                    category=cc_dump.core.formatting.Category.ASSISTANT,
                )
            )

        # ── Domain logic: wrap in MessageBlock ──
        _metadata_types = {"StreamInfoBlock", "StopReasonBlock"}
        content_children = [
            b for b in consolidated if type(b).__name__ not in _metadata_types
        ]
        metadata = [
            b for b in consolidated if type(b).__name__ in _metadata_types
        ]
        consolidated = (
            metadata[:1]
            + [
                cc_dump.core.formatting.MessageBlock(
                    role="assistant",
                    msg_index=0,
                    children=content_children,
                    category=cc_dump.core.formatting.Category.ASSISTANT,
                )
            ]
            + metadata[1:]
        )

        # ── Domain logic: populate content_regions ──
        # // [LAW:single-enforcer] Uses module-level import for hot-reload safety
        def _walk_populate(block_list):
            for block in block_list:
                cc_dump.core.formatting.populate_content_regions(block)
                _walk_populate(getattr(block, "children", []))

        _walk_populate(consolidated)

        self._seal_stream(request_id, consolidated, was_focused=was_focused)
        return consolidated

    def finalize_stream_with_blocks(self, request_id: str, final_blocks: list) -> list:
        """Finalize a request-scoped stream using externally assembled blocks.

        // [LAW:one-source-of-truth] Complete-response assembly happens upstream;
        // this method only seals stream lifecycle in DomainStore.
        """
        blocks = self._stream_turns.get(request_id)
        if blocks is None:
            return []

        was_focused = request_id == self._focused_stream_id
        sealed = list(final_blocks)
        self._seal_stream(request_id, sealed, was_focused=was_focused)
        return sealed

    def _seal_stream(self, request_id: str, sealed_blocks: list, *, was_focused: bool) -> None:
        """Common stream shutdown path for both local and upstream assembly."""
        meta = self._stream_meta.get(request_id, {})
        recent_label = str(meta.get("agent_label") or request_id[:8])
        recent_kind = str(meta.get("agent_kind") or "unknown")

        # ── Registry cleanup ──
        self._stream_turns.pop(request_id, None)
        self._stream_delta_buffers.pop(request_id, None)
        self._stream_delta_text.pop(request_id, None)
        self._stream_delta_versions.pop(request_id, None)
        self._stream_meta.pop(request_id, None)
        self._stream_order = [
            rid for rid in self._stream_order if rid != request_id
        ]

        # Add to completed turns
        self._completed.append(sealed_blocks)
        self._recent_stream_chips.append((request_id, f"{recent_label} \u2713", recent_kind))

        # Update focus
        if was_focused:
            self._focused_stream_id = (
                self._stream_order[0] if self._stream_order else None
            )

        if self.on_stream_finalized is not None:
            self.on_stream_finalized(request_id, sealed_blocks, was_focused)
        self._enforce_completed_retention()

    def _enforce_completed_retention(self) -> None:
        """Apply completed-turn retention policy and notify renderer."""
        if self._max_completed_turns <= 0:
            return
        overflow = len(self._completed) - self._max_completed_turns
        if overflow <= 0:
            return
        del self._completed[:overflow]
        # Adjust session boundary indices after pruning.
        self._session_boundaries = [
            (sid, idx - overflow)
            for sid, idx in self._session_boundaries
            if idx >= overflow
        ]
        if self.on_turns_pruned is not None:
            self.on_turns_pruned(overflow)

    def set_focused_stream(self, request_id: str) -> bool:
        """Focus an active stream for live rendering preview."""
        if request_id not in self._stream_turns:
            return False
        self._focused_stream_id = request_id
        if self.on_focus_changed is not None:
            self.on_focus_changed(request_id)
        return True

    # ─── Read-only accessors ──────────────────────────────────────────

    def get_focused_stream_id(self) -> str | None:
        return self._focused_stream_id

    def get_session_boundaries(self) -> list[tuple[str, int]]:
        """Return (session_id, turn_index) pairs for all session boundaries."""
        return list(self._session_boundaries)

    def get_delta_text(self, request_id: str) -> list[str]:
        """Return the accumulated delta text buffer for a stream."""
        return self._stream_delta_buffers.get(request_id, [])

    def get_delta_preview_text(self, request_id: str) -> str:
        """Return concatenated delta text for streaming preview rendering."""
        return self._stream_delta_text.get(request_id, "")

    def get_delta_version(self, request_id: str) -> int:
        """Return monotonic delta version for change detection."""
        return self._stream_delta_versions.get(request_id, 0)

    def get_stream_blocks(self, request_id: str) -> list:
        """Return the block list for an active stream."""
        return self._stream_turns.get(request_id, [])

    def get_active_stream_ids(self) -> tuple[str, ...]:
        """Return request_ids for currently active streams in display order."""
        return tuple(
            request_id
            for request_id in self._stream_order
            if request_id in self._stream_turns
        )

    def get_completed_lane_counts(self) -> dict[str, int]:
        """Return completed turn counts by agent_kind.

        // [LAW:one-source-of-truth] Lane counts are derived from stamped block attribution.
        """
        counts = {"main": 0, "subagent": 0, "unknown": 0}
        for turn in self._completed:
            kind = "unknown"
            for block in turn:
                value = str(getattr(block, "agent_kind", "") or "")
                if value:
                    kind = value
                    break
            counts[kind] = counts.get(kind, 0) + 1
        return counts

    def get_active_lane_counts(self) -> dict[str, int]:
        """Return active stream counts by agent_kind."""
        counts = {"main": 0, "subagent": 0, "unknown": 0}
        for request_id in self._stream_order:
            if request_id not in self._stream_turns:
                continue
            meta = self._stream_meta.get(request_id, {})
            kind = str(meta.get("agent_kind") or "unknown")
            counts[kind] = counts.get(kind, 0) + 1
        return counts

    def restamp_stream(
        self,
        request_id: str,
        *,
        session_id: str,
        lane_id: str,
        agent_kind: str,
        agent_label: str,
    ) -> bool:
        """Restamp an active stream's metadata and block attribution.

        Returns True if request_id is an active stream and was restamped.
        """
        blocks = self._stream_turns.get(request_id)
        if blocks is None:
            return False

        # // [LAW:one-source-of-truth] Stream chip labels derive from _stream_meta.
        meta = self._stream_meta.get(request_id)
        if meta is None:
            meta = {}
            self._stream_meta[request_id] = meta
        meta["session_id"] = session_id
        meta["lane_id"] = lane_id
        meta["agent_kind"] = agent_kind
        meta["agent_label"] = agent_label

        def _stamp_tree(block) -> None:
            block.session_id = session_id
            block.lane_id = lane_id
            block.agent_kind = agent_kind
            block.agent_label = agent_label
            for child in getattr(block, "children", []):
                _stamp_tree(child)

        for block in blocks:
            _stamp_tree(block)
        return True

    def get_active_stream_chips(self) -> tuple[tuple[str, str, str], ...]:
        """Return active stream tuples for footer chips.

        Tuple item shape: (request_id, label, kind)
        """
        result: list[tuple[str, str, str]] = []
        active_ids: set[str] = set()
        for request_id in self._stream_order:
            if request_id not in self._stream_turns:
                continue
            meta = self._stream_meta.get(request_id, {})
            label = str(meta.get("agent_label") or request_id[:8])
            kind = str(meta.get("agent_kind") or "unknown")
            result.append((request_id, label, kind))
            active_ids.add(request_id)
        for request_id, label, kind in self._recent_stream_chips:
            if request_id in active_ids:
                continue
            result.append((request_id, label, kind))
        return tuple(result)

    def iter_completed_blocks(self) -> list[list]:
        """Return all completed turn block lists."""
        return self._completed

    @property
    def completed_count(self) -> int:
        return len(self._completed)

    # ─── State management (hot-reload) ────────────────────────────────

    def get_state(self) -> dict:
        """Extract state for serialization.

        Note: DomainStore persists on the app object across widget
        replacement, so this is rarely needed. Provided for robustness.
        """
        active_streams = {}
        for rid in self._stream_order:
            if rid not in self._stream_turns:
                continue
            active_streams[rid] = {
                "blocks": self._stream_turns[rid],
                "delta_buffers": list(self._stream_delta_buffers.get(rid, [])),
                "meta": dict(self._stream_meta.get(rid, {})),
            }

        return {
            "completed": list(self._completed),
            "active_streams": active_streams,
            "stream_order": list(self._stream_order),
            "recent_stream_chips": list(self._recent_stream_chips),
            "focused_stream_id": self._focused_stream_id,
            "session_boundaries": list(self._session_boundaries),
        }

    def restore_state(self, state: dict) -> None:
        """Restore state from serialized dict."""
        self._completed = list(state.get("completed", []))
        self._stream_turns.clear()
        self._stream_delta_buffers.clear()
        self._stream_delta_text.clear()
        self._stream_delta_versions.clear()
        self._stream_meta.clear()
        self._stream_order.clear()
        self._recent_stream_chips.clear()
        self._focused_stream_id = None
        self._session_boundaries.clear()

        active_streams = state.get("active_streams", {})
        if isinstance(active_streams, dict):
            for request_id, payload in active_streams.items():
                if not isinstance(payload, dict):
                    continue
                rid = str(request_id)
                self._stream_turns[rid] = payload.get("blocks", [])
                delta_buffers = list(payload.get("delta_buffers", []))
                self._stream_delta_buffers[rid] = delta_buffers
                # // [LAW:one-source-of-truth] Derive concatenated text/version from buffer payload once.
                self._stream_delta_text[rid] = "".join(delta_buffers)
                self._stream_delta_versions[rid] = len(delta_buffers)
                self._stream_meta[rid] = dict(payload.get("meta", {}))

            order = state.get("stream_order", [])
            if isinstance(order, list):
                self._stream_order = [
                    rid for rid in order if rid in self._stream_turns
                ]
            if not self._stream_order:
                self._stream_order = list(self._stream_turns.keys())

        recent_stream_chips = state.get("recent_stream_chips", [])
        if isinstance(recent_stream_chips, list):
            parsed_recent: list[tuple[str, str, str]] = []
            for item in recent_stream_chips:
                if not isinstance(item, (list, tuple)) or len(item) != 3:
                    continue
                rid, label, kind = item
                parsed_recent.append((str(rid), str(label), str(kind)))
            self._recent_stream_chips = parsed_recent

        focused = state.get("focused_stream_id")
        if isinstance(focused, str) and focused in self._stream_turns:
            self._focused_stream_id = focused
        elif self._stream_order:
            self._focused_stream_id = self._stream_order[0]

        raw_boundaries = state.get("session_boundaries", [])
        if isinstance(raw_boundaries, list):
            for item in raw_boundaries:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    sid, idx = item
                    if isinstance(sid, str) and isinstance(idx, int):
                        self._session_boundaries.append((sid, idx))
