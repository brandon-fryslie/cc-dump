"""Widget factory - creates widget instances that can be hot-swapped.

This module is RELOADABLE. When it reloads, the app can create new widget
instances from the updated class definitions and swap them in.
"""

import datetime
import json
import sys
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from textual.dom import NoScreen
from textual.widgets import RichLog, Static
from textual.scroll_view import ScrollView
from textual.selection import Selection
from textual.strip import Strip
from textual.cache import LRUCache
from textual.geometry import Size, Offset
from rich.segment import Segment
from rich.text import Text

# Use module-level imports for hot-reload
import cc_dump.formatting
import cc_dump.palette
import cc_dump.analysis
import cc_dump.tui.rendering
import cc_dump.tui.panel_renderers
import cc_dump.tui.error_indicator
import cc_dump.tui.view_overrides


# ─── Follow mode state machine ──────────────────────────────────────────────


class FollowState(Enum):
    OFF = "off"
    ENGAGED = "engaged"
    ACTIVE = "active"


# [LAW:dataflow-not-control-flow] Transitions as data, not branches.
# Key: (current_state, at_bottom) → new_state
_FOLLOW_TRANSITIONS: dict[tuple[FollowState, bool], FollowState] = {
    (FollowState.ACTIVE, True): FollowState.ACTIVE,
    (FollowState.ACTIVE, False): FollowState.ENGAGED,
    (FollowState.ENGAGED, True): FollowState.ACTIVE,
    (FollowState.ENGAGED, False): FollowState.ENGAGED,
    (FollowState.OFF, True): FollowState.OFF,
    (FollowState.OFF, False): FollowState.OFF,
}

_FOLLOW_TOGGLE: dict[FollowState, FollowState] = {
    FollowState.OFF: FollowState.ACTIVE,
    FollowState.ENGAGED: FollowState.OFF,
    FollowState.ACTIVE: FollowState.OFF,
}

_FOLLOW_SCROLL_BOTTOM: dict[FollowState, FollowState] = {
    FollowState.OFF: FollowState.OFF,
    FollowState.ENGAGED: FollowState.ACTIVE,
    FollowState.ACTIVE: FollowState.ACTIVE,
}

_FOLLOW_DEACTIVATE: dict[FollowState, FollowState] = {
    FollowState.OFF: FollowState.OFF,
    FollowState.ENGAGED: FollowState.ENGAGED,
    FollowState.ACTIVE: FollowState.ENGAGED,
}


def _compute_widest(strips: list) -> int:
    """Compute max cell_length across strips.

    O(m) but called once per strip assignment.
    """
    widest = 0
    for s in strips:
        w = s.cell_length
        if w > widest:
            widest = w
    return widest


@dataclass
class TurnData:
    """Pre-rendered turn data for Line API storage."""

    turn_index: int
    blocks: list  # list[FormattedBlock] - hierarchical source of truth
    strips: list  # list[Strip] - pre-rendered lines
    block_strip_map: dict = field(
        default_factory=dict
    )  # block_index → first strip line
    _flat_blocks: list = field(default_factory=list)  # flattened block list for click resolution
    relevant_filter_keys: set = field(default_factory=set)
    line_offset: int = 0  # start line in virtual space
    _last_filter_snapshot: dict = field(default_factory=dict)
    # Streaming fields
    is_streaming: bool = False
    _text_delta_buffer: list = field(
        default_factory=list
    )  # list[str] - accumulated delta text
    _stable_strip_count: int = 0  # boundary between stable and delta strips
    _widest_strip: int = 0  # cached max(s.cell_length for s in strips)
    _pending_filter_snapshot: dict | None = (
        None  # deferred filters for lazy off-viewport re-render
    )


    @property
    def line_count(self) -> int:
        return len(self.strips)

    def compute_relevant_keys(self):
        """Compute which filter keys affect this turn's blocks.

        Uses get_category() for lookup so blocks created before a
        hot-reload still match after the module is reloaded.
        Walks children recursively to capture categories from container blocks.
        """
        keys = set()
        def _walk(blocks):
            for block in blocks:
                cat = cc_dump.tui.rendering.get_category(block)
                if cat is not None:
                    keys.add(cat.value)
                for child in getattr(block, "children", []):
                    _walk([child])
        _walk(self.blocks)
        self.relevant_filter_keys = keys

    def re_render(
        self,
        filters: dict,
        console,
        width: int,
        force: bool = False,
        block_cache=None,
        search_ctx=None,
        overrides=None,
    ) -> bool:
        """Re-render if a relevant filter changed. Returns True if strips changed.

        Args:
            force: Force re-render even if filter snapshot hasn't changed.
            block_cache: Optional LRUCache for caching rendered strips per block.
            search_ctx: Optional SearchContext for highlighting matches.
            overrides: Optional ViewOverrides for per-block view state.
        """
        # Create snapshot using ALWAYS_VISIBLE default to match filters dict structure
        snapshot = {k: filters.get(k, cc_dump.formatting.ALWAYS_VISIBLE) for k in self.relevant_filter_keys}
        # Force re-render when search context changes
        if not force and search_ctx is None and snapshot == self._last_filter_snapshot:
            return False
        self._last_filter_snapshot = snapshot
        self._pending_filter_snapshot = None  # clear deferred state
        self.strips, self.block_strip_map, self._flat_blocks = cc_dump.tui.rendering.render_turn_to_strips(
            self.blocks,
            filters,
            console,
            width,
            block_cache=block_cache,
            search_ctx=search_ctx,
            turn_index=self.turn_index,
            overrides=overrides,
        )
        self._widest_strip = _compute_widest(self.strips)
        return True

    def strip_offset_for_block(self, block_index: int) -> int | None:
        """Return the first strip line for a given block index, or None if filtered out."""
        return self.block_strip_map.get(block_index)


@dataclass
class ScrollAnchor:
    """Block-level scroll anchor for stable scroll position across vis_state changes."""

    turn_index: int      # index into _turns
    block_index: int     # original block index (key in block_strip_map)
    line_in_block: int   # line offset within block's rendered strips


