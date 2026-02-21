"""Domain store — append-only domain data for FormattedBlock trees.

// [LAW:one-source-of-truth] All block lists live here.
// [LAW:one-way-deps] No widget imports. No rendering imports.

RELOADABLE — hot-reload can update this module's code. The DomainStore
instance persists on the app object across widget replacement.
"""

from collections.abc import Callable

import cc_dump.formatting


class DomainStore:
    """Append-only domain data. Single owner of FormattedBlock trees.

    Callbacks are registered by ConversationView for rendering notifications.
    All mutations go through public methods; callbacks fire after mutation.
    """

    def __init__(self):
        self._completed: list[list] = []  # sealed turn block lists
        self._stream_turns: dict[str, list] = {}  # active stream block lists
        self._stream_delta_buffers: dict[str, list[str]] = {}  # text delta accumulators
        self._stream_meta: dict[str, dict] = {}
        self._stream_order: list[str] = []
        self._focused_stream_id: str | None = None

        # Callbacks — ConversationView registers these
        self.on_turn_added: Callable | None = None
        self.on_stream_started: Callable | None = None
        self.on_stream_block: Callable | None = None
        self.on_stream_finalized: Callable | None = None
        self.on_focus_changed: Callable | None = None

    # ─── Completed turns ──────────────────────────────────────────────

    def add_turn(self, blocks: list) -> None:
        """Add a completed turn (sealed block list)."""
        index = len(self._completed)
        self._completed.append(blocks)
        if self.on_turn_added is not None:
            self.on_turn_added(blocks, index)

    # ─── Request-scoped streaming ─────────────────────────────────────

    def begin_stream(self, request_id: str, meta: dict | None = None) -> None:
        """Create an active stream bucket for request_id.

        // [LAW:one-source-of-truth] request_id is canonical stream identity.
        """
        if request_id in self._stream_turns:
            if meta:
                self._stream_meta[request_id] = dict(meta)
            return

        self._stream_turns[request_id] = []
        self._stream_delta_buffers[request_id] = []
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
                        cc_dump.formatting.TextContentBlock(
                            content=combined_text,
                            category=cc_dump.formatting.Category.ASSISTANT,
                        )
                    )
                    delta_buffer.clear()
                consolidated.append(block)

        if delta_buffer:
            combined_text = "".join(delta_buffer)
            consolidated.append(
                cc_dump.formatting.TextContentBlock(
                    content=combined_text,
                    category=cc_dump.formatting.Category.ASSISTANT,
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
                cc_dump.formatting.MessageBlock(
                    role="assistant",
                    msg_index=0,
                    children=content_children,
                    category=cc_dump.formatting.Category.ASSISTANT,
                )
            ]
            + metadata[1:]
        )

        # ── Domain logic: populate content_regions ──
        # // [LAW:single-enforcer] Uses module-level import for hot-reload safety
        def _walk_populate(block_list):
            for block in block_list:
                cc_dump.formatting.populate_content_regions(block)
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
        # ── Registry cleanup ──
        self._stream_turns.pop(request_id, None)
        self._stream_delta_buffers.pop(request_id, None)
        self._stream_meta.pop(request_id, None)
        self._stream_order = [
            rid for rid in self._stream_order if rid != request_id
        ]

        # Add to completed turns
        self._completed.append(sealed_blocks)

        # Update focus
        if was_focused:
            self._focused_stream_id = (
                self._stream_order[0] if self._stream_order else None
            )

        if self.on_stream_finalized is not None:
            self.on_stream_finalized(request_id, sealed_blocks, was_focused)

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

    def get_delta_text(self, request_id: str) -> list[str]:
        """Return the accumulated delta text buffer for a stream."""
        return self._stream_delta_buffers.get(request_id, [])

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
        for request_id in self._stream_order:
            if request_id not in self._stream_turns:
                continue
            meta = self._stream_meta.get(request_id, {})
            label = str(meta.get("agent_label") or request_id[:8])
            kind = str(meta.get("agent_kind") or "unknown")
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
            "focused_stream_id": self._focused_stream_id,
        }

    def restore_state(self, state: dict) -> None:
        """Restore state from serialized dict."""
        self._completed = list(state.get("completed", []))
        self._stream_turns.clear()
        self._stream_delta_buffers.clear()
        self._stream_meta.clear()
        self._stream_order.clear()
        self._focused_stream_id = None

        active_streams = state.get("active_streams", {})
        if isinstance(active_streams, dict):
            for request_id, payload in active_streams.items():
                if not isinstance(payload, dict):
                    continue
                rid = str(request_id)
                self._stream_turns[rid] = payload.get("blocks", [])
                self._stream_delta_buffers[rid] = list(
                    payload.get("delta_buffers", [])
                )
                self._stream_meta[rid] = dict(payload.get("meta", {}))

            order = state.get("stream_order", [])
            if isinstance(order, list):
                self._stream_order = [
                    rid for rid in order if rid in self._stream_turns
                ]
            if not self._stream_order:
                self._stream_order = list(self._stream_turns.keys())

        focused = state.get("focused_stream_id")
        if isinstance(focused, str) and focused in self._stream_turns:
            self._focused_stream_id = focused
        elif self._stream_order:
            self._focused_stream_id = self._stream_order[0]
