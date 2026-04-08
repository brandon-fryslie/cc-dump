"""StreamingPreviewManager — per-request streaming preview state + render flow.

// [LAW:one-source-of-truth] Owns all preview turn bookkeeping:
//   - stream_preview_turns: dict[request_id, TurnData]
//   - attached_stream_id: str | None
//   - pending_delta_request_ids: set[str]
//   - delta_flush_scheduled: bool
//
// Previously these four fields lived on ConversationView with scattered
// `if self._attached_stream_id and self._turns[-1].is_streaming` guards on
// every mutation path. The manager concentrates that state so the render
// side of streaming is isolated from TurnStore + ScrollCoordinator.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import cc_dump.core.formatting
import cc_dump.tui.rendering

if TYPE_CHECKING:
    from cc_dump.tui.widget_factory import ConversationView, TurnData

logger = logging.getLogger(__name__)


class StreamingPreviewManager:
    """Render-side owner of in-flight stream previews keyed by request_id."""

    def __init__(self, host: "ConversationView") -> None:
        # // [LAW:locality-or-seam] The host back-reference is the only coupling
        # // point. All mutations to CV state funnel through named methods.
        self._host = host
        self.stream_preview_turns: dict[str, "TurnData"] = {}
        self.attached_stream_id: str | None = None
        self.pending_delta_request_ids: set[str] = set()
        self.delta_flush_scheduled: bool = False

    # ─── Cleanup / reset helpers ────────────────────────────────────────

    def reset(self) -> None:
        """Clear all preview state (used by hydrate/rebuild)."""
        self.stream_preview_turns.clear()
        self.attached_stream_id = None
        self.pending_delta_request_ids.clear()
        self.delta_flush_scheduled = False

    # ─── Attach/detach preview turn as last entry in the turn list ──────

    def attach_focused(self) -> None:
        """Ensure the focused active stream preview is the last turn."""
        host = self._host
        ds = host._domain_store
        focused = ds.get_focused_stream_id()
        if not focused or focused not in self.stream_preview_turns:
            self.detach()
            return

        turns = host._turn_store.turns
        if self.attached_stream_id == focused and turns and turns[-1].is_streaming:
            return

        self.detach()
        td = self.stream_preview_turns[focused]
        td.turn_index = len(turns)
        turns.append(td)
        self.attached_stream_id = focused
        host._recalculate_offsets()

    def attach(self) -> None:
        self.attach_focused()

    def detach(self) -> None:
        host = self._host
        if self.attached_stream_id is None:
            return
        turns = host._turn_store.turns
        if turns and turns[-1].is_streaming:
            turns.pop()
        self.attached_stream_id = None
        host._recalculate_offsets()

    # ─── Stream lifecycle render handlers ───────────────────────────────

    def render_started(self, request_id: str, meta: dict | None = None) -> None:
        if request_id in self.stream_preview_turns:
            return
        from cc_dump.tui.widget_factory import TurnData  # avoid cycle at import time
        td = TurnData(
            turn_index=-1,
            blocks=[],
            strips=[],
            is_streaming=True,
        )
        self.stream_preview_turns[request_id] = td
        self.attach()

    def on_preview_cleanup(self, request_id: str, was_focused: bool) -> None:
        if was_focused:
            self.detach()
        self.stream_preview_turns.pop(request_id, None)
        self.pending_delta_request_ids.discard(request_id)
        self.attach()

    def refresh_streaming_delta(
        self,
        request_id: str,
        td: "TurnData",
        *,
        force: bool = False,
        width: int | None = None,
    ) -> bool:
        """Re-render delta buffer with lightweight streaming preview."""
        from cc_dump.tui.widget_factory import _compute_widest, _next_strip_version
        host = self._host
        width = (
            width
            if width is not None
            else (host._content_width if host._size_known else host._last_width)
        )
        ds = host._domain_store
        delta_version = ds.get_delta_version(request_id)
        if (
            not force
            and delta_version == td._stream_last_delta_version
            and width == td._stream_last_render_width
        ):
            return False

        delta_text = ds.get_delta_preview_text(request_id)
        if not delta_text:
            td.strips = td.strips[: td._stable_strip_count]
            td._strip_version = _next_strip_version()
            td._widest_strip = _compute_widest(td.strips)
            td._stream_last_delta_version = delta_version
            td._stream_last_render_width = width
            return True

        console = host.app.console
        delta_strips = cc_dump.tui.rendering.render_streaming_preview(
            delta_text, console, width, runtime=host._render_runtime
        )

        td.strips = td.strips[: td._stable_strip_count] + delta_strips
        td._strip_version = _next_strip_version()
        td._widest_strip = _compute_widest(td.strips)
        td._stream_last_delta_version = delta_version
        td._stream_last_render_width = width
        return True

    def queue_delta(self, request_id: str) -> None:
        """Coalesce streaming delta paints to one invalidate per UI tick."""
        self.pending_delta_request_ids.add(request_id)
        if self.delta_flush_scheduled:
            return
        self.delta_flush_scheduled = True
        self._host.call_later(self.flush_delta_frame)

    def flush_delta_frame(self) -> None:
        host = self._host
        self.delta_flush_scheduled = False
        pending = self.pending_delta_request_ids
        self.pending_delta_request_ids = set()
        if not pending:
            return
        focused_id = host._domain_store.get_focused_stream_id()
        if not focused_id or focused_id not in pending:
            return
        host._invalidate("stream_delta", request_id=focused_id)

    def on_stream_block(self, request_id: str, block) -> None:
        td = self.stream_preview_turns.get(request_id)
        if td is None:
            return
        focused_id = self._host._domain_store.get_focused_stream_id()
        is_focused = request_id == focused_id
        if block.show_during_streaming and is_focused:
            self.queue_delta(request_id)

    def render_delta(self, request_id: str = "") -> None:
        td = self.stream_preview_turns.get(request_id)
        if td is None:
            return
        self.attach()
        if self.refresh_streaming_delta(request_id, td):
            self._host._recalculate_offsets()

    def finalize_turn_data(
        self,
        td: "TurnData | None",
        *,
        final_blocks: list,
        strips: list,
        block_strip_map: dict,
        flat_blocks: list,
    ) -> "TurnData":
        """Return finalized TurnData, reusing preview TurnData when possible."""
        from cc_dump.tui.widget_factory import TurnData
        if td is None:
            return TurnData(
                turn_index=-1,
                blocks=final_blocks,
                strips=strips,
                block_strip_map=block_strip_map,
                _flat_blocks=flat_blocks,
                is_streaming=False,
            )
        td.blocks = final_blocks
        td.strips = strips
        td.block_strip_map = block_strip_map
        td._flat_blocks = flat_blocks
        td.rebuild_block_derivatives()
        return td

    def render_finalized(
        self,
        request_id: str,
        final_blocks: list,
        was_focused: bool = False,
    ) -> None:
        from cc_dump.tui.widget_factory import _compute_widest, _next_strip_version
        host = self._host
        td = self.stream_preview_turns.get(request_id)

        if was_focused:
            self.detach()

        width = host._content_width if host._size_known else host._last_width
        console = host.app.console
        strips, block_strip_map, flat_blocks = cc_dump.tui.rendering.render_turn_to_strips(
            final_blocks,
            host._last_filters,
            console,
            width,
            block_cache=host._block_strip_cache,
            overrides=host._view_overrides,
            runtime=host._render_runtime,
        )

        td = self.finalize_turn_data(
            td,
            final_blocks=final_blocks,
            strips=strips,
            block_strip_map=block_strip_map,
            flat_blocks=flat_blocks,
        )
        td._strip_version = _next_strip_version()
        td._widest_strip = _compute_widest(td.strips)
        td.is_streaming = False
        td._text_delta_buffer.clear()
        td._stable_strip_count = 0
        td._stream_last_delta_version = -1
        td._stream_last_render_width = 0

        td._last_filter_snapshot = {
            k: host._last_filters.get(k, cc_dump.core.formatting.ALWAYS_VISIBLE)
            for k in td.relevant_filter_keys
        }
        td._filter_revision = host._active_filter_revision
        host._turn_store.index_blocks(final_blocks)

        self.stream_preview_turns.pop(request_id, None)
        self.pending_delta_request_ids.discard(request_id)

        host._append_completed_turn(td)
        self.attach()

    def render_focus_changed(self, request_id: str) -> None:
        self.pending_delta_request_ids.discard(request_id)
        td = self.stream_preview_turns.get(request_id)
        if td is not None:
            self.refresh_streaming_delta(request_id, td, force=True)
        self.attach()
