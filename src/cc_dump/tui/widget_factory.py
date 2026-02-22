"""Widget factory - creates widget instances that can be hot-swapped.

This module is RELOADABLE. When it reloads, the app can create new widget
instances from the updated class definitions and swap them in.
"""

import datetime
import hashlib
import json
import os
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
from rich.style import Style
from rich.text import Text

# Use module-level imports for hot-reload
import cc_dump.formatting
import cc_dump.palette
import cc_dump.analysis
import cc_dump.tui.rendering
import cc_dump.tui.panel_renderers
import cc_dump.tui.error_indicator
import cc_dump.tui.view_overrides
import cc_dump.domain_store


# ─── Follow mode state machine ──────────────────────────────────────────────


class FollowState(Enum):
    OFF = "off"
    ENGAGED = "engaged"
    ACTIVE = "active"


class StreamViewMode(Enum):
    FOCUSED = "focused"
    LANES = "lanes"


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


def _hash_strips(strips: list[Strip]) -> str:
    """Compute stable content hash for rendered strips."""
    digest = hashlib.blake2b(digest_size=16)
    for strip in strips:
        for seg in strip:
            digest.update(seg.text.encode("utf-8", errors="replace"))
            digest.update(b"\x1f")
            digest.update(str(seg.style).encode("utf-8", errors="replace"))
            digest.update(b"\x1e")
        digest.update(b"\x00")
    return digest.hexdigest()


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
    _stream_last_delta_version: int = -1  # last rendered delta version
    _stream_last_render_width: int = 0  # width used for last preview render
    _strip_hash: str = ""  # hash of rendered strips for no-op rerender detection
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
        strips, block_strip_map, flat_blocks = cc_dump.tui.rendering.render_turn_to_strips(
            self.blocks,
            filters,
            console,
            width,
            block_cache=block_cache,
            search_ctx=search_ctx,
            turn_index=self.turn_index,
            overrides=overrides,
        )
        strip_hash = _hash_strips(strips)
        if strip_hash == self._strip_hash:
            return False

        self.strips = strips
        self.block_strip_map = block_strip_map
        self._flat_blocks = flat_blocks
        self._strip_hash = strip_hash
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

    def __init__(self, view_store=None, domain_store=None):
        super().__init__()
        self._view_store = view_store
        # Auto-create domain store for tests that don't provide one
        self._domain_store = domain_store if domain_store is not None else cc_dump.domain_store.DomainStore()
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
        self._line_cache_index_write_count: int = 0
        self._line_cache_index_prune_interval: int = 256
        self._last_filters: dict = {}
        self._last_width: int = 78
        self._last_search_ctx = None  # Store search context for lazy rerenders
        # Local fallback for tests that don't pass a view_store
        self._follow_state_fallback: FollowState = FollowState.ACTIVE
        self._stream_view_mode_fallback: StreamViewMode = StreamViewMode.FOCUSED
        self._pending_restore: dict | None = None
        self._scrolling_programmatically: bool = False
        self._scroll_anchor: ScrollAnchor | None = None
        self._indicator = cc_dump.tui.error_indicator.IndicatorState()
        # // [LAW:one-source-of-truth] All per-block view state lives here.
        self._view_overrides = cc_dump.tui.view_overrides.ViewOverrides()
        # Streaming preview rendering state (rendering concern).
        # Block lists and delta buffers live in DomainStore.
        self._stream_preview_turns: dict[str, TurnData] = {}
        self._attached_stream_id: str | None = None
        self._multi_stream_preview_id = "__multi_stream_preview__"
        self._pending_stream_delta_request_ids: set[str] = set()
        self._stream_delta_flush_scheduled: bool = False
        self._background_rerender_scheduled: bool = False
        self._background_rerender_chunk_size: int = 8

        # Wire domain store callbacks
        self._wire_domain_store(self._domain_store)

    def _wire_domain_store(self, ds) -> None:
        """Register rendering callbacks on domain store."""
        ds.on_turn_added = self._on_turn_added
        ds.on_stream_started = self._on_stream_started
        ds.on_stream_block = self._on_stream_block
        ds.on_stream_finalized = self._on_stream_finalized
        ds.on_focus_changed = self._on_focus_changed
        ds.on_turns_pruned = self._on_turns_pruned

    def on_mount(self) -> None:
        """Hydrate local render cache from domain store on mount.

        // [LAW:one-source-of-truth] DomainStore remains canonical; widget cache is derived.
        """
        self._hydrate_from_domain_store()

    def _hydrate_from_domain_store(self) -> None:
        """Rebuild rendered turns from current domain store state."""
        if not self.is_attached:
            return
        if self._view_store is not None:
            self._last_filters = self._view_store.active_filters.get()
        self._turns = []
        self._stream_preview_turns = {}
        self._attached_stream_id = None
        self._pending_stream_delta_request_ids = set()
        self._clear_line_cache()

        for blocks in self._domain_store.iter_completed_blocks():
            self._render_and_append_turn(blocks, self._last_filters)

        self._attach_stream_preview()
        self._recalculate_offsets()
        self.refresh()

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

    @property
    def _stream_view_mode(self) -> StreamViewMode:
        if self._view_store is not None:
            raw = self._view_store.get("streams:view")
            try:
                return StreamViewMode(raw)
            except ValueError:
                return StreamViewMode.FOCUSED
        return self._stream_view_mode_fallback

    @_stream_view_mode.setter
    def _stream_view_mode(self, value: StreamViewMode):
        if self._view_store is not None:
            self._view_store.set("streams:view", value.value)
        else:
            self._stream_view_mode_fallback = value

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

            # Binary search for the turn containing this line
            turn = self._find_turn_for_line(actual_y)
            if turn is None:
                return Strip.blank(width, self.rich_style)

            # Lazy re-render: if this turn was deferred during a filter toggle,
            # re-render it now that it's scrolled into view.
            if turn._pending_filter_snapshot is not None:
                self._lazy_rerender_turn(turn)

            local_y = actual_y - turn.line_offset
            key = (
                turn.turn_index,
                turn.line_offset,
                local_y,
                scroll_x,
                width,
                self._widest_line,
            )
            # Bypass cache when selection is active (selection is transient)
            if selection is None and key in self._line_cache:
                strip = self._line_cache[key].apply_style(self.rich_style)
                # Apply overlay AFTER cache (viewport-relative, must not be cached)
                return cc_dump.tui.error_indicator.composite_overlay(
                    strip, y, width, self._indicator
                )

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
            self._line_cache_index_write_count += 1
            if self._line_cache_index_write_count >= self._line_cache_index_prune_interval:
                self._line_cache_index_write_count = 0
                self._prune_line_cache_index()

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
        self._clear_line_cache()
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

    def _schedule_background_rerender(self) -> None:
        """Schedule incremental off-viewport rerender work."""
        if self._background_rerender_scheduled:
            return
        self._background_rerender_scheduled = True
        self.call_later(self._background_rerender)

    def _background_rerender(self) -> None:
        """Incrementally rerender deferred turns in background.

        Processes a bounded number of turns per tick to keep UI responsive.
        """
        self._background_rerender_scheduled = False
        width = self._content_width if self._size_known else self._last_width
        console = self.app.console

        first_changed: int | None = None
        processed = 0
        for idx, td in enumerate(self._turns):
            if td.is_streaming or td._pending_filter_snapshot is None:
                continue
            if td.re_render(
                self._last_filters,
                console,
                width,
                block_cache=self._block_strip_cache,
                search_ctx=self._last_search_ctx,
                overrides=self._view_overrides,
            ):
                if first_changed is None:
                    first_changed = idx
            processed += 1
            if processed >= self._background_rerender_chunk_size:
                break

        if first_changed is not None:
            self._recalculate_offsets_from(first_changed)
            if not self._is_following:
                self._resolve_anchor()
            self.refresh()

        if any(
            (not td.is_streaming and td._pending_filter_snapshot is not None)
            for td in self._turns
        ):
            self._schedule_background_rerender()

    # ─── Unified render invalidation ─────────────────────────────────────────

    # // [LAW:single-enforcer] _invalidate is the single entry point for all render invalidation.
    # // [LAW:dataflow-not-control-flow] Dispatch table drives behavior, not branches.
    _INVALIDATION_DISPATCH = {
        "new_turn":          "_render_new_turn",
        "stream_started":    "_render_stream_started",
        "stream_delta":      "_render_stream_delta",
        "stream_finalized":  "_render_stream_finalized",
        "focus_changed":     "_render_focus_changed",
        "stream_mode_changed": "_render_stream_mode_changed",
        "filters_changed":   "_rerender_affected",
        "block_toggled":     "_render_single_turn",
        "region_toggled":    "_render_single_turn",
        "search":            "_rerender_affected",
        "resize":            "_render_all_turns",
        "restore":           "_render_restore",
    }

    def _invalidate(self, reason: str, **kwargs) -> None:
        """Single entry point for all render invalidation.

        // [LAW:single-enforcer] All render triggers go through here.
        Dispatches to reason-specific render method, then runs uniform post-render.
        """
        method_name = self._INVALIDATION_DISPATCH.get(reason)
        if method_name is None:
            return
        method = getattr(self, method_name)
        method(**kwargs)
        self._post_render(reason)

    # // [LAW:dataflow-not-control-flow] Post-render behavior varies by data (reason), not control flow.
    _FOLLOW_REASONS = frozenset({
        "new_turn", "stream_delta", "stream_finalized", "focus_changed", "stream_mode_changed",
    })
    _ANCHOR_REASONS = frozenset({
        "filters_changed", "block_toggled", "region_toggled", "search",
    })

    def _post_render(self, reason: str) -> None:
        """Uniform post-render: offsets, follow-scroll or anchor resolve."""
        if reason in self._FOLLOW_REASONS:
            if self._is_following:
                with self._programmatic_scroll():
                    self.scroll_end(animate=False, immediate=False, x_axis=False)
        elif reason in self._ANCHOR_REASONS:
            if not self._is_following:
                self._resolve_anchor()

    def _clear_line_cache(self) -> None:
        """Clear line cache and its turn-key index together."""
        # // [LAW:single-enforcer] Cache + index invalidation is centralized here.
        self._line_cache.clear()
        self._cache_keys_by_turn.clear()
        self._line_cache_index_write_count = 0

    def _prune_line_cache_index(self) -> None:
        """Drop stale index keys that no longer exist in LRU line cache."""
        live_keys = set(self._line_cache.keys())
        stale_turns: list[int] = []
        for turn_idx, keys in self._cache_keys_by_turn.items():
            keys.intersection_update(live_keys)
            if not keys:
                stale_turns.append(turn_idx)
        for turn_idx in stale_turns:
            self._cache_keys_by_turn.pop(turn_idx, None)

    def _invalidate_cache_for_turns(self, start_idx: int, end_idx: int | None = None) -> None:
        """Drop line-cache entries for turns in [start_idx, end_idx).

        // [LAW:single-enforcer] Range invalidation for line cache happens only here.
        """
        if start_idx <= 0:
            self._clear_line_cache()
            return

        upper = len(self._turns) if end_idx is None else min(end_idx, len(self._turns))
        if upper <= start_idx:
            return

        for turn_idx in range(start_idx, upper):
            keys = self._cache_keys_by_turn.pop(turn_idx, None)
            if not keys:
                continue
            for key in keys:
                self._line_cache.discard(key)

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
        self._invalidate_cache_for_turns(start_idx, len(turns))

    def _on_turn_added(self, blocks: list, index: int) -> None:
        """Domain store callback: a completed turn was added."""
        if not self.is_attached:
            return
        self._invalidate("new_turn", blocks=blocks)

    def _on_turns_pruned(self, pruned_count: int) -> None:
        """Domain store callback: oldest completed turns were pruned."""
        if not self.is_attached:
            return
        if pruned_count <= 0:
            return
        if pruned_count >= len(self._turns):
            self._turns.clear()
            self._scroll_anchor = None
            self._clear_line_cache()
            self._recalculate_offsets()
            if self.is_attached:
                self.refresh()
            return

        del self._turns[:pruned_count]
        for idx, td in enumerate(self._turns):
            td.turn_index = idx

        if self._scroll_anchor is not None:
            new_turn_index = self._scroll_anchor.turn_index - pruned_count
            if new_turn_index < 0:
                new_turn_index = 0
            self._scroll_anchor = ScrollAnchor(
                turn_index=new_turn_index,
                block_index=self._scroll_anchor.block_index,
                line_in_block=self._scroll_anchor.line_in_block,
            )

        self._clear_line_cache()
        self._recalculate_offsets()
        if not self._is_following and self.is_attached:
            self._resolve_anchor()
        if self.is_attached:
            self.refresh()

    def _render_new_turn(self, blocks: list, filters: dict = None) -> None:
        """Render blocks to TurnData and append as completed turn.

        // [LAW:single-enforcer] Called via _invalidate("new_turn").
        Post-render (follow-scroll) handled by _post_render.
        """
        self._render_and_append_turn(blocks, filters)

    def _render_and_append_turn(self, blocks: list, filters: dict = None) -> None:
        """Render blocks to TurnData and append as completed turn."""
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
        td._strip_hash = _hash_strips(strips)
        td._widest_strip = _compute_widest(strips)
        td.compute_relevant_keys()

        # Use ALWAYS_VISIBLE default to match filters dict structure
        td._last_filter_snapshot = {
            k: filters.get(k, cc_dump.formatting.ALWAYS_VISIBLE) for k in td.relevant_filter_keys
        }
        self._append_completed_turn(td)

    def add_turn(self, blocks: list, filters: dict = None):
        """Add a completed turn from block list.

        Delegates to domain_store.add_turn() which fires _on_turn_added callback.
        """
        self._domain_store.add_turn(blocks)

    def _append_completed_turn(self, td: TurnData) -> None:
        """Append completed turn while preserving live stream preview at end."""
        had_preview_attached = bool(
            self._attached_stream_id and self._turns and self._turns[-1].is_streaming
        )
        if had_preview_attached:
            self._turns.pop()
            self._attached_stream_id = None

        td.turn_index = len(self._turns)
        self._turns.append(td)

        if had_preview_attached:
            self._attach_stream_preview()

        self._recalculate_offsets_from(td.turn_index)

    def _attach_focused_stream_preview(self) -> None:
        """Ensure focused active stream preview is attached as the last turn."""
        focused = self._domain_store.get_focused_stream_id()
        if not focused or focused not in self._stream_preview_turns:
            self._detach_stream_preview()
            return

        if self._attached_stream_id == focused and self._turns and self._turns[-1].is_streaming:
            return

        self._detach_stream_preview()
        td = self._stream_preview_turns[focused]
        td.turn_index = len(self._turns)
        self._turns.append(td)
        self._attached_stream_id = focused
        self._recalculate_offsets()

    def _refresh_multi_stream_preview(self) -> TurnData | None:
        """Build side-by-side strips for active streaming lanes."""
        request_ids = self._domain_store.get_active_stream_ids()
        if not request_ids:
            return None

        td = self._stream_preview_turns.get(self._multi_stream_preview_id)
        if td is None:
            td = TurnData(
                turn_index=-1,
                blocks=[],
                strips=[],
                is_streaming=True,
            )
            self._stream_preview_turns[self._multi_stream_preview_id] = td

        width = self._content_width if self._size_known else self._last_width
        active = request_ids[:3]
        lane_count = max(1, len(active))
        separator_width = lane_count - 1
        lane_width = max(24, (width - separator_width) // lane_count)
        composed_width = lane_width * lane_count + separator_width

        chips = dict((rid, (label, kind)) for rid, label, kind in self._domain_store.get_active_stream_chips())
        label_styles = {
            "main": Style(color=cc_dump.palette.PALETTE.accent, bold=True),
            "subagent": Style(color=cc_dump.palette.PALETTE.info, bold=True),
            "unknown": Style(color=cc_dump.palette.PALETTE.warning, dim=True),
        }
        separator = Segment("│", Style(dim=True))

        lane_rows: list[list[Strip]] = []
        for request_id in active:
            lane_td = self._stream_preview_turns.get(request_id)
            if lane_td is None:
                lane_td = TurnData(turn_index=-1, blocks=[], strips=[], is_streaming=True)
                self._stream_preview_turns[request_id] = lane_td
            self._refresh_streaming_delta(request_id, lane_td, force=True, width=lane_width)
            label, kind = chips.get(request_id, (request_id[:8], "unknown"))
            header_style = label_styles.get(kind, label_styles["unknown"])
            header_text = Text(f" {label} ".ljust(lane_width), style=header_style)
            header_strip = Strip([Segment(str(header_text), header_style)]).adjust_cell_length(lane_width)
            lane_rows.append([header_strip, *lane_td.strips])

        row_count = max(len(rows) for rows in lane_rows)
        blank_lane = Strip.blank(lane_width, self.rich_style)
        composed: list[Strip] = []
        for row_idx in range(row_count):
            row_segments: list[Segment] = []
            for lane_idx, rows in enumerate(lane_rows):
                lane_strip = rows[row_idx] if row_idx < len(rows) else blank_lane
                lane_strip = lane_strip.crop_extend(0, lane_width, self.rich_style)
                row_segments.extend(lane_strip._segments)
                if lane_idx < lane_count - 1:
                    row_segments.append(separator)
            composed.append(Strip(row_segments).adjust_cell_length(composed_width))

        td.strips = composed
        td._strip_hash = _hash_strips(composed)
        td._widest_strip = _compute_widest(composed)
        return td

    def _attach_multi_stream_preview(self) -> None:
        """Attach side-by-side multi-lane streaming preview."""
        td = self._refresh_multi_stream_preview()
        if td is None:
            self._detach_stream_preview()
            return
        if (
            self._attached_stream_id == self._multi_stream_preview_id
            and self._turns
            and self._turns[-1].is_streaming
        ):
            self._turns[-1] = td
            self._recalculate_offsets()
            return
        self._detach_stream_preview()
        td.turn_index = len(self._turns)
        self._turns.append(td)
        self._attached_stream_id = self._multi_stream_preview_id
        self._recalculate_offsets()

    def _attach_stream_preview(self) -> None:
        """Attach the active streaming preview for the selected view mode."""
        if self._stream_view_mode == StreamViewMode.LANES:
            self._attach_multi_stream_preview()
            return
        self._attach_focused_stream_preview()

    def _detach_stream_preview(self) -> None:
        """Remove attached streaming preview turn from completed turn list."""
        if self._attached_stream_id is None:
            return
        if self._turns and self._turns[-1].is_streaming:
            self._turns.pop()
        self._attached_stream_id = None
        self._recalculate_offsets()

    # ─── Domain store callbacks (rendering side) ─────────────────────────────

    def _on_stream_started(self, request_id: str, meta: dict) -> None:
        """Domain store callback: a new stream was created."""
        if not self.is_attached:
            return
        self._invalidate("stream_started", request_id=request_id, meta=meta)

    def _render_stream_started(self, request_id: str, meta: dict = None) -> None:
        """Create streaming preview TurnData for a new stream."""
        if request_id in self._stream_preview_turns:
            return

        td = TurnData(
            turn_index=-1,
            blocks=[],
            strips=[],
            is_streaming=True,
        )
        self._stream_preview_turns[request_id] = td
        self._attach_stream_preview()

    def _refresh_streaming_delta(
        self,
        request_id: str,
        td: TurnData,
        *,
        force: bool = False,
        width: int | None = None,
    ) -> bool:
        """Re-render delta buffer with lightweight streaming preview.

        Uses render_streaming_preview() — Markdown + gutter only, bypassing
        the full rendering pipeline (visibility, dispatch, truncation, caching).
        Finalization re-renders through the full pipeline.
        """
        width = (
            width
            if width is not None
            else (self._content_width if self._size_known else self._last_width)
        )
        delta_version = self._domain_store.get_delta_version(request_id)
        if (
            not force
            and delta_version == td._stream_last_delta_version
            and width == td._stream_last_render_width
        ):
            return False

        delta_text = self._domain_store.get_delta_preview_text(request_id)
        if not delta_text:
            td.strips = td.strips[: td._stable_strip_count]
            td._strip_hash = _hash_strips(td.strips)
            td._widest_strip = _compute_widest(td.strips)
            td._stream_last_delta_version = delta_version
            td._stream_last_render_width = width
            return True

        console = self.app.console
        delta_strips = cc_dump.tui.rendering.render_streaming_preview(
            delta_text, console, width
        )

        td.strips = td.strips[: td._stable_strip_count] + delta_strips
        td._strip_hash = _hash_strips(td.strips)
        td._widest_strip = _compute_widest(td.strips)
        td._stream_last_delta_version = delta_version
        td._stream_last_render_width = width
        return True

    def _queue_stream_delta(self, request_id: str) -> None:
        """Coalesce streaming delta paints to one invalidate per UI tick."""
        self._pending_stream_delta_request_ids.add(request_id)
        if self._stream_delta_flush_scheduled:
            return
        self._stream_delta_flush_scheduled = True
        self.call_later(self._flush_stream_delta_frame)

    def _flush_stream_delta_frame(self) -> None:
        """Flush coalesced stream delta invalidation for current stream mode."""
        self._stream_delta_flush_scheduled = False
        pending = self._pending_stream_delta_request_ids
        self._pending_stream_delta_request_ids = set()
        if not pending:
            return
        if self._stream_view_mode == StreamViewMode.LANES:
            ordered = tuple(
                request_id
                for request_id in self._domain_store.get_active_stream_ids()
                if request_id in pending
            )
            self._invalidate("stream_delta", request_ids=ordered)
            return
        focused_id = self._domain_store.get_focused_stream_id()
        if not focused_id or focused_id not in pending:
            return
        self._invalidate("stream_delta", request_id=focused_id)

    def _on_stream_block(self, request_id: str, block) -> None:
        """Domain store callback: a block was appended to a stream."""
        if not self.is_attached:
            return
        td = self._stream_preview_turns.get(request_id)
        if td is None:
            return

        # // [LAW:dataflow-not-control-flow] Block declares streaming behavior via property
        focused_id = self._domain_store.get_focused_stream_id()
        is_focused = request_id == focused_id
        should_render = (
            block.show_during_streaming
            and (
                is_focused
                or self._stream_view_mode == StreamViewMode.LANES
            )
        )
        if should_render:
            # // [LAW:dataflow-not-control-flow] Pending set holds variability; flush loop stays fixed.
            self._queue_stream_delta(request_id)

    def _render_stream_delta(self, request_id: str = "", request_ids: tuple[str, ...] = ()) -> None:
        """Re-render stream preview after new delta block."""
        if self._stream_view_mode == StreamViewMode.LANES:
            # // [LAW:dataflow-not-control-flow] Update fixed preview path using request_id data set.
            for rid in request_ids:
                td = self._stream_preview_turns.get(rid)
                if td is None:
                    continue
                self._refresh_streaming_delta(rid, td)
            self._attach_stream_preview()
            return

        td = self._stream_preview_turns.get(request_id)
        if td is None:
            return
        self._attach_stream_preview()
        if self._refresh_streaming_delta(request_id, td):
            self._recalculate_offsets()

    def _on_stream_finalized(self, request_id: str, final_blocks: list, was_focused: bool) -> None:
        """Domain store callback: a stream was finalized with consolidated blocks."""
        if not self.is_attached:
            return
        self._invalidate("stream_finalized", request_id=request_id, final_blocks=final_blocks, was_focused=was_focused)

    def _render_stream_finalized(self, request_id: str, final_blocks: list, was_focused: bool = False) -> None:
        """Finalize stream: full re-render from consolidated blocks."""
        td = self._stream_preview_turns.get(request_id)

        if was_focused:
            self._detach_stream_preview()

        # Full re-render from consolidated blocks
        width = self._content_width if self._size_known else self._last_width
        console = self.app.console
        strips, block_strip_map, flat_blocks = cc_dump.tui.rendering.render_turn_to_strips(
            final_blocks,
            self._last_filters,
            console,
            width,
            block_cache=self._block_strip_cache,
            overrides=self._view_overrides,
        )

        # Create or reuse TurnData for the finalized turn
        if td is None:
            td = TurnData(turn_index=-1, blocks=[], strips=[], is_streaming=False)
        td.blocks = final_blocks
        td.strips = strips
        td.block_strip_map = block_strip_map
        td._flat_blocks = flat_blocks
        td._strip_hash = _hash_strips(strips)
        td._widest_strip = _compute_widest(td.strips)
        td.is_streaming = False
        td._text_delta_buffer.clear()
        td._stable_strip_count = 0
        td._stream_last_delta_version = -1
        td._stream_last_render_width = 0

        # Compute relevant filter keys
        td.compute_relevant_keys()
        td._last_filter_snapshot = {
            k: self._last_filters.get(k, cc_dump.formatting.ALWAYS_VISIBLE) for k in td.relevant_filter_keys
        }

        # Remove from preview registry
        self._stream_preview_turns.pop(request_id, None)
        if not self._domain_store.get_active_stream_ids():
            self._stream_preview_turns.pop(self._multi_stream_preview_id, None)
        self._pending_stream_delta_request_ids.discard(request_id)

        # Append as a completed turn while preserving active preview at end.
        self._append_completed_turn(td)

        # Reattach if there's a new focused stream
        self._attach_stream_preview()

    def _on_focus_changed(self, request_id: str) -> None:
        """Domain store callback: focused stream changed."""
        if not self.is_attached:
            return
        self._invalidate("focus_changed", request_id=request_id)

    def _render_focus_changed(self, request_id: str) -> None:
        """Re-render after focus stream change."""
        self._pending_stream_delta_request_ids.discard(request_id)
        td = self._stream_preview_turns.get(request_id)
        if td is not None:
            self._refresh_streaming_delta(request_id, td, force=True)
        self._attach_stream_preview()

    def _render_stream_mode_changed(self, mode: str = "focused") -> None:
        """Re-render stream preview after focused/lanes mode change."""
        _ = mode
        for request_id in self._domain_store.get_active_stream_ids():
            td = self._stream_preview_turns.get(request_id)
            if td is None:
                continue
            self._refresh_streaming_delta(request_id, td, force=True)
        self._attach_stream_preview()

    # ─── Delegating accessors (read from domain_store) ─────────────────────

    def get_focused_stream_id(self) -> str | None:
        return self._domain_store.get_focused_stream_id()

    def set_focused_stream(self, request_id: str) -> bool:
        """Focus an active stream for live rendering preview."""
        return self._domain_store.set_focused_stream(request_id)

    def get_active_stream_chips(self) -> tuple[tuple[str, str, str], ...]:
        """Return active stream tuples for footer chips."""
        return self._domain_store.get_active_stream_chips()

    def get_stream_view_mode(self) -> str:
        return self._stream_view_mode.value

    def set_stream_view_mode(self, mode: str) -> bool:
        """Set live stream preview mode: focused or side-by-side lanes."""
        try:
            next_mode = StreamViewMode(mode)
        except ValueError:
            return False
        if self._stream_view_mode == next_mode:
            return True
        self._stream_view_mode = next_mode
        self._invalidate("stream_mode_changed", mode=next_mode.value)
        return True

    # Backward-compat wrappers for existing call sites/tests.
    def begin_stream(self, request_id: str, stream_meta: dict | None = None) -> None:
        """Delegate to domain_store."""
        self._domain_store.begin_stream(request_id, stream_meta)

    def append_stream_block(self, request_id: str, block, filters: dict | None = None) -> None:
        """Delegate to domain_store. filters param ignored (rendering reads _last_filters)."""
        self._domain_store.append_stream_block(request_id, block)

    def finalize_stream(self, request_id: str) -> list:
        """Delegate to domain_store."""
        return self._domain_store.finalize_stream(request_id)

    def begin_streaming_turn(self):
        self.begin_stream("__default__", {"agent_label": "main", "agent_kind": "main"})

    def append_streaming_block(self, block, filters: dict = None):
        self.append_stream_block("__default__", block, filters)

    def finalize_streaming_turn(self) -> list:
        return self.finalize_stream("__default__")

    # ─────────────────────────────────────────────────────────────────────────

    def rerender(self, filters: dict, search_ctx=None, force: bool = False):
        """Re-render affected turns in place. Preserves scroll position.

        // [LAW:single-enforcer] Delegates to _invalidate for actual rendering.

        Args:
            filters: Current filter state (category name -> Level)
            search_ctx: Optional SearchContext for highlighting matches
            force: Force re-render even if filter snapshot hasn't changed
                   (e.g. theme change rebuilds gutter colors).
        """
        self._last_filters = filters
        self._last_search_ctx = search_ctx  # Store for lazy rerenders

        if self._pending_restore is not None:
            self._invalidate("restore", filters=filters)
            return

        reason = "search" if search_ctx is not None else "filters_changed"
        self._invalidate(reason, filters=filters, search_ctx=search_ctx, force=force)

    def _rerender_affected(self, filters: dict = None, search_ctx=None, force: bool = False) -> None:
        """Re-render affected turns in place using viewport-only strategy.

        // [LAW:single-enforcer] Called via _invalidate("filters_changed") or _invalidate("search").
        Post-render (anchor resolve) handled by _post_render.
        """
        if filters is None:
            filters = self._last_filters

        width = self._content_width if self._size_known else self._last_width
        console = self.app.console

        # Viewport-only re-rendering: only process visible turns + buffer
        vp_start, vp_end = self._viewport_turn_range()

        # Force re-render when search is active or caller requests it (theme change)
        force = force or search_ctx is not None

        first_changed = None
        has_deferred = False
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
                    has_deferred = True

        if first_changed is not None:
            self._recalculate_offsets_from(first_changed)
        if has_deferred:
            self._schedule_background_rerender()

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
            self._invalidate("resize")

    def _render_all_turns(self) -> None:
        """Re-render all turns at current width. Used for resize."""
        width = self._last_width
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
            td._strip_hash = _hash_strips(td.strips)
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

        # // [LAW:single-enforcer] Re-render via _invalidate
        if not turn.is_streaming:
            self._invalidate("region_toggled", turn=turn)

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

        # // [LAW:single-enforcer] Re-render via _invalidate
        if not turn.is_streaming:
            self._invalidate("block_toggled", turn=turn)

    def _render_single_turn(self, turn: TurnData = None) -> None:
        """Re-render a single turn after toggle. Post-render via _post_render."""
        if turn is None:
            return
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
        self._recalculate_offsets_from(turn.turn_index)

    # ─── Error indicator ────────────────────────────────────────────────────

    def update_error_items(self, items: list) -> None:
        """Set error indicator items. Called by app when stale files change."""
        self._indicator.items = items
        if not items:
            self._indicator.expanded = False
        self._clear_line_cache()
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
            self._clear_line_cache()
            self.refresh()

    # ─── State management ────────────────────────────────────────────────────

    def get_state(self) -> dict:
        """Extract view state for hot-reload preservation.

        Domain data (block lists, streams) lives in DomainStore and persists
        across widget replacement. This only captures view/rendering state.
        """
        # Serialize scroll anchor for position preservation across hot-reload
        anchor = self._scroll_anchor
        anchor_dict = (
            {"turn_index": anchor.turn_index, "block_index": anchor.block_index, "line_in_block": anchor.line_in_block}
            if anchor is not None
            else None
        )

        return {
            "follow_state": self._follow_state.value,
            "stream_view_mode": self._stream_view_mode.value,
            "scroll_anchor": anchor_dict,
            "view_overrides": self._view_overrides.to_dict(),
        }

    def restore_state(self, state: dict):
        """Restore view state from a previous instance.

        Domain data (block lists, streams) lives in DomainStore and persists
        across widget replacement. This restores view/rendering state only.
        """
        self._pending_restore = state
        # Support both new follow_state (str) and old follow_mode (bool) for backward compat
        follow_raw = state.get("follow_state")
        if follow_raw is not None:
            self._follow_state = FollowState(follow_raw)
        else:
            # Backward compat: old bool format
            self._follow_state = FollowState.ACTIVE if state.get("follow_mode", True) else FollowState.OFF
        stream_mode_raw = state.get("stream_view_mode")
        if stream_mode_raw in {StreamViewMode.FOCUSED.value, StreamViewMode.LANES.value}:
            self._stream_view_mode = StreamViewMode(stream_mode_raw)

        # Restore view overrides
        vo_data = state.get("view_overrides", {})
        self._view_overrides = cc_dump.tui.view_overrides.ViewOverrides.from_dict(vo_data)

    def _render_restore(self, filters: dict = None) -> None:
        """Dispatch target for _invalidate("restore"). Delegates to _rebuild_from_state."""
        self._rebuild_from_state(filters or self._last_filters)

    def _rebuild_from_state(self, filters: dict):
        """Rebuild rendering from domain store data + restored view state."""
        state = self._pending_restore
        self._pending_restore = None
        self._turns.clear()
        self._stream_preview_turns.clear()
        self._attached_stream_id = None
        self._pending_stream_delta_request_ids.clear()
        self._stream_delta_flush_scheduled = False

        self._rebuild_from_domain_store(filters)

        # Restore scroll anchor and resolve position (when not following)
        if state is not None:
            anchor_dict = state.get("scroll_anchor")
            if anchor_dict is not None:
                self._scroll_anchor = ScrollAnchor(
                    turn_index=anchor_dict["turn_index"],
                    block_index=anchor_dict["block_index"],
                    line_in_block=anchor_dict["line_in_block"],
                )
                if not self._is_following:
                    self._resolve_anchor()

    def _rebuild_from_domain_store(self, filters: dict) -> None:
        """Re-render all turns from domain store data.

        Used after hot-reload widget replacement. Domain store persists
        across widget replacement, so we just re-render from its data.
        """
        # Re-render completed turns
        for block_list in self._domain_store.iter_completed_blocks():
            self._render_and_append_turn(block_list, filters)

        # Rebuild streaming preview turns
        ds = self._domain_store
        for request_id in ds._stream_order:
            if request_id not in ds._stream_turns:
                continue
            meta = ds._stream_meta.get(request_id, {})
            self._on_stream_started(request_id, meta)
            td = self._stream_preview_turns.get(request_id)
            if td is not None:
                # Rebuild delta preview from domain store's accumulated buffer
                self._refresh_streaming_delta(request_id, td, force=True)

        # Reattach focused stream preview
        self._attach_stream_preview()
        self._recalculate_offsets()


class StatsPanel(Static):
    """Unified analytics dashboard (summary/timeline/models).

    // [LAW:one-source-of-truth] All displayed metrics come from AnalyticsStore snapshot data.
    """

    _VIEW_ORDER = ("summary", "timeline", "models")

    def __init__(self):
        super().__init__("")
        self._view_index = 0
        self._last_snapshot: dict = {"summary": {}, "timeline": [], "models": []}
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

        # Request/model tracking is retained for compatibility with existing handlers/tests.

    def refresh_from_store(self, store, current_turn: dict = None, domain_store=None):
        """Refresh dashboard data from analytics store.

        Args:
            store: AnalyticsStore instance
            current_turn: Optional dict with in-progress turn data to merge for real-time display
                          Expected keys: input_tokens, output_tokens, cache_read_tokens,
                          cache_creation_tokens, model
        """
        if store is None:
            self._last_snapshot = {"summary": {}, "timeline": [], "models": []}
            self._refresh_display()
            return

        snapshot = store.get_dashboard_snapshot(current_turn=current_turn)
        summary = dict(snapshot.get("summary", {}))

        # // [LAW:one-source-of-truth] Lane attribution comes from DomainStore stamped blocks/meta.
        if domain_store is not None:
            completed_lane_counts = domain_store.get_completed_lane_counts()
            active_lane_counts = domain_store.get_active_lane_counts()
        else:
            completed_lane_counts = {"main": 0, "subagent": 0, "unknown": 0}
            active_lane_counts = {"main": 0, "subagent": 0, "unknown": 0}

        summary["main_turns"] = int(completed_lane_counts.get("main", 0))
        summary["subagent_turns"] = int(completed_lane_counts.get("subagent", 0))
        summary["unknown_turns"] = int(completed_lane_counts.get("unknown", 0))
        summary["active_main_streams"] = int(active_lane_counts.get("main", 0))
        summary["active_subagent_streams"] = int(active_lane_counts.get("subagent", 0))
        summary["active_unknown_streams"] = int(active_lane_counts.get("unknown", 0))

        # Optional local capacity baseline (not provided by API).
        capacity_raw = str(os.environ.get("CC_DUMP_TOKEN_CAPACITY", "") or "").strip()
        try:
            capacity_total = int(capacity_raw) if capacity_raw else 0
        except ValueError:
            capacity_total = 0
        if capacity_total > 0:
            used_tokens = int(summary.get("total_tokens", 0))
            remaining_tokens = max(0, capacity_total - used_tokens)
            used_pct = min(100.0, (used_tokens / capacity_total) * 100.0)
            summary["capacity_total"] = capacity_total
            summary["capacity_used"] = used_tokens
            summary["capacity_remaining"] = remaining_tokens
            summary["capacity_used_pct"] = used_pct

        snapshot["summary"] = summary
        self._last_snapshot = snapshot
        self._refresh_display()

    def _refresh_display(self):
        """Rebuild the display text."""
        # // [LAW:dataflow-not-control-flow] exception: Textual update() requires an attached app context.
        if not self.is_attached:
            return
        view_mode = self._VIEW_ORDER[self._view_index]
        text = cc_dump.tui.panel_renderers.render_analytics_panel(
            self._last_snapshot,
            view_mode,
        )
        # [LAW:single-enforcer] Normalize dashboard text to a styled Text object at one boundary.
        self.update(Text(text, style="default"))

    def cycle_mode(self):
        """Cycle dashboard view mode."""
        self._view_index = (self._view_index + 1) % len(self._VIEW_ORDER)
        self._refresh_display()

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {
            "request_count": self.request_count,
            "models_seen": set(self.models_seen),
            "view_index": self._view_index,
        }

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self.request_count = state.get("request_count", 0)
        self.models_seen = state.get("models_seen", set())
        self._view_index = int(state.get("view_index", 0)) % len(self._VIEW_ORDER)
        self._refresh_display()


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
def create_conversation_view(view_store=None, domain_store=None) -> ConversationView:
    """Create a new ConversationView instance."""
    return ConversationView(view_store=view_store, domain_store=domain_store)


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