class ConversationView(ScrollView):
    """Virtual-rendering conversation display using Line API.

    Stores turns as TurnData (blocks + pre-rendered strips).
    render_line(y) maps virtual line y to the correct turn's strip.
    Only visible lines are rendered per frame.
    """

    DEFAULT_CSS = """
    ConversationView {
        color: $foreground;
        overflow-y: scroll;
        overflow-x: hidden;
        border: solid $accent;
        &:focus {
            background-tint: $foreground 5%;
        }
    }
    """

    def __init__(self, view_store=None):
        super().__init__()
        self._view_store = view_store
        self._turns: list[TurnData] = []
        self._total_lines: int = 0
        self._widest_line: int = 0
        self._line_cache: LRUCache = LRUCache(1024)
        self._block_strip_cache: LRUCache = LRUCache(
            4096
        )  # Block-level rendering cache
        self._cache_keys_by_turn: dict[
            int, set[tuple]
        ] = {}  # Track cache keys per turn
        self._last_filters: dict = {}
        self._last_width: int = 78
        self._last_search_ctx = None  # Store search context for lazy rerenders
        # Local fallback for tests that don't pass a view_store
        self._follow_state_fallback: FollowState = FollowState.ACTIVE
        self._pending_restore: dict | None = None
        self._scrolling_programmatically: bool = False
        self._scroll_anchor: ScrollAnchor | None = None
        self._indicator = cc_dump.tui.error_indicator.IndicatorState()
        # // [LAW:one-source-of-truth] All per-block view state lives here.
        self._view_overrides = cc_dump.tui.view_overrides.ViewOverrides()
        # Active streams keyed by canonical request_id.
        # // [LAW:one-source-of-truth] request_id is the only stream identity key.
        self._stream_turns: dict[str, TurnData] = {}
        self._stream_meta: dict[str, dict] = {}
        self._stream_order: list[str] = []
        self._focused_stream_id: str | None = None
        self._attached_stream_id: str | None = None

    # // [LAW:one-source-of-truth] Follow state stored as string in view store.
    # String comparison is stable across hot-reloads (enum class identity changes).
    # Falls back to local attribute when no store (tests).
    @property
    def _follow_state(self) -> FollowState:
        if self._view_store is not None:
            return FollowState(self._view_store.get("nav:follow"))
        return self._follow_state_fallback

    @_follow_state.setter
    def _follow_state(self, value: FollowState):
        if self._view_store is not None:
            self._view_store.set("nav:follow", value.value)
        else:
            self._follow_state_fallback = value

    @contextmanager
    def _programmatic_scroll(self):
        """Guard scroll operations from anchor recomputation."""
        self._scrolling_programmatically = True
        try:
            yield
        finally:
            self._scrolling_programmatically = False

    @property
    def _is_following(self) -> bool:
        """Whether auto-scroll is active (ACTIVE state only)."""
        return self._follow_state == FollowState.ACTIVE

    @property
    def view_overrides(self):
        """Public accessor for ViewOverrides — used by search_controller and action_handlers."""
        return self._view_overrides

    def render_line(self, y: int) -> Strip:
        """Line API: render a single line at virtual position y."""
        scroll_x, scroll_y = self.scroll_offset
        actual_y = scroll_y + y
        width = self._content_width
        try:
            selection = self.text_selection
        except NoScreen:
            selection = None

        try:
            if actual_y >= self._total_lines:
                return Strip.blank(width, self.rich_style)

            key = (actual_y, scroll_x, width, self._widest_line)
            # Bypass cache when selection is active (selection is transient)
            if selection is None and key in self._line_cache:
                strip = self._line_cache[key].apply_style(self.rich_style)
                # Apply overlay AFTER cache (viewport-relative, must not be cached)
                return cc_dump.tui.error_indicator.composite_overlay(
                    strip, y, width, self._indicator
                )

            # Binary search for the turn containing this line
            turn = self._find_turn_for_line(actual_y)
            if turn is None:
                return Strip.blank(width, self.rich_style)

            # Lazy re-render: if this turn was deferred during a filter toggle,
            # re-render it now that it's scrolled into view.
            if turn._pending_filter_snapshot is not None:
                self._lazy_rerender_turn(turn)

            local_y = actual_y - turn.line_offset
            if local_y < len(turn.strips):
                strip = turn.strips[local_y].crop_extend(
                    scroll_x, scroll_x + width, self.rich_style
                )
            else:
                strip = Strip.blank(width, self.rich_style)

            # Apply selection highlight
            if selection is not None:
                span = selection.get_span(actual_y)
                if span is not None:
                    strip = self._apply_selection_to_strip(strip, span)

            # Apply base style
            strip = strip.apply_style(self.rich_style)

            # Apply offsets for text selection coordinate mapping
            strip = strip.apply_offsets(scroll_x, actual_y)

            self._line_cache[key] = strip

            # Track which turn this cache key belongs to (for selective invalidation)
            turn_idx = turn.turn_index
            if turn_idx not in self._cache_keys_by_turn:
                self._cache_keys_by_turn[turn_idx] = set()
            self._cache_keys_by_turn[turn_idx].add(key)

            # Apply overlay AFTER cache (viewport-relative, must not be cached)
            strip = cc_dump.tui.error_indicator.composite_overlay(
                strip, y, width, self._indicator
            )
            return strip
        except Exception as exc:
            sys.stderr.write("[render] " + traceback.format_exc())
            sys.stderr.flush()
            # Show in error indicator overlay (deduplicate by exception type+message)
            err_key = f"render:{type(exc).__name__}"
            if not any(item.id == err_key for item in self._indicator.items):
                self._indicator.items.append(
                    cc_dump.tui.error_indicator.ErrorItem(
                        err_key, "\u26a0\ufe0f", f"{type(exc).__name__}: {exc}"
                    )
                )
            return Strip.blank(width, self.rich_style)

    def _apply_selection_to_strip(
        self, strip: Strip, span: tuple[int, int]
    ) -> Strip:
        """Apply selection highlight style to a character range within a strip.

        Uses Segment.divide() to split at selection boundaries, then applies
        the screen--selection style to the selected portion.
        """
        start, end = span
        segments = list(strip._segments)
        cell_length = strip.cell_length

        if end == -1:
            end = cell_length

        # No selection range on this strip
        if start >= end or start >= cell_length:
            return strip

        selection_style = self.screen.get_component_rich_style(
            "screen--selection"
        )

        # Divide segments at selection boundaries
        cuts = [start, end, cell_length]
        parts = list(Segment.divide(segments, cuts))

        # parts[0] = before selection, parts[1] = selected, parts[2] = after
        result_segments: list[Segment] = []
        if len(parts) > 0:
            result_segments.extend(parts[0])
        if len(parts) > 1:
            for seg in parts[1]:
                text, style, control = seg
                result_segments.append(
                    Segment(text, style + selection_style if style else selection_style, control)
                )
        if len(parts) > 2:
            result_segments.extend(parts[2])

        return Strip(result_segments, cell_length)

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        """Extract plain text from the selection range, stripping gutters."""
        # [LAW:one-source-of-truth] Gutter sizing from rendering module
        left = cc_dump.tui.rendering.GUTTER_WIDTH
        has_right = self.size.width >= cc_dump.tui.rendering.MIN_WIDTH_FOR_RIGHT_GUTTER
        right = cc_dump.tui.rendering.RIGHT_GUTTER_WIDTH if has_right else 0

        # Build clean text: strip left gutter and right gutter from each line
        lines = []
        for turn in self._turns:
            for strip in turn.strips:
                raw = strip.text
                content = raw[left:len(raw) - right] if right else raw[left:]
                lines.append(content.rstrip())

        # Adjust selection x-coordinates to account for removed left gutter
        start = selection.start
        end = selection.end
        if start is not None:
            start = Offset(max(0, start.x - left), start.y)
        if end is not None:
            end = Offset(max(0, end.x - left), end.y)
        adjusted = Selection(start, end)

        text = "\n".join(lines)
        return adjusted.extract(text), "\n"

    def selection_updated(self, selection: Selection | None) -> None:
        """Invalidate cache when selection changes."""
        self._line_cache.clear()
        self.refresh()

    def _find_turn_for_line(self, line_y: int) -> TurnData | None:
        """Binary search for turn containing virtual line y."""
        turns = self._turns
        if not turns:
            return None
        lo, hi = 0, len(turns) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            turn = turns[mid]
            if line_y < turn.line_offset:
                hi = mid - 1
            elif line_y >= turn.line_offset + turn.line_count:
                lo = mid + 1
            else:
                return turn
        return None

    def _viewport_turn_range(self, buffer_lines: int = 200) -> tuple[int, int]:
        """Return (start_idx, end_idx) of turns visible in viewport + buffer.

        Returns inclusive start, exclusive end indices into self._turns.
        Buffer extends the range above and below the viewport by buffer_lines
        to avoid popping when scrolling.
        """
        if not self._turns:
            return (0, 0)

        scroll_y = int(self.scroll_offset.y)
        viewport_height = self.scrollable_content_region.height

        # Expand range by buffer
        range_start = max(0, scroll_y - buffer_lines)
        range_end = scroll_y + viewport_height + buffer_lines

        # Find first turn via binary search
        start_turn = self._find_turn_for_line(range_start)
        if start_turn is None:
            # range_start is before all turns or no turns visible
            start_idx = 0
        else:
            start_idx = start_turn.turn_index

        # Find last turn via binary search
        end_turn = self._find_turn_for_line(min(range_end, self._total_lines - 1))
        if end_turn is None:
            end_idx = len(self._turns)
        else:
            end_idx = end_turn.turn_index + 1  # exclusive

        return (start_idx, end_idx)

    def _lazy_rerender_turn(self, turn: TurnData):
        """Lazily re-render a turn that was deferred during a filter toggle.

        Called from render_line() when a turn with _pending_filter_snapshot
        scrolls into view. Re-renders the turn with the pending filters,
        then schedules offset recalculation for after the current render pass.
        """
        width = self._content_width if self._size_known else self._last_width
        console = self.app.console

        # Apply the pending filters
        filters = dict(self._last_filters)
        turn.re_render(
            filters,
            console,
            width,
            block_cache=self._block_strip_cache,
            search_ctx=self._last_search_ctx,  # Pass stored search context
            overrides=self._view_overrides,
        )
        # re_render clears _pending_filter_snapshot

        # Schedule offset recalculation after current render pass completes.
        # We can't recalculate inline because it invalidates the line cache
        # and virtual_size while render_line() is still iterating.
        self.call_later(self._deferred_offset_recalc, turn.turn_index)

    def _deferred_offset_recalc(self, from_turn_index: int):
        """Recalculate offsets after a lazy re-render, then refresh display.

        Resolves stored block-level anchor to prevent viewport drift
        when off-viewport turns lazily re-render and shift line offsets.
        """
        self._recalculate_offsets_from(from_turn_index)
        if not self._is_following:
            self._resolve_anchor()
        self.refresh()

    def _recalculate_offsets(self):
        """Rebuild line offsets and virtual size."""
        self._recalculate_offsets_from(0)

    def _recalculate_offsets_from(self, start_idx: int):
        """Rebuild line offsets and virtual size from start_idx onwards.

        For start_idx > 0, reuses offset from previous turn.
        Widest line is always recomputed from all turns (O(n) with cached _widest_strip).
        """
        turns = self._turns
        if start_idx > 0 and start_idx < len(turns):
            prev = turns[start_idx - 1]
            offset = prev.line_offset + prev.line_count
        else:
            offset = 0
            start_idx = 0

        for i in range(start_idx, len(turns)):
            turns[i].line_offset = offset
            offset += turns[i].line_count

        # Widest: O(n) integer comparisons with cached _widest_strip
        widest = 0
        for turn in turns:
            if turn._widest_strip > widest:
                widest = turn._widest_strip

        self._total_lines = offset
        self._widest_line = max(widest, self._last_width)
        self.virtual_size = Size(self._widest_line, self._total_lines)
        self._line_cache.clear()
        self._cache_keys_by_turn.clear()  # Clear tracking when cache is cleared

    def add_turn(self, blocks: list, filters: dict = None):
        """Add a completed turn from block list."""
        if filters is None:
            filters = self._last_filters
        width = self._content_width if self._size_known else self._last_width
        console = self.app.console

        strips, block_strip_map, flat_blocks = cc_dump.tui.rendering.render_turn_to_strips(
            blocks, filters, console, width, block_cache=self._block_strip_cache,
            overrides=self._view_overrides,
        )
        td = TurnData(
            turn_index=len(self._turns),
            blocks=blocks,
            strips=strips,
            block_strip_map=block_strip_map,
            _flat_blocks=flat_blocks,
        )
        td._widest_strip = _compute_widest(strips)
        td.compute_relevant_keys()

        # Use ALWAYS_VISIBLE default to match filters dict structure
        td._last_filter_snapshot = {
            k: filters.get(k, cc_dump.formatting.ALWAYS_VISIBLE) for k in td.relevant_filter_keys
        }
        self._append_completed_turn(td)

        if self._is_following:
            with self._programmatic_scroll():
                self.scroll_end(animate=False, immediate=False, x_axis=False)

    def _append_completed_turn(self, td: TurnData) -> None:
        """Append completed turn while preserving focused streaming preview at end."""
        attached: TurnData | None = None
        if self._attached_stream_id and self._turns and self._turns[-1].is_streaming:
            attached = self._turns.pop()
            self._attached_stream_id = None

        td.turn_index = len(self._turns)
        self._turns.append(td)

        if attached is not None and self._focused_stream_id and self._focused_stream_id in self._stream_turns:
            attached.turn_index = len(self._turns)
            self._turns.append(attached)
            self._attached_stream_id = self._focused_stream_id

        self._recalculate_offsets()

    def _attach_focused_stream(self) -> None:
        """Ensure focused active stream preview is attached as the last turn."""
        focused = self._focused_stream_id
        if not focused or focused not in self._stream_turns:
            self._detach_stream_preview()
            return

        if self._attached_stream_id == focused and self._turns and self._turns[-1].is_streaming:
            return

        self._detach_stream_preview()
        td = self._stream_turns[focused]
        td.turn_index = len(self._turns)
        self._turns.append(td)
        self._attached_stream_id = focused
        self._recalculate_offsets()

    def _detach_stream_preview(self) -> None:
        """Remove attached streaming preview turn from completed turn list."""
        if self._attached_stream_id is None:
            return
        if self._turns and self._turns[-1].is_streaming:
            self._turns.pop()
        self._attached_stream_id = None
        self._recalculate_offsets()

    # ─── Request-scoped streaming ────────────────────────────────────────────

    def begin_stream(self, request_id: str, stream_meta: dict | None = None) -> None:
        """Create an active stream bucket for request_id.

        // [LAW:one-source-of-truth] request_id is canonical stream identity.
        """
        if request_id in self._stream_turns:
            if stream_meta:
                self._stream_meta[request_id] = dict(stream_meta)
            return

        td = TurnData(
            turn_index=-1,
            blocks=[],
            strips=[],
            is_streaming=True,
        )
        self._stream_turns[request_id] = td
        self._stream_meta[request_id] = dict(stream_meta or {})
        self._stream_order.append(request_id)

        if self._focused_stream_id is None:
            self._focused_stream_id = request_id
        self._attach_focused_stream()

    def _refresh_streaming_delta(self, td: TurnData):
        """Re-render delta buffer with lightweight streaming preview.

        Uses render_streaming_preview() — Markdown + gutter only, bypassing
        the full rendering pipeline (visibility, dispatch, truncation, caching).
        Finalization re-renders through the full pipeline.
        """
        if not td._text_delta_buffer:
            td.strips = td.strips[: td._stable_strip_count]
            td._widest_strip = _compute_widest(td.strips)
            return

        width = self._content_width if self._size_known else self._last_width
        console = self.app.console

        combined_text = "".join(td._text_delta_buffer)
        delta_strips = cc_dump.tui.rendering.render_streaming_preview(
            combined_text, console, width
        )

        td.strips = td.strips[: td._stable_strip_count] + delta_strips
        td._widest_strip = _compute_widest(td.strips)

    def _update_streaming_size(self, td: TurnData):
        """Update total_lines and virtual_size for streaming turn.

        Delegates to _recalculate_offsets() to avoid code duplication.
        """
        self._recalculate_offsets()

    def append_stream_block(self, request_id: str, block, filters: dict | None = None) -> None:
        """Append a block to the request-scoped streaming turn."""
        if filters is None:
            filters = self._last_filters

        if request_id not in self._stream_turns:
            self.begin_stream(request_id)
        td = self._stream_turns[request_id]

        # Add block to blocks list (always store)
        td.blocks.append(block)

        # // [LAW:dataflow-not-control-flow] Block declares streaming behavior via property
        if block.show_during_streaming:
            # Buffer deltas for all streams; only focused stream renders live preview.
            td._text_delta_buffer.append(block.content)
        is_focused = request_id == self._focused_stream_id
        if block.show_during_streaming and is_focused:
            self._attach_focused_stream()
            # TextDeltaBlock: progressive display for the focused stream.
            self._refresh_streaming_delta(td)
            # Update virtual size and auto-scroll
            self._update_streaming_size(td)
            if self._is_following:
                with self._programmatic_scroll():
                    self.scroll_end(animate=False, immediate=False, x_axis=False)
        # Other blocks: stored only, rendered at finalization.

    def finalize_stream(self, request_id: str) -> list:
        """Finalize a request-scoped streaming turn.

        Consolidates TextDeltaBlocks → TextContentBlocks, wraps content in
        MessageBlock container, full re-render from final blocks, marks turn
        as non-streaming.

        Returns the final block list.
        """
        td = self._stream_turns.get(request_id)
        if td is None:
            return []

        was_focused = request_id == self._focused_stream_id
        if was_focused:
            self._detach_stream_preview()

        consolidated: list[cc_dump.formatting.FormattedBlock] = []
        delta_buffer = []

        for block in td.blocks:
            if type(block).__name__ == "TextDeltaBlock":
                delta_buffer.append(block.content)
            else:
                # Flush accumulated deltas as a single TextContentBlock with ASSISTANT category
                if delta_buffer:
                    combined_text = "".join(delta_buffer)
                    consolidated.append(
                        cc_dump.formatting.TextContentBlock(content=combined_text, category=cc_dump.formatting.Category.ASSISTANT)
                    )
                    delta_buffer.clear()
                # Add the non-delta block
                consolidated.append(block)

        # Flush any remaining deltas
        if delta_buffer:
            combined_text = "".join(delta_buffer)
            consolidated.append(
                cc_dump.formatting.TextContentBlock(content=combined_text, category=cc_dump.formatting.Category.ASSISTANT)
            )

        # // [LAW:one-source-of-truth] Wrap content in MessageBlock, matching request-side structure.
        # Metadata blocks (StreamInfoBlock, StopReasonBlock) stay outside the container.
        _metadata_types = {"StreamInfoBlock", "StopReasonBlock"}
        content_children = [b for b in consolidated if type(b).__name__ not in _metadata_types]
        metadata = [b for b in consolidated if type(b).__name__ in _metadata_types]
        consolidated = metadata[:1] + [cc_dump.formatting.MessageBlock(
            role="assistant",
            msg_index=0,
            children=content_children,
            category=cc_dump.formatting.Category.ASSISTANT,
        )] + metadata[1:]

        # Eagerly populate content_regions for all text blocks (recursive tree walk)
        # // [LAW:single-enforcer] Uses module-level import for hot-reload safety
        def _walk_populate(block_list):
            for block in block_list:
                cc_dump.formatting.populate_content_regions(block)
                _walk_populate(getattr(block, "children", []))
        _walk_populate(consolidated)

        # Full re-render from consolidated blocks
        width = self._content_width if self._size_known else self._last_width
        console = self.app.console
        strips, block_strip_map, flat_blocks = cc_dump.tui.rendering.render_turn_to_strips(
            consolidated,
            self._last_filters,
            console,
            width,
            block_cache=self._block_strip_cache,
            overrides=self._view_overrides,
        )

        # Update turn data
        td.blocks = consolidated
        td.strips = strips
        td.block_strip_map = block_strip_map
        td._flat_blocks = flat_blocks
        td._widest_strip = _compute_widest(td.strips)
        td.is_streaming = False
        td._text_delta_buffer.clear()
        td._stable_strip_count = 0

        # Compute relevant filter keys
        td.compute_relevant_keys()
        td._last_filter_snapshot = {
            k: self._last_filters.get(k, cc_dump.formatting.ALWAYS_VISIBLE) for k in td.relevant_filter_keys
        }

        # Remove from active stream registries.
        self._stream_turns.pop(request_id, None)
        self._stream_meta.pop(request_id, None)
        self._stream_order = [rid for rid in self._stream_order if rid != request_id]

        # Append as a completed turn while preserving active preview at end.
        self._append_completed_turn(td)

        if was_focused:
            self._focused_stream_id = self._stream_order[0] if self._stream_order else None
            self._attach_focused_stream()

        if self._is_following:
            with self._programmatic_scroll():
                self.scroll_end(animate=False, immediate=False, x_axis=False)
        return consolidated

    def get_focused_stream_id(self) -> str | None:
        return self._focused_stream_id

    def set_focused_stream(self, request_id: str) -> bool:
        """Focus an active stream for live rendering preview."""
        if request_id not in self._stream_turns:
            return False
        self._focused_stream_id = request_id
        focused = self._stream_turns[request_id]
        # Rebuild delta preview from buffered text for the newly-focused stream.
        self._refresh_streaming_delta(focused)
        self._attach_focused_stream()
        if self._is_following:
            with self._programmatic_scroll():
                self.scroll_end(animate=False, immediate=False, x_axis=False)
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

    # Backward-compat wrappers for existing call sites/tests.
    def begin_streaming_turn(self):
        self.begin_stream("__default__", {"agent_label": "main", "agent_kind": "main"})

    def append_streaming_block(self, block, filters: dict = None):
        self.append_stream_block("__default__", block, filters)

    def finalize_streaming_turn(self) -> list:
        return self.finalize_stream("__default__")

    # ─────────────────────────────────────────────────────────────────────────

    def rerender(self, filters: dict, search_ctx=None, force: bool = False):
        """Re-render affected turns in place. Preserves scroll position.

        Uses stored block-level anchor (set on user scroll) to maintain
        stable scroll position across vis_state changes.

        Args:
            filters: Current filter state (category name -> Level)
            search_ctx: Optional SearchContext for highlighting matches
            force: Force re-render even if filter snapshot hasn't changed
                   (e.g. theme change rebuilds gutter colors).
        """
        self._last_filters = filters
        self._last_search_ctx = search_ctx  # Store for lazy rerenders

        if self._pending_restore is not None:
            self._rebuild_from_state(filters)
            return

        width = self._content_width if self._size_known else self._last_width
        console = self.app.console

        # Viewport-only re-rendering: only process visible turns + buffer
        vp_start, vp_end = self._viewport_turn_range()

        # Force re-render when search is active or caller requests it (theme change)
        force = force or search_ctx is not None

        first_changed = None
        for idx, td in enumerate(self._turns):
            # Skip streaming turns during filter changes
            if td.is_streaming:
                continue

            if vp_start <= idx < vp_end:
                # Viewport turn: re-render immediately
                if td.re_render(
                    filters,
                    console,
                    width,
                    force=force,
                    block_cache=self._block_strip_cache,
                    search_ctx=search_ctx,
                    overrides=self._view_overrides,
                ):
                    if first_changed is None:
                        first_changed = idx
            else:
                # Off-viewport turn: defer re-render, mark pending
                # Use ALWAYS_VISIBLE default to match filters dict structure
                snapshot = {
                    k: filters.get(k, cc_dump.formatting.ALWAYS_VISIBLE) for k in td.relevant_filter_keys
                }
                if force or snapshot != td._last_filter_snapshot:
                    td._pending_filter_snapshot = snapshot

        if first_changed is not None:
            self._recalculate_offsets_from(first_changed)

        # Resolve stored block-level anchor to restore scroll position
        if not self._is_following:
            self._resolve_anchor()

    def ensure_turn_rendered(self, turn_index: int):
        """Force-render a specific turn, then recalculate offsets.

        Used before scroll_to_block() to ensure the target turn has accurate
        block_strip_map and line_offset after _force_vis changes or deferred renders.
        """
        if turn_index >= len(self._turns):
            return
        td = self._turns[turn_index]
        width = self._content_width if self._size_known else self._last_width
        td.re_render(
            self._last_filters, self.app.console, width,
            force=True, block_cache=self._block_strip_cache,
            search_ctx=self._last_search_ctx,
            overrides=self._view_overrides,
        )
        self._recalculate_offsets_from(turn_index)

    @property
    def _content_width(self) -> int:
        """Render width for content, with margin to prevent horizontal scrollbar."""
        return max(1, self.scrollable_content_region.width - 1)

    @property
    def _size_known(self) -> bool:
        return self.size.width > 0

    def on_resize(self, event):
        """Re-render all strips at new width."""
        width = self._content_width
        if width != self._last_width and width > 0:
            self._last_width = width
            console = self.app.console
            for td in self._turns:
                # Skip re-rendering streaming turns on resize
                if td.is_streaming:
                    continue
                td.strips, td.block_strip_map, td._flat_blocks = (
                    cc_dump.tui.rendering.render_turn_to_strips(
                        td.blocks,
                        self._last_filters,
                        console,
                        width,
                        block_cache=self._block_strip_cache,
                        overrides=self._view_overrides,
                    )
                )
                td._widest_strip = _compute_widest(td.strips)
            self._recalculate_offsets()

    # ─── Sprint 2: Follow mode ───────────────────────────────────────────────

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        """Detect scroll position changes from ALL sources.

        CRITICAL: Must call super() to preserve scrollbar sync and refresh.
        CRITICAL: Signature is (old_value, new_value), not (value).

        // [LAW:dataflow-not-control-flow] Transition via _FOLLOW_TRANSITIONS table.
        """
        super().watch_scroll_y(old_value, new_value)
        if self._scrolling_programmatically:
            return
        # Compute anchor on user scroll (block-level anchor for vis_state changes)
        self._scroll_anchor = self._compute_anchor_from_scroll()
        self._follow_state = _FOLLOW_TRANSITIONS[
            (self._follow_state, self.is_vertical_scroll_end)
        ]

    def toggle_follow(self):
        """Toggle follow mode.

        // [LAW:dataflow-not-control-flow] Transition via _FOLLOW_TOGGLE table.
        """
        self._follow_state = _FOLLOW_TOGGLE[self._follow_state]
        if self._is_following:
            with self._programmatic_scroll():
                self.scroll_end(animate=False)

    def scroll_to_bottom(self):
        """Scroll to bottom. Transitions ENGAGED→ACTIVE; OFF stays OFF.

        // [LAW:dataflow-not-control-flow] Transition via _FOLLOW_SCROLL_BOTTOM table.
        """
        self._follow_state = _FOLLOW_SCROLL_BOTTOM[self._follow_state]
        with self._programmatic_scroll():
            self.scroll_end(animate=False)

    def scroll_to_block(self, turn_index: int, block_index: int) -> None:
        """Scroll to center a specific block in the viewport."""
        if turn_index >= len(self._turns):
            return
        td = self._turns[turn_index]
        strip_offset = td.strip_offset_for_block(block_index)
        if strip_offset is None:
            # Block filtered out — scroll to turn start instead
            target_y = td.line_offset
        else:
            target_y = td.line_offset + strip_offset

        # Center in viewport
        viewport_height = self.scrollable_content_region.height
        centered_y = max(0, target_y - viewport_height // 2)

        # // [LAW:dataflow-not-control-flow] Deactivate via table lookup.
        self._follow_state = _FOLLOW_DEACTIVATE[self._follow_state]
        with self._programmatic_scroll():
            self.scroll_to(y=centered_y, animate=False)

    def _block_index_at_line(self, turn: TurnData, content_y: int) -> int | None:
        """Find the block index within a turn for a given content line.

        Uses block_strip_map to determine which block owns the line.
        Returns None if no block maps to this line.
        """
        local_y = content_y - turn.line_offset
        best_block_idx = None
        best_strip_start = -1
        for block_idx, strip_start in turn.block_strip_map.items():
            if strip_start <= local_y and strip_start > best_strip_start:
                best_block_idx = block_idx
                best_strip_start = strip_start
        return best_block_idx

    def _is_expandable_block(self, block) -> bool:
        """Check if a block is expandable (from ViewOverrides, set by render_turn_to_strips)."""
        # // [LAW:one-source-of-truth] Expandable state from overrides only
        bvs = self._view_overrides._blocks.get(block.block_id)
        return bvs.expandable if bvs is not None else False

    def _block_strip_count(self, turn: TurnData, block_index: int) -> int:
        """Return the number of strips occupied by a block.

        Computes distance to next block start or turn end.
        """
        block_start = turn.block_strip_map.get(block_index)
        if block_start is None:
            return 0

        # Find next block start
        next_start = len(turn.strips)  # default to turn end
        for idx, start in turn.block_strip_map.items():
            if start > block_start and start < next_start:
                next_start = start

        return next_start - block_start

    def _nearest_visible_block_offset(self, turn: TurnData, target_block_index: int) -> int:
        """Find nearest visible block to target_block_index, prefer earlier blocks.

        Returns strip offset (line within turn) of the nearest visible block.
        If no blocks visible, returns 0.
        """
        if not turn.block_strip_map:
            return 0

        # Find nearest earlier block
        best_idx = None
        best_offset = -1
        for idx, offset in turn.block_strip_map.items():
            if idx <= target_block_index and offset > best_offset:
                best_idx = idx
                best_offset = offset

        if best_idx is not None:
            return best_offset

        # No earlier block, use first visible block
        return min(turn.block_strip_map.values())

    def _compute_anchor_from_scroll(self) -> ScrollAnchor | None:
        """Compute block-level anchor from current scroll_y.

        Returns ScrollAnchor(turn_index, block_index, line_in_block).
        Returns None if no turns or scroll position invalid.
        """
        if not self._turns:
            return None

        scroll_y = int(self.scroll_offset.y)
        turn = self._find_turn_for_line(scroll_y)
        if turn is None:
            return None

        local_y = scroll_y - turn.line_offset

        # Find which block contains local_y
        block_idx = self._block_index_at_line(turn, scroll_y)
        if block_idx is None:
            # No block mapped to this line, anchor to turn start
            return ScrollAnchor(turn.turn_index, 0, 0)

        # Compute line offset within the block
        block_start = turn.block_strip_map[block_idx]
        line_in_block = local_y - block_start

        return ScrollAnchor(turn.turn_index, block_idx, line_in_block)

    def _resolve_anchor(self):
        """Resolve stored anchor to scroll_y after content changes.

        Scrolls to the position that matches the stored anchor.
        Uses _scrolling_programmatically guard to prevent anchor corruption.
        """
        if self._scroll_anchor is None:
            return

        anchor = self._scroll_anchor

        # Find anchor turn (or nearest visible)
        if anchor.turn_index >= len(self._turns):
            # Anchor turn no longer exists, scroll to last turn
            if self._turns:
                last_turn = self._turns[-1]
                if last_turn.line_count > 0:
                    with self._programmatic_scroll():
                        self.scroll_to(y=last_turn.line_offset, animate=False)
            return

        turn = self._turns[anchor.turn_index]

        # If turn is hidden (0 lines), find nearest visible turn
        if turn.line_count == 0:
            # Walk forward/backward to find nearest visible
            for delta in range(1, len(self._turns)):
                for idx in [anchor.turn_index + delta, anchor.turn_index - delta]:
                    if 0 <= idx < len(self._turns) and self._turns[idx].line_count > 0:
                        turn = self._turns[idx]
                        target_y = turn.line_offset
                        with self._programmatic_scroll():
                            self.scroll_to(y=target_y, animate=False)
                        return
            # No visible turns
            return

        # Find anchor block (or nearest visible)
        block_start = turn.block_strip_map.get(anchor.block_index)
        actual_block_idx = anchor.block_index

        if block_start is None:
            # Block is hidden, find nearest visible block
            block_start = self._nearest_visible_block_offset(turn, anchor.block_index)
            # Find which block this offset corresponds to
            for idx, offset in turn.block_strip_map.items():
                if offset == block_start:
                    actual_block_idx = idx
                    break

        # Compute block size and clamp line_in_block
        block_size = self._block_strip_count(turn, actual_block_idx)
        if block_size == 0:
            # Block has no strips, use block_start directly
            clamped_line = 0
        else:
            # When anchor block was hidden, clamp to end of nearest visible block
            if actual_block_idx != anchor.block_index:
                # Use last line of the found block
                clamped_line = block_size - 1
            else:
                # Use original anchor position, clamped to block size
                clamped_line = min(anchor.line_in_block, block_size - 1)

        target_y = turn.line_offset + block_start + clamped_line

        with self._programmatic_scroll():
            self.scroll_to(y=target_y, animate=False)

    def _resolve_click_target(self, event):
        """Pure coordinate/meta resolution for a click event.

        Returns (turn, block_idx, meta_type, meta_value) if the click hit
        a toggle target, or None if it missed.

        meta_type is META_TOGGLE_BLOCK or META_TOGGLE_REGION.
        meta_value is True for block toggles, or the region index for regions.
        """
        meta = event.style.meta
        content_y = int(event.y + self.scroll_offset.y)
        turn = self._find_turn_for_line(content_y)
        if turn is None:
            return None
        block_idx = self._block_index_at_line(turn, content_y)
        if block_idx is None or block_idx >= len(turn._flat_blocks):
            return None

        # Fast path: segment metadata
        # // [LAW:single-enforcer] Only rendering.py sets these meta keys
        if meta.get(cc_dump.tui.rendering.META_TOGGLE_BLOCK):
            return (turn, block_idx, cc_dump.tui.rendering.META_TOGGLE_BLOCK, True)
        if meta.get(cc_dump.tui.rendering.META_TOGGLE_REGION) is not None:
            return (turn, block_idx, cc_dump.tui.rendering.META_TOGGLE_REGION,
                    meta.get(cc_dump.tui.rendering.META_TOGGLE_REGION))

        # Coordinate fallback for gutter clicks on region tag lines
        block = turn._flat_blocks[block_idx]
        region_idx = self._region_tag_at_line(turn, block, block_idx, content_y)
        if region_idx is not None:
            return (turn, block_idx, cc_dump.tui.rendering.META_TOGGLE_REGION, region_idx)
        return None

    def text_select_all(self) -> None:
        """Override to select only the block at the last click position.

        Textual's Widget._on_click calls text_select_all() on double-click
        (chain==2), which normally selects ALL text. We narrow to the block
        under the cursor using the position stored from the most recent click.
        """
        content_y = getattr(self, "_last_click_content_y", None)
        if content_y is None:
            super().text_select_all()
            return

        turn = self._find_turn_for_line(content_y)
        if turn is None:
            super().text_select_all()
            return

        block_idx = self._block_index_at_line(turn, content_y)
        if block_idx is None:
            super().text_select_all()
            return

        block_start_in_turn = turn.block_strip_map.get(block_idx)
        if block_start_in_turn is None:
            super().text_select_all()
            return

        strip_count = self._block_strip_count(turn, block_idx)
        if strip_count == 0:
            super().text_select_all()
            return

        # Global line coordinates for this block
        start_y = turn.line_offset + block_start_in_turn
        end_y = start_y + strip_count - 1

        start = Offset(0, start_y)
        end = Offset(10000, end_y)  # Large x to cover full last line

        selection = Selection.from_offsets(start, end)
        self.screen.selections = {self: selection}

    def on_click(self, event) -> None:
        """Toggle expand on truncated blocks or content regions.

        Uses segment metadata (Style.from_meta) set during rendering to
        determine what was clicked, following the same pattern as Textual's
        Tree widget. Only arrow segments carry toggle metadata.

        Also stores click position for text_select_all() block selection.
        """
        # Store for text_select_all (called by Widget._on_click on double-click)
        self._last_click_content_y = int(event.y + self.scroll_offset.y)

        target = self._resolve_click_target(event)
        if target is None:
            return

        turn, block_idx, meta_type, meta_value = target

        if meta_type == cc_dump.tui.rendering.META_TOGGLE_BLOCK:
            if self._is_expandable_block(turn._flat_blocks[block_idx]):
                self._toggle_block_expand(turn, block_idx)
        elif meta_type == cc_dump.tui.rendering.META_TOGGLE_REGION:
            self._toggle_region(turn, block_idx, meta_value)

    # FUTURE: region navigation — scan all turns' blocks' content_regions
    # for matching tags to support "go to <tag>" navigation

    def _region_at_line(
        self, turn: TurnData, block, block_idx: int, content_y: int
    ) -> int | None:
        """Map click y → content region index using strip_range.

        Returns the region index if the click hit a region's strip range,
        or None if no region was hit.
        """
        if not block.content_regions:
            return None

        # Compute the click's local strip offset within this block
        block_start_strip = turn.block_strip_map.get(block_idx)
        if block_start_strip is None:
            return None

        local_y = content_y - turn.line_offset - block_start_strip

        # // [LAW:one-source-of-truth] strip_range from overrides only
        for region in block.content_regions:
            rvs = self._view_overrides._regions.get((block.block_id, region.index))
            strip_range = rvs.strip_range if rvs is not None else None
            if strip_range is not None:
                range_start, range_end = strip_range
                if range_start <= local_y < range_end:
                    return region.index

        return None

    def _region_tag_at_line(
        self, turn: TurnData, block, block_idx: int, content_y: int
    ) -> int | None:
        """Check if click is on a region tag line (first or last strip of region).

        Only matches start tag and end tag lines, not inner content.
        This is the coordinate-based complement to META_TOGGLE_REGION metadata.
        """
        if not block.content_regions:
            return None
        block_start_strip = turn.block_strip_map.get(block_idx)
        if block_start_strip is None:
            return None
        local_y = content_y - turn.line_offset - block_start_strip
        # // [LAW:one-source-of-truth] strip_range from overrides only
        for region in block.content_regions:
            rvs = self._view_overrides._regions.get((block.block_id, region.index))
            strip_range = rvs.strip_range if rvs is not None else None
            if strip_range is not None:
                range_start, range_end = strip_range
                if local_y == range_start or local_y == range_end - 1:
                    return region.index
        return None

    def _toggle_region(
        self, turn: TurnData, block_idx: int, region_idx: int
    ) -> None:
        """Toggle a content region's expanded state and re-render the turn.

        // [LAW:dataflow-not-control-flow] content_regions[i].expanded is the value;
        // None = default (expanded). False = collapsed.
        """
        block = turn._flat_blocks[block_idx]

        if region_idx >= len(block.content_regions):
            return

        region = block.content_regions[region_idx]
        # Only collapsible region kinds can be toggled
        if region.kind not in cc_dump.tui.rendering.COLLAPSIBLE_REGION_KINDS:
            return
        # Toggle: None/True → False, False → None (restore default)
        # // [LAW:one-source-of-truth] Region expanded state in overrides only
        rvs = self._view_overrides.get_region(block.block_id, region_idx)
        current_exp = rvs.expanded
        new_expanded = None if current_exp is False else False
        rvs.expanded = new_expanded

        # Re-render just this turn
        if not turn.is_streaming:
            width = self._content_width if self._size_known else self._last_width
            console = self.app.console
            turn.re_render(
                self._last_filters,
                console,
                width,
                force=True,
                block_cache=self._block_strip_cache,
                overrides=self._view_overrides,
            )
            self._recalculate_offsets()
            # Resolve anchor to maintain scroll position
            if not self._is_following:
                self._resolve_anchor()

    def _toggle_block_expand(self, turn: TurnData, block_idx: int):
        """Toggle expand state for a single block and re-render its turn."""
        block = turn._flat_blocks[block_idx]

        # [LAW:dataflow-not-control-flow] Coalesce None to default, then toggle
        cat = cc_dump.tui.rendering.get_category(block)
        vis = self._last_filters.get(cat.value, cc_dump.formatting.ALWAYS_VISIBLE) if cat else cc_dump.formatting.ALWAYS_VISIBLE

        # Coalesce: treat None as default — read from overrides only
        # / [LAW:one-source-of-truth] Expanded state from ViewOverrides only
        bvs = self._view_overrides.get_block(block.block_id)
        current = bvs.expanded if bvs.expanded is not None else vis.expanded

        # Toggle
        new_value = not current

        # Store override (None if matches default)
        override_value = None if new_value == vis.expanded else new_value
        # // [LAW:one-source-of-truth] View state in overrides only
        bvs.expanded = override_value

        # Re-render just this turn
        if not turn.is_streaming:
            width = self._content_width if self._size_known else self._last_width
            console = self.app.console
            turn.re_render(
                self._last_filters,
                console,
                width,
                force=True,
                block_cache=self._block_strip_cache,
                overrides=self._view_overrides,
            )
            self._recalculate_offsets()
            # Resolve anchor to maintain scroll position after expand/collapse
            if not self._is_following:
                self._resolve_anchor()

    # ─── Error indicator ────────────────────────────────────────────────────

    def update_error_items(self, items: list) -> None:
        """Set error indicator items. Called by app when stale files change."""
        self._indicator.items = items
        if not items:
            self._indicator.expanded = False
        self._line_cache.clear()
        self.refresh()

    def on_mouse_move(self, event) -> None:
        """Track hover for error indicator expansion."""
        content_offset = event.get_content_offset(self)
        hit = (
            content_offset is not None
            and cc_dump.tui.error_indicator.hit_test_event(
                self._indicator, content_offset.x, content_offset.y, self._content_width
            )
        )
        if hit != self._indicator.expanded:
            self._indicator.expanded = hit
            self._line_cache.clear()
            self.refresh()

    # ─── State management ────────────────────────────────────────────────────

    def get_state(self) -> dict:
        """Extract state for hot-reload preservation.

        Preserves completed turns plus active request-scoped streams.
        """
        all_blocks = [td.blocks for td in self._turns if not td.is_streaming]
        active_streams = {
            rid: {
                "blocks": td.blocks,
                "text_delta_buffer": list(td._text_delta_buffer),
                "stable_strip_count": td._stable_strip_count,
                "meta": dict(self._stream_meta.get(rid, {})),
            }
            for rid, td in self._stream_turns.items()
        }

        # Serialize scroll anchor for position preservation across hot-reload
        anchor = self._scroll_anchor
        anchor_dict = (
            {"turn_index": anchor.turn_index, "block_index": anchor.block_index, "line_in_block": anchor.line_in_block}
            if anchor is not None
            else None
        )

        return {
            "all_blocks": all_blocks,
            "follow_state": self._follow_state.value,
            "turn_count": len(self._turns),
            "streaming_states": [],  # backward-compatible key (legacy singleton stream path)
            "active_streams": active_streams,
            "stream_order": list(self._stream_order),
            "focused_stream_id": self._focused_stream_id,
            "scroll_anchor": anchor_dict,
            "view_overrides": self._view_overrides.to_dict(),
        }

    def restore_state(self, state: dict):
        """Restore state from a previous instance.

        Restores streaming turn state and re-renders from preserved blocks.
        """
        self._pending_restore = state
        # Support both new follow_state (str) and old follow_mode (bool) for backward compat
        follow_raw = state.get("follow_state")
        if follow_raw is not None:
            self._follow_state = FollowState(follow_raw)
        else:
            # Backward compat: old bool format
            self._follow_state = FollowState.ACTIVE if state.get("follow_mode", True) else FollowState.OFF

        # Restore view overrides
        vo_data = state.get("view_overrides", {})
        self._view_overrides = cc_dump.tui.view_overrides.ViewOverrides.from_dict(vo_data)

        # Restore streaming states after _rebuild_from_state is called
        streaming_states = state.get("streaming_states", [])
        if streaming_states:
            # Store for application after rebuild
            self._pending_streaming_states = streaming_states

    def _rebuild_from_state(self, filters: dict):
        """Rebuild from restored state."""
        state = self._pending_restore
        self._pending_restore = None
        self._turns.clear()
        self._stream_turns.clear()
        self._stream_meta.clear()
        self._stream_order.clear()
        self._focused_stream_id = None
        self._attached_stream_id = None

        all_blocks = state.get("all_blocks", [])
        for block_list in all_blocks:
            self.add_turn(block_list, filters)

        # Restore request-scoped active streams.
        active_streams = state.get("active_streams", {})
        if isinstance(active_streams, dict):
            width = self._content_width if self._size_known else self._last_width
            console = self.app.console
            for request_id, payload in active_streams.items():
                if not isinstance(payload, dict):
                    continue
                blocks = payload.get("blocks", [])
                meta = payload.get("meta", {})
                self.begin_stream(str(request_id), meta if isinstance(meta, dict) else None)
                td = self._stream_turns[str(request_id)]
                td.blocks = blocks if isinstance(blocks, list) else []
                td._text_delta_buffer = list(payload.get("text_delta_buffer", []))
                td._stable_strip_count = int(payload.get("stable_strip_count", 0))
                # Rebuild baseline strips for completeness; focused stream preview
                # is refreshed below.
                strips, block_strip_map, flat_blocks = cc_dump.tui.rendering.render_turn_to_strips(
                    td.blocks,
                    filters,
                    console,
                    width,
                    block_cache=self._block_strip_cache,
                    overrides=self._view_overrides,
                )
                td.strips = strips
                td.block_strip_map = block_strip_map
                td._flat_blocks = flat_blocks
                td._widest_strip = _compute_widest(td.strips)

            order = state.get("stream_order", [])
            if isinstance(order, list):
                self._stream_order = [rid for rid in order if rid in self._stream_turns]
            if not self._stream_order:
                self._stream_order = list(self._stream_turns.keys())
            focused = state.get("focused_stream_id")
            if isinstance(focused, str) and focused in self._stream_turns:
                self._focused_stream_id = focused
            elif self._stream_order:
                self._focused_stream_id = self._stream_order[0]
            if self._focused_stream_id:
                self._refresh_streaming_delta(self._stream_turns[self._focused_stream_id])
                self._attach_focused_stream()

        self._recalculate_offsets()

        # Restore scroll anchor and resolve position (when not following)
        anchor_dict = state.get("scroll_anchor")
        if anchor_dict is not None:
            self._scroll_anchor = ScrollAnchor(
                turn_index=anchor_dict["turn_index"],
                block_index=anchor_dict["block_index"],
                line_in_block=anchor_dict["line_in_block"],
            )
            if not self._is_following:
                self._resolve_anchor()


class StatsPanel(Static):
    """Live statistics display showing request counts, tokens, and models.

    Queries database as single source of truth for token counts.
    Only tracks request_count and models_seen in memory (not in DB).
    """

    def __init__(self):
        super().__init__("")
        self.request_count = 0
        self.models_seen: set = set()

    def update_stats(self, **kwargs):
        """Update statistics and refresh display.

        Only updates in-memory fields (requests, models).
        Token counts come from analytics store via refresh_from_store().
        """
        if "requests" in kwargs:
            self.request_count = kwargs["requests"]
        if "model" in kwargs and kwargs["model"]:
            self.models_seen.add(kwargs["model"])

        # No longer accumulating token counts here - they come from analytics store

    def refresh_from_store(self, store, current_turn: dict = None):
        """Refresh token counts from analytics store.

        Args:
            store: AnalyticsStore instance
            current_turn: Optional dict with in-progress turn data to merge for real-time display
                         Expected keys: input_tokens, output_tokens, cache_read_tokens,
                         cache_creation_tokens, model
        """
        if store is None:
            # No store - show only in-memory fields with defaults
            self._refresh_display(
                turn_count=self.request_count,
                context_total=0,
                context_window=200_000,
                cache_pct=0.0,
                output_total=0,
                cost_estimate=0.0,
                model_str="unknown",
            )
            return

        # Query session cumulative stats
        session_stats = store.get_session_stats(current_turn)

        # Query latest turn stats (for context window usage)
        latest_turn = store.get_latest_turn_stats()

        # If we have a current_turn (streaming), merge it for latest turn values
        if current_turn:
            # During streaming, current_turn represents the latest (incomplete) turn
            latest_input = current_turn.get("input_tokens", 0)
            latest_cache_read = current_turn.get("cache_read_tokens", 0)
            latest_cache_creation = current_turn.get("cache_creation_tokens", 0)
            latest_model = current_turn.get("model", "unknown")
        elif latest_turn:
            # Use completed latest turn from store
            latest_input = latest_turn["input_tokens"]
            latest_cache_read = latest_turn["cache_read_tokens"]
            latest_cache_creation = latest_turn["cache_creation_tokens"]
            latest_model = latest_turn["model"] or "unknown"
        else:
            # No turns yet
            latest_input = 0
            latest_cache_read = 0
            latest_cache_creation = 0
            latest_model = "unknown"

        # Compute derived values
        context_total = latest_input + latest_cache_read + latest_cache_creation
        context_window = cc_dump.analysis.get_context_window(latest_model)

        # Cache hit percentage for latest turn
        total_input_latest = latest_input + latest_cache_read
        cache_pct = (100.0 * latest_cache_read / total_input_latest) if total_input_latest > 0 else 0.0

        # Cumulative output across session
        output_total = session_stats["output_tokens"]

        # Cost estimate using session cumulative stats
        # For cost, we need a representative model - use latest turn's model
        cost_estimate = cc_dump.analysis.compute_session_cost(
            session_stats["input_tokens"],
            session_stats["output_tokens"],
            session_stats["cache_read_tokens"],
            session_stats["cache_creation_tokens"],
            latest_model,
        )

        # Model display name
        model_display = cc_dump.analysis.format_model_ultra_short(latest_model)

        self._refresh_display(
            turn_count=self.request_count,
            context_total=context_total,
            context_window=context_window,
            cache_pct=cache_pct,
            output_total=output_total,
            cost_estimate=cost_estimate,
            model_str=model_display,
        )

    def _refresh_display(
        self,
        turn_count: int,
        context_total: int,
        context_window: int,
        cache_pct: float,
        output_total: int,
        cost_estimate: float,
        model_str: str,
    ):
        """Rebuild the display text."""
        rich_text = cc_dump.tui.panel_renderers.render_stats_panel(
            turn_count,
            context_total,
            context_window,
            cache_pct,
            output_total,
            cost_estimate,
            model_str,
        )
        self.update(rich_text)

    def cycle_mode(self):
        """No-op — StatsPanel has no sub-modes."""

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {
            "request_count": self.request_count,
            "models_seen": set(self.models_seen),
        }

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self.request_count = state.get("request_count", 0)
        self.models_seen = state.get("models_seen", set())
        # Note: Display refresh will happen when refresh_from_store() is called
        # after the widget is mounted in the app. Don't call _refresh_display()
        # here as it requires an app context for Rich Text rendering.


class ToolEconomicsPanel(Static):
    """Panel showing per-tool token usage aggregates.

    Queries analytics store as single source of truth.
    Supports two view modes:
    - Aggregate (default): one row per tool (all models combined)
    - Breakdown (Ctrl+M): separate rows per (tool, model) combination
    """

    def __init__(self):
        super().__init__("")
        self._breakdown_mode = False  # Default to aggregate view
        self._store = None

    def refresh_from_store(self, store):
        """Refresh panel data from analytics store.

        Args:
            store: AnalyticsStore instance
        """
        # Store for use in toggle_breakdown
        self._store = store

        if store is None:
            self._refresh_display([])
            return

        # Query tool economics with real tokens and cache attribution
        rows = store.get_tool_economics(group_by_model=self._breakdown_mode)
        self._refresh_display(rows)

    def toggle_breakdown(self):
        """Toggle between aggregate and breakdown view modes."""
        self._breakdown_mode = not self._breakdown_mode
        # Re-query with new mode
        if self._store is not None:
            self.refresh_from_store(self._store)

    def cycle_mode(self):
        """Cycle intra-panel mode — delegates to toggle_breakdown."""
        self.toggle_breakdown()

    def _refresh_display(self, rows):
        """Rebuild the economics table."""
        text = cc_dump.tui.panel_renderers.render_economics_panel(rows)
        self.update(text)

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {
            "breakdown_mode": self._breakdown_mode,
        }

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self._breakdown_mode = state.get("breakdown_mode", False)
        self._refresh_display([])


class TimelinePanel(Static):
    """Panel showing per-turn context growth over time.

    Queries analytics store as single source of truth.
    """

    def __init__(self):
        super().__init__("")

    def refresh_from_store(self, store):
        """Refresh panel data from analytics store.

        Args:
            store: AnalyticsStore instance
        """
        if store is None:
            self._refresh_display([])
            return

        # Query turn timeline from store
        turn_data = store.get_turn_timeline()

        # Reconstruct TurnBudget objects from store data
        budgets = []
        for row in turn_data:
            # Parse request JSON to compute budget estimates
            request_json = row["request_json"]
            request_body = json.loads(request_json) if request_json else {}

            budget = cc_dump.analysis.compute_turn_budget(request_body)

            # Fill in actual token counts from store
            budget.actual_input_tokens = row["input_tokens"]
            budget.actual_cache_read_tokens = row["cache_read_tokens"]
            budget.actual_cache_creation_tokens = row["cache_creation_tokens"]
            budget.actual_output_tokens = row["output_tokens"]

            budgets.append(budget)

        self._refresh_display(budgets)

    def _refresh_display(self, budgets: list[cc_dump.analysis.TurnBudget]):
        """Rebuild the timeline table."""
        text = cc_dump.tui.panel_renderers.render_timeline_panel(budgets)
        self.update(text)

    def cycle_mode(self):
        """No-op — TimelinePanel has no sub-modes."""

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {}  # No state to preserve - queries DB on demand

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self._refresh_display([])


class LogsPanel(RichLog):
    """Panel showing cc-dump application logs (debug, errors, internal messages)."""

    def __init__(self):
        super().__init__(highlight=False, markup=False, wrap=True, max_lines=1000)

    # [LAW:dataflow-not-control-flow] Log level style dispatch
    def _get_log_level_styles(self):
        p = cc_dump.palette.PALETTE
        return {
            "ERROR": f"bold {p.error}",
            "WARNING": f"bold {p.warning}",
            "INFO": f"bold {p.info}",
            "DEBUG": "dim",
        }

    def app_log(self, level: str, message: str):
        """Add an application log entry.

        Args:
            level: Log level (DEBUG, INFO, WARNING, ERROR)
            message: Log message
        """
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

        log_text = Text()
        log_text.append(f"[{timestamp}] ", style="dim")

        # Color-code by level using palette
        styles = self._get_log_level_styles()
        style = styles.get(level, "dim")
        log_text.append(f"{level:7s} ", style=style)

        log_text.append(message)
        self.write(log_text)

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {}  # Logs don't need to be preserved across hot-reload

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        pass  # Nothing to restore


# Factory functions for creating widgets
def create_conversation_view(view_store=None) -> ConversationView:
    """Create a new ConversationView instance."""
    return ConversationView(view_store=view_store)


def create_stats_panel() -> StatsPanel:
    """Create a new StatsPanel instance."""
    return StatsPanel()


def create_economics_panel() -> ToolEconomicsPanel:
    """Create a new ToolEconomicsPanel instance."""
    return ToolEconomicsPanel()


def create_timeline_panel() -> TimelinePanel:
    """Create a new TimelinePanel instance."""
    return TimelinePanel()


def create_logs_panel() -> LogsPanel:
    """Create a new LogsPanel instance."""
    return LogsPanel()
