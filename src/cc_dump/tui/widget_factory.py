"""Widget factory - creates widget instances that can be hot-swapped.

This module is RELOADABLE. When it reloads, the app can create new widget
instances from the updated class definitions and swap them in.
"""

import datetime
import hashlib
import logging
from contextlib import contextmanager
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from snarfx import Observable, reaction
from snarfx import textual as stx
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
import cc_dump.core.formatting
import cc_dump.core.palette
import cc_dump.core.analysis
import cc_dump.tui.rendering
import cc_dump.tui.panel_renderers
import cc_dump.tui.error_indicator
import cc_dump.tui.view_overrides
import cc_dump.app.error_models
import cc_dump.app.domain_store
from cc_dump.tui.follow_mode import (
    FollowState,
    FollowEvent,
    FollowModeStore,
    FollowTransition,
)
from cc_dump.io.perf_logging import monitor_slow_path

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cc_dump.tui.rendering_impl import RenderRuntime


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
    _last_render_key: tuple | None = None  # width/search/theme/override revision tuple
    _pending_filter_snapshot: dict | None = (
        None  # deferred filters for lazy off-viewport re-render
    )
    _filter_revision: int = 0  # last filter revision this turn was validated against


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
        render_key: tuple | None = None,
        runtime: "RenderRuntime | None" = None,
    ) -> bool:
        """Re-render if a relevant filter changed. Returns True if strips changed.

        Args:
            force: Force re-render even if filter snapshot hasn't changed.
            block_cache: Optional LRUCache for caching rendered strips per block.
            search_ctx: Optional SearchContext for highlighting matches.
            overrides: Optional ViewOverrides for per-block view state.
            render_key: Optional revision tuple for width/search/theme/overrides.
        """
        # Create snapshot using ALWAYS_VISIBLE default to match filters dict structure
        snapshot = {k: filters.get(k, cc_dump.core.formatting.ALWAYS_VISIBLE) for k in self.relevant_filter_keys}
        snapshot_changed = snapshot != self._last_filter_snapshot
        render_key_changed = render_key is not None and render_key != self._last_render_key
        if not force and not snapshot_changed and not render_key_changed:
            self._pending_filter_snapshot = None
            return False

        self._last_filter_snapshot = snapshot
        if render_key is not None:
            self._last_render_key = render_key
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
            runtime=runtime,
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
    """Turn-level scroll anchor for stable viewport preservation across rerenders."""

    turn_index: int      # index into _turns
    line_in_turn: int    # top-of-viewport offset within rendered turn strips


@dataclass(frozen=True)
class SearchTurnsSnapshot:
    """Immutable snapshot of turns exposed to search consumers."""

    turns: tuple[TurnData, ...]


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

    def __init__(
        self,
        view_store=None,
        domain_store=None,
        runtime: "RenderRuntime | None" = None,
    ):
        super().__init__()
        self._view_store = view_store
        # Auto-create domain store for tests that don't provide one
        self._domain_store = domain_store if domain_store is not None else cc_dump.app.domain_store.DomainStore()
        self._render_runtime: "RenderRuntime | None" = runtime
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
        self._search_revision: int = 0
        self._theme_revision: int = 0
        self._overrides_revision: int = 0
        self._last_search_signature: tuple | None = None
        self._last_theme_generation: int = self._read_theme_generation()
        # [LAW:one-source-of-truth] Canonical follow state lives in FollowModeStore Observable.
        self._follow_store = FollowModeStore(self._initial_follow_state())
        self._pending_restore: dict | None = None
        self._scrolling_programmatically: bool = False
        self._scroll_anchor: ScrollAnchor | None = None
        self._indicator = cc_dump.tui.error_indicator.IndicatorState()
        self._indicator_state: Observable[tuple[list, bool]] = Observable(([], False))
        # [LAW:single-enforcer] One reactive projection owns indicator invalidation/refresh.
        self._indicator_reaction = reaction(
            lambda: self._indicator_state.get(),
            self._apply_indicator_state,
            fire_immediately=False,
        )
        # [LAW:single-enforcer] Follow transition side effects flow from one reactive projection.
        self._follow_transition_reaction = reaction(
            lambda: self._follow_store.transition.get(),
            self._apply_follow_transition,
            fire_immediately=False,
        )
        # [LAW:single-enforcer] One projection syncs follow state into view_store/persistence.
        self._follow_state_sync_reaction = reaction(
            lambda: self._follow_store.state.get(),
            self._persist_follow_state,
            fire_immediately=True,
        )
        # // [LAW:one-source-of-truth] All per-block view state lives here.
        self._view_overrides = cc_dump.tui.view_overrides.ViewOverrides()
        # Streaming preview rendering state (rendering concern).
        # Block lists and delta buffers live in DomainStore.
        self._stream_preview_turns: dict[str, TurnData] = {}
        self._attached_stream_id: str | None = None
        self._pending_stream_delta_request_ids: set[str] = set()
        self._stream_delta_flush_scheduled: bool = False
        self._background_rerender_scheduled: bool = False
        self._background_rerender_chunk_size: int = 8
        self._background_rerender_prefetch_turn_window: int = 128
        # // [LAW:dataflow-not-control-flow] Deferred turn work is an explicit data queue.
        self._background_rerender_generation: int = 0
        self._pending_rerender_indices: deque[int] = deque()
        self._active_filter_revision: int = 0
        self._deferred_offset_recalc_scheduled: bool = False
        self._deferred_offset_recalc_start_idx: int | None = None
        self._widest_strip_max: int = 0
        self._offset_recalc_incremental_count: int = 0
        self._offset_recalc_full_width_interval: int = 128

        # Wire domain store callbacks
        self._wire_domain_store(self._domain_store)

    def _read_theme_generation(self) -> int:
        if self._view_store is None:
            return 0
        raw = self._view_store.get("theme:generation")
        return int(raw) if isinstance(raw, int) else 0

    def _initial_follow_state(self) -> FollowState:
        follow_raw = self._view_store.get("nav:follow") if self._view_store is not None else FollowState.ACTIVE.value
        try:
            return FollowState(str(follow_raw))
        except ValueError:
            # [LAW:dataflow-not-control-flow] exception: guard malformed persisted state.
            return FollowState.ACTIVE

    @staticmethod
    def _search_match_signature(match) -> tuple | None:
        if match is None:
            return None
        return (
            match.turn_index,
            match.block_index,
            match.text_offset,
            match.text_length,
            id(match.block) if match.block is not None else None,
        )

    def _search_signature(self, search_ctx) -> tuple | None:
        if search_ctx is None:
            return None
        return (
            search_ctx.pattern.pattern,
            search_ctx.pattern.flags,
            len(search_ctx.all_matches),
            id(search_ctx.all_matches),
            self._search_match_signature(search_ctx.current_match),
        )

    def _update_render_revisions(self, search_ctx) -> None:
        theme_generation = self._read_theme_generation()
        if theme_generation != self._last_theme_generation:
            self._last_theme_generation = theme_generation
            self._theme_revision += 1

        search_signature = self._search_signature(search_ctx)
        if search_signature != self._last_search_signature:
            self._last_search_signature = search_signature
            self._search_revision += 1

    def _turn_render_key(self, width: int) -> tuple[int, int, int, int]:
        return (
            width,
            self._search_revision,
            self._theme_revision,
            self._overrides_revision,
        )

    def mark_overrides_changed(self) -> None:
        self._overrides_revision += 1

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
        self._apply_indicator_state(self._indicator_state.get())
        self._hydrate_from_domain_store()

    def on_unmount(self) -> None:
        self._indicator_reaction.dispose()
        self._follow_transition_reaction.dispose()
        self._follow_state_sync_reaction.dispose()
        self._follow_store.dispose()

    def _set_indicator_state(
        self,
        *,
        items: list | None = None,
        expanded: bool | None = None,
    ) -> None:
        """Update indicator projection state; rendering side effects happen in reaction."""
        current_items, current_expanded = self._indicator_state.get()
        next_items = list(current_items) if items is None else list(items)
        next_expanded = current_expanded if expanded is None else bool(expanded)
        self._indicator_state.set((next_items, next_expanded))

    def _apply_indicator_state(self, indicator_state: tuple[list, bool]) -> None:
        items, expanded = indicator_state
        # [LAW:dataflow-not-control-flow] Apply always runs; values control expansion.
        self._indicator.items = list(items)
        self._indicator.expanded = bool(expanded and items)
        self._clear_line_cache()
        if self.is_attached:
            self.refresh()

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
        self._reset_background_rerender_state()
        self._clear_line_cache()

        for blocks in self._domain_store.iter_completed_blocks():
            self._render_and_append_turn(blocks, self._last_filters)

        self._attach_stream_preview()
        self._recalculate_offsets()
        self.refresh()

    # // [LAW:one-source-of-truth] Follow state stored as string in view store.
    # String persistence in view_store remains derived from this canonical Observable.
    @property
    def _follow_state(self) -> FollowState:
        return self._follow_store.state.get()

    @_follow_state.setter
    def _follow_state(self, value: FollowState):
        self._follow_store.state.set(value)

    def _persist_follow_state(self, value: FollowState) -> None:
        if self._view_store is not None:
            self._view_store.set("nav:follow", value.value)

    def _dispatch_follow_event(
        self,
        event: FollowEvent,
        *,
        at_bottom: bool,
    ) -> None:
        """Dispatch a follow intent with explicit caller-owned scroll context.

        // [LAW:one-source-of-truth] Caller-provided at_bottom is authoritative.
        """
        self._follow_store.dispatch(event, at_bottom=bool(at_bottom))

    def _apply_follow_transition(self, payload: tuple[int, FollowTransition]) -> None:
        _seq, transition = payload
        if transition.scroll_to_end:
            with self._programmatic_scroll():
                self.scroll_end(animate=False)

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

    def get_search_turns_snapshot(self) -> SearchTurnsSnapshot:
        """Return an immutable turns snapshot for search consumers.

        // [LAW:locality-or-seam] Search reads turns through this seam, not `_turns`.
        // [LAW:one-source-of-truth] ConversationView is canonical owner of turn storage.
        """
        return SearchTurnsSnapshot(turns=tuple(self._turns))

    def current_scroll_y(self) -> float:
        """Return current vertical scroll offset."""
        return float(self.scroll_offset.y)

    def _blank_line(self, width: int) -> Strip:
        return Strip.blank(width, self.rich_style)

    def _safe_text_selection(self) -> Selection | None:
        try:
            return self.text_selection
        except NoScreen:
            return None

    def _should_lazy_refresh_turn(self, turn: TurnData) -> bool:
        needs_filter_refresh = (
            not turn.is_streaming
            and turn._filter_revision != self._active_filter_revision
        )
        return turn._pending_filter_snapshot is not None or needs_filter_refresh

    def _line_cache_key(
        self,
        *,
        turn: TurnData,
        local_y: int,
        scroll_x: int,
        width: int,
    ) -> tuple[int, int, int, int, int, int]:
        return (
            turn.turn_index,
            turn.line_offset,
            local_y,
            scroll_x,
            width,
            self._widest_line,
        )

    def _cached_line_strip(
        self,
        *,
        cache_key: tuple[int, int, int, int, int, int],
        selection: Selection | None,
    ) -> Strip | None:
        if selection is not None or cache_key not in self._line_cache:
            return None
        return self._line_cache[cache_key].apply_style(self.rich_style)

    def _strip_for_turn_line(
        self,
        *,
        turn: TurnData,
        local_y: int,
        scroll_x: int,
        width: int,
    ) -> Strip:
        if local_y < len(turn.strips):
            return turn.strips[local_y].crop_extend(
                scroll_x, scroll_x + width, self.rich_style
            )
        return self._blank_line(width)

    def _styled_line_strip(
        self,
        *,
        strip: Strip,
        selection: Selection | None,
        actual_y: int,
        scroll_x: int,
    ) -> Strip:
        if selection is not None:
            span = selection.get_span(actual_y)
            if span is not None:
                strip = self._apply_selection_to_strip(strip, span)
        strip = strip.apply_style(self.rich_style)
        return strip.apply_offsets(scroll_x, actual_y)

    def _record_line_cache_key(
        self,
        *,
        turn_idx: int,
        cache_key: tuple[int, int, int, int, int, int],
        strip: Strip,
        selection: Selection | None,
    ) -> None:
        # [LAW:dataflow-not-control-flow] Selection disables cache writes to avoid persisting transient highlighting.
        if selection is not None:
            return
        self._line_cache[cache_key] = strip
        if turn_idx not in self._cache_keys_by_turn:
            self._cache_keys_by_turn[turn_idx] = set()
        self._cache_keys_by_turn[turn_idx].add(cache_key)
        self._line_cache_index_write_count += 1
        if self._line_cache_index_write_count >= self._line_cache_index_prune_interval:
            self._line_cache_index_write_count = 0
            self._prune_line_cache_index()

    def _overlay_line(self, strip: Strip, *, y: int, width: int) -> Strip:
        # [LAW:single-enforcer] Error indicator overlay is applied from a single boundary.
        return cc_dump.tui.error_indicator.composite_overlay(
            strip, y, width, self._indicator
        )

    def _render_line_core(
        self,
        *,
        y: int,
        actual_y: int,
        width: int,
        scroll_x: int,
        selection: Selection | None,
    ) -> Strip:
        if actual_y >= self._total_lines:
            return self._blank_line(width)

        turn = self._find_turn_for_line(actual_y)
        if turn is None:
            return self._blank_line(width)
        if self._should_lazy_refresh_turn(turn):
            self._lazy_rerender_turn(turn)

        local_y = actual_y - turn.line_offset
        cache_key = self._line_cache_key(
            turn=turn,
            local_y=local_y,
            scroll_x=scroll_x,
            width=width,
        )
        cached_strip = self._cached_line_strip(
            cache_key=cache_key,
            selection=selection,
        )
        if cached_strip is not None:
            return self._overlay_line(cached_strip, y=y, width=width)

        strip = self._strip_for_turn_line(
            turn=turn,
            local_y=local_y,
            scroll_x=scroll_x,
            width=width,
        )
        strip = self._styled_line_strip(
            strip=strip,
            selection=selection,
            actual_y=actual_y,
            scroll_x=scroll_x,
        )
        self._record_line_cache_key(
            turn_idx=turn.turn_index,
            cache_key=cache_key,
            strip=strip,
            selection=selection,
        )
        return self._overlay_line(strip, y=y, width=width)

    def _report_render_line_exception(self, exc: Exception) -> None:
        logger.exception("render_line failed")
        err_key = f"render:{type(exc).__name__}"
        items, expanded = self._indicator_state.get()
        if not any(item.id == err_key for item in items):
            next_items = list(items)
            next_items.append(
                cc_dump.app.error_models.ErrorItem(
                    err_key, "\u26a0\ufe0f", f"{type(exc).__name__}: {exc}"
                )
            )
            self._set_indicator_state(items=next_items, expanded=expanded)

    def render_line(self, y: int) -> Strip:
        """Line API: render a single line at virtual position y."""
        scroll_x, scroll_y = self.scroll_offset
        actual_y = scroll_y + y
        width = self._content_width
        selection = self._safe_text_selection()
        try:
            return self._render_line_core(
                y=y,
                actual_y=actual_y,
                width=width,
                scroll_x=scroll_x,
                selection=selection,
            )
        except Exception as exc:
            self._report_render_line_exception(exc)
            return self._blank_line(width)

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
        render_key = self._turn_render_key(width)

        # Apply the pending filters
        filters = dict(self._last_filters)
        turn.re_render(
            filters,
            console,
            width,
            block_cache=self._block_strip_cache,
            search_ctx=self._last_search_ctx,  # Pass stored search context
            overrides=self._view_overrides,
            render_key=render_key,
            runtime=self._render_runtime,
        )
        turn._filter_revision = self._active_filter_revision
        # re_render clears _pending_filter_snapshot

        # Coalesce deferred offset recalcs across multiple lazy-rerendered turns.
        # // [LAW:dataflow-not-control-flow] Pending min index drives a fixed flush path.
        self._schedule_deferred_offset_recalc(turn.turn_index)

    def _schedule_deferred_offset_recalc(self, from_turn_index: int) -> None:
        """Queue one deferred offset recalc using the earliest changed turn index."""
        current = self._deferred_offset_recalc_start_idx
        if current is None or from_turn_index < current:
            self._deferred_offset_recalc_start_idx = from_turn_index
        if self._deferred_offset_recalc_scheduled:
            return
        self._deferred_offset_recalc_scheduled = True
        self.call_later(self._flush_deferred_offset_recalc)

    def _flush_deferred_offset_recalc(self) -> None:
        """Apply deferred offset recalculation and optional anchor restoration."""
        self._deferred_offset_recalc_scheduled = False
        start_idx = self._deferred_offset_recalc_start_idx
        self._deferred_offset_recalc_start_idx = None
        if start_idx is None:
            return
        self._recalculate_offsets_from(start_idx)
        if not self._is_following:
            self._resolve_anchor()
        self.refresh()

    def _deferred_offset_recalc(self, from_turn_index: int):
        """Recalculate offsets after a lazy re-render, then refresh display.

        Resolves stored turn-level anchor to prevent viewport drift
        when off-viewport turns lazily re-render and shift line offsets.
        """
        self._deferred_offset_recalc_start_idx = from_turn_index
        self._flush_deferred_offset_recalc()

    def _reset_background_rerender_state(self) -> None:
        """Cancel queued background rerender work and invalidate scheduled callbacks."""
        # // [LAW:single-enforcer] Generation token is the sole cancellation mechanism.
        self._background_rerender_generation += 1
        self._background_rerender_scheduled = False
        self._pending_rerender_indices.clear()

    def _schedule_background_rerender(self) -> None:
        """Schedule incremental off-viewport rerender work."""
        if self._background_rerender_scheduled:
            return
        generation = self._background_rerender_generation
        self._background_rerender_scheduled = True
        self.call_later(lambda: self._background_rerender(generation))

    def _background_rerender_generation_for(self, generation: int | None) -> int:
        return self._background_rerender_generation if generation is None else generation

    def _process_background_rerender_turn(
        self,
        idx: int,
        *,
        width: int,
        console,
        render_key: tuple[int, int, int, int],
    ) -> int | None:
        if idx < 0 or idx >= len(self._turns):
            return None
        td = self._turns[idx]
        if td.is_streaming or td._pending_filter_snapshot is None:
            return None
        changed = td.re_render(
            self._last_filters,
            console,
            width,
            block_cache=self._block_strip_cache,
            search_ctx=self._last_search_ctx,
            overrides=self._view_overrides,
            render_key=render_key,
            runtime=self._render_runtime,
        )
        td._filter_revision = self._active_filter_revision
        return idx if changed else -1

    def _process_background_rerender_chunk(
        self,
        *,
        width: int,
        console,
        render_key: tuple[int, int, int, int],
    ) -> tuple[int | None, int]:
        first_changed: int | None = None
        processed = 0
        while processed < self._background_rerender_chunk_size and self._pending_rerender_indices:
            idx = self._pending_rerender_indices.popleft()
            result = self._process_background_rerender_turn(
                idx,
                width=width,
                console=console,
                render_key=render_key,
            )
            if result is None:
                continue
            processed += 1
            if result >= 0 and (first_changed is None or result < first_changed):
                first_changed = result
        return (first_changed, processed)

    def _apply_background_rerender_changes(self, first_changed: int | None) -> None:
        if first_changed is None:
            return
        self._recalculate_offsets_from(first_changed)
        if not self._is_following:
            self._resolve_anchor()
        self.refresh()

    def _background_rerender(self, generation: int | None = None) -> None:
        """Incrementally rerender deferred turns in background.

        Processes a bounded number of turns per tick to keep UI responsive.
        """
        active_generation = self._background_rerender_generation_for(generation)
        if active_generation != self._background_rerender_generation:
            return
        self._background_rerender_scheduled = False
        width = self._content_width if self._size_known else self._last_width
        console = self.app.console
        render_key = self._turn_render_key(width)
        pending_before = len(self._pending_rerender_indices)
        first_changed: int | None = None
        processed = 0
        pending_after = pending_before

        with monitor_slow_path(
            "conversation.background_rerender_tick",
            logger=logger,
            context=lambda: {
                "turn_count": len(self._turns),
                "chunk_size": self._background_rerender_chunk_size,
                "pending_before": pending_before,
                "pending_after": pending_after,
                "processed": processed,
                "first_changed": first_changed,
            },
        ):
            first_changed, processed = self._process_background_rerender_chunk(
                width=width,
                console=console,
                render_key=render_key,
            )
            self._apply_background_rerender_changes(first_changed)

            pending_after = len(self._pending_rerender_indices)
            if pending_after > 0:
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
        "filters_changed":   "_rerender_affected",
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
        "new_turn", "stream_delta", "stream_finalized", "focus_changed",
    })
    _ANCHOR_REASONS = frozenset({
        "filters_changed", "search",
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
        Uses incremental widest-line tracking to avoid full-list scans per tick.
        """
        turns = self._turns
        start_idx_input = start_idx
        with monitor_slow_path(
            "conversation.recalculate_offsets_from",
            logger=logger,
            context=lambda: {
                "start_idx_input": start_idx_input,
                "start_idx_effective": start_idx,
                "turn_count": len(turns),
            },
        ):
            if start_idx > 0 and start_idx < len(turns):
                prev = turns[start_idx - 1]
                offset = prev.line_offset + prev.line_count
            else:
                offset = 0
                start_idx = 0

            suffix_widest = 0
            for i in range(start_idx, len(turns)):
                turns[i].line_offset = offset
                offset += turns[i].line_count
                turn_widest = turns[i]._widest_strip
                if turn_widest > suffix_widest:
                    suffix_widest = turn_widest

            # // [LAW:dataflow-not-control-flow] Width strategy derives from start_idx + counter values.
            if start_idx == 0:
                # Already scanned all turns above when recomputing offsets from zero.
                widest = suffix_widest
                self._offset_recalc_incremental_count = 0
            elif self._offset_recalc_incremental_count >= self._offset_recalc_full_width_interval:
                widest = 0
                for i in range(len(turns)):
                    turn_widest = turns[i]._widest_strip
                    if turn_widest > widest:
                        widest = turn_widest
                self._offset_recalc_incremental_count = 0
            else:
                widest = max(self._widest_strip_max, suffix_widest)
                self._offset_recalc_incremental_count += 1
            self._widest_strip_max = widest

            self._total_lines = offset
            self._widest_line = max(widest, self._last_width)
            self.virtual_size = Size(self._widest_line, self._total_lines)
            self._invalidate_cache_for_turns(start_idx, len(turns))

    def _on_turn_added(self, blocks: list, index: int) -> None:
        """Domain store callback: a completed turn was added."""
        if not self.is_attached:
            return
        self._invalidate("new_turn", blocks=blocks)

    def _prune_all_turns(self) -> None:
        self._turns.clear()
        self._scroll_anchor = None
        self._reset_background_rerender_state()
        self._recalculate_offsets()
        if self.is_attached:
            self.refresh()

    def _reindex_turns(self) -> None:
        for idx, td in enumerate(self._turns):
            td.turn_index = idx

    def _rebase_scroll_anchor_after_prune(self, pruned_count: int) -> None:
        anchor = self._scroll_anchor
        if anchor is None:
            return
        self._scroll_anchor = ScrollAnchor(
            turn_index=max(0, anchor.turn_index - pruned_count),
            line_in_turn=anchor.line_in_turn,
        )

    def _clear_pending_filter_snapshots(self) -> None:
        for td in self._turns:
            td._pending_filter_snapshot = None

    def _refresh_after_turn_prune(self) -> None:
        self._clear_line_cache()
        self._recalculate_offsets()
        if not self._is_following and self.is_attached:
            self._resolve_anchor()
        if self.is_attached:
            self.refresh()

    def _on_turns_pruned(self, pruned_count: int) -> None:
        """Domain store callback: oldest completed turns were pruned."""
        if not self.is_attached:
            return
        if pruned_count <= 0:
            return
        if pruned_count >= len(self._turns):
            self._prune_all_turns()
            return

        del self._turns[:pruned_count]
        self._reindex_turns()
        self._rebase_scroll_anchor_after_prune(pruned_count)
        self._reset_background_rerender_state()
        self._clear_pending_filter_snapshots()
        self._refresh_after_turn_prune()

    def _render_new_turn(self, blocks: list, filters: dict | None = None) -> None:
        """Render blocks to TurnData and append as completed turn.

        // [LAW:single-enforcer] Called via _invalidate("new_turn").
        Post-render (follow-scroll) handled by _post_render.
        """
        self._render_and_append_turn(blocks, filters)

    def _render_and_append_turn(self, blocks: list, filters: dict | None = None) -> None:
        """Render blocks to TurnData and append as completed turn."""
        if filters is None:
            filters = self._last_filters
        width = self._content_width if self._size_known else self._last_width
        console = self.app.console
        self._update_render_revisions(self._last_search_ctx)
        turn_index = len(self._turns)
        render_key = self._turn_render_key(width)

        strips, block_strip_map, flat_blocks = cc_dump.tui.rendering.render_turn_to_strips(
            blocks, filters, console, width, block_cache=self._block_strip_cache,
            search_ctx=self._last_search_ctx,
            turn_index=turn_index,
            overrides=self._view_overrides,
            runtime=self._render_runtime,
        )
        td = TurnData(
            turn_index=turn_index,
            blocks=blocks,
            strips=strips,
            block_strip_map=block_strip_map,
            _flat_blocks=flat_blocks,
        )
        td._strip_hash = _hash_strips(strips)
        td._last_render_key = render_key
        td._widest_strip = _compute_widest(strips)
        td.compute_relevant_keys()

        # Use ALWAYS_VISIBLE default to match filters dict structure
        td._last_filter_snapshot = {
            k: filters.get(k, cc_dump.core.formatting.ALWAYS_VISIBLE) for k in td.relevant_filter_keys
        }
        td._filter_revision = self._active_filter_revision
        self._append_completed_turn(td)

    def add_turn(self, blocks: list, filters: dict | None = None):
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

    def _attach_stream_preview(self) -> None:
        """Attach the active streaming preview."""
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

    def _render_stream_started(self, request_id: str, meta: dict | None = None) -> None:
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
            delta_text, console, width, runtime=self._render_runtime
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
        """Flush coalesced stream delta invalidation for focused stream."""
        self._stream_delta_flush_scheduled = False
        pending = self._pending_stream_delta_request_ids
        self._pending_stream_delta_request_ids = set()
        if not pending:
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
        if block.show_during_streaming and is_focused:
            # // [LAW:dataflow-not-control-flow] Pending set holds variability; flush loop stays fixed.
            self._queue_stream_delta(request_id)

    def _render_stream_delta(self, request_id: str = "") -> None:
        """Re-render focused stream preview after new delta block."""
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
            runtime=self._render_runtime,
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
            k: self._last_filters.get(k, cc_dump.core.formatting.ALWAYS_VISIBLE) for k in td.relevant_filter_keys
        }
        td._filter_revision = self._active_filter_revision

        # Remove from preview registry
        self._stream_preview_turns.pop(request_id, None)
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

    # ─── Delegating accessors (read from domain_store) ─────────────────────

    def get_focused_stream_id(self) -> str | None:
        return self._domain_store.get_focused_stream_id()

    def set_focused_stream(self, request_id: str) -> bool:
        """Focus an active stream for live rendering preview."""
        return self._domain_store.set_focused_stream(request_id)

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
        self.begin_stream("__default__")

    def append_streaming_block(self, block, filters: dict | None = None):
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
        self._update_render_revisions(search_ctx)

        if self._pending_restore is not None:
            self._invalidate("restore", filters=filters)
            return

        reason = "search" if search_ctx is not None else "filters_changed"
        self._invalidate(reason, filters=filters, search_ctx=search_ctx, force=force)

    def _rerender_affected(self, filters: dict | None = None, search_ctx=None, force: bool = False) -> None:
        """Re-render affected turns in place using viewport-only strategy.

        // [LAW:single-enforcer] Called via _invalidate("filters_changed") or _invalidate("search").
        Post-render (anchor resolve) handled by _post_render.
        """
        if filters is None:
            filters = self._last_filters

        width = self._content_width if self._size_known else self._last_width
        console = self.app.console

        # [LAW:dataflow-not-control-flow] Revision value tracks whether a turn has been validated.
        self._active_filter_revision += 1
        target_revision = self._active_filter_revision
        self._reset_background_rerender_state()
        self._deferred_offset_recalc_scheduled = False
        self._deferred_offset_recalc_start_idx = None

        render_key = self._turn_render_key(width)

        # Search highlighting still uses full-scan queueing to preserve existing behavior.
        is_search = search_ctx is not None
        if is_search:
            self._rerender_affected_full_scan(
                filters=filters,
                search_ctx=search_ctx,
                force=True,
                width=width,
                console=console,
                target_revision=target_revision,
                render_key=render_key,
            )
            return

        self._rerender_affected_bounded(
            filters=filters,
            force=force,
            width=width,
            console=console,
            target_revision=target_revision,
            render_key=render_key,
        )

    def _rerender_viewport_turn(
        self,
        td: TurnData,
        *,
        filters: dict,
        console,
        width: int,
        force: bool,
        target_revision: int,
        render_key: tuple[int, int, int, int],
    ) -> tuple[bool, bool]:
        if td.is_streaming:
            return (False, False)
        changed = td.re_render(
            filters,
            console,
            width,
            force=force,
            block_cache=self._block_strip_cache,
            search_ctx=None,
            overrides=self._view_overrides,
            render_key=render_key,
            runtime=self._render_runtime,
        )
        td._pending_filter_snapshot = None
        td._filter_revision = target_revision
        return (True, changed)

    def _prefetch_indices(
        self,
        *,
        prefetch_start: int,
        prefetch_end: int,
        vp_start: int,
        vp_end: int,
    ) -> list[int]:
        # [LAW:dataflow-not-control-flow] Index list computes inclusion once, then runs fixed staging.
        return [idx for idx in range(prefetch_start, prefetch_end) if idx < vp_start or idx >= vp_end]

    def _stage_prefetch_turn(
        self,
        td: TurnData,
        *,
        idx: int,
        filters: dict,
        force: bool,
        target_revision: int,
        render_key: tuple[int, int, int, int],
    ) -> tuple[bool, bool]:
        if td.is_streaming:
            return (False, False)
        snapshot = {
            k: filters.get(k, cc_dump.core.formatting.ALWAYS_VISIBLE)
            for k in td.relevant_filter_keys
        }
        needs_render_key = render_key != td._last_render_key
        if force or snapshot != td._last_filter_snapshot or needs_render_key:
            td._pending_filter_snapshot = snapshot
            # // [LAW:dataflow-not-control-flow] Queue index value drives background work.
            self._pending_rerender_indices.append(idx)
            return (True, True)
        td._pending_filter_snapshot = None
        td._filter_revision = target_revision
        return (True, False)

    def _rerender_affected_bounded(
        self,
        *,
        filters: dict,
        force: bool,
        width: int,
        console,
        target_revision: int,
        render_key: tuple[int, int, int, int],
    ) -> None:
        """Re-render viewport turns immediately; prefetch a bounded off-viewport window.

        // [LAW:dataflow-not-control-flow] Fixed operations; window bounds drive affected indices.
        """
        vp_start, vp_end = self._viewport_turn_range()
        prefetch_start = max(0, vp_start - self._background_rerender_prefetch_turn_window)
        prefetch_end = min(len(self._turns), vp_end + self._background_rerender_prefetch_turn_window)

        first_changed = None
        has_deferred = False
        deferred_count = 0
        viewport_count = 0

        with monitor_slow_path(
            "conversation.rerender_affected",
            logger=logger,
            context=lambda: {
                "turn_count": len(self._turns),
                "vp_start": vp_start,
                "vp_end": vp_end,
                "prefetch_start": prefetch_start,
                "prefetch_end": prefetch_end,
                "viewport_count": viewport_count,
                "deferred_count": deferred_count,
                "force": force,
                "search_active": False,
                "first_changed": first_changed,
            },
        ):
            for idx in range(vp_start, min(vp_end, len(self._turns))):
                is_viewport_turn, changed = self._rerender_viewport_turn(
                    self._turns[idx],
                    filters=filters,
                    console=console,
                    width=width,
                    force=force,
                    target_revision=target_revision,
                    render_key=render_key,
                )
                if not is_viewport_turn:
                    continue
                viewport_count += 1
                if changed and first_changed is None:
                    first_changed = idx

            for idx in self._prefetch_indices(
                prefetch_start=prefetch_start,
                prefetch_end=prefetch_end,
                vp_start=vp_start,
                vp_end=vp_end,
            ):
                considered, deferred = self._stage_prefetch_turn(
                    self._turns[idx],
                    idx=idx,
                    filters=filters,
                    force=force,
                    target_revision=target_revision,
                    render_key=render_key,
                )
                if not considered:
                    continue
                if deferred:
                    has_deferred = True
                    deferred_count += 1

            if first_changed is not None:
                self._recalculate_offsets_from(first_changed)
            if has_deferred:
                self._schedule_background_rerender()

    def _rerender_affected_full_scan(
        self,
        *,
        filters: dict,
        search_ctx,
        force: bool,
        width: int,
        console,
        target_revision: int,
        render_key: tuple[int, int, int, int],
    ) -> None:
        """Full-scan rerender path used for search highlight propagation."""
        vp_start, vp_end = self._viewport_turn_range()
        first_changed = None
        has_deferred = False
        deferred_count = 0
        viewport_count = 0

        with monitor_slow_path(
            "conversation.rerender_affected",
            logger=logger,
            context=lambda: {
                "turn_count": len(self._turns),
                "vp_start": vp_start,
                "vp_end": vp_end,
                "viewport_count": viewport_count,
                "deferred_count": deferred_count,
                "force": force,
                "search_active": True,
                "first_changed": first_changed,
            },
        ):
            for idx, td in enumerate(self._turns):
                if td.is_streaming:
                    continue
                if vp_start <= idx < vp_end:
                    viewport_count += 1
                    if td.re_render(
                        filters,
                        console,
                        width,
                        force=force,
                        block_cache=self._block_strip_cache,
                        search_ctx=search_ctx,
                        overrides=self._view_overrides,
                        render_key=render_key,
                        runtime=self._render_runtime,
                    ):
                        if first_changed is None:
                            first_changed = idx
                    td._pending_filter_snapshot = None
                    td._filter_revision = target_revision
                else:
                    snapshot = {
                        k: filters.get(k, cc_dump.core.formatting.ALWAYS_VISIBLE)
                        for k in td.relevant_filter_keys
                    }
                    needs_render_key = render_key != td._last_render_key
                    if force or snapshot != td._last_filter_snapshot or needs_render_key:
                        td._pending_filter_snapshot = snapshot
                        self._pending_rerender_indices.append(idx)
                        has_deferred = True
                        deferred_count += 1
                    else:
                        td._pending_filter_snapshot = None
                        td._filter_revision = target_revision

            if first_changed is not None:
                self._recalculate_offsets_from(first_changed)
            if has_deferred:
                self._schedule_background_rerender()

    def ensure_turn_rendered(self, turn_index: int):
        """Force-render a specific turn, then recalculate offsets.

        Used before scroll_to_block() to ensure the target turn has accurate
        block_strip_map and line_offset after deferred renders.
        """
        if turn_index >= len(self._turns):
            return
        td = self._turns[turn_index]
        width = self._content_width if self._size_known else self._last_width
        render_key = self._turn_render_key(width)
        td.re_render(
            self._last_filters, self.app.console, width,
            force=True, block_cache=self._block_strip_cache,
            search_ctx=self._last_search_ctx,
            overrides=self._view_overrides,
            render_key=render_key,
            runtime=self._render_runtime,
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
        self._update_render_revisions(self._last_search_ctx)
        render_key = self._turn_render_key(width)
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
                    search_ctx=self._last_search_ctx,
                    turn_index=td.turn_index,
                    overrides=self._view_overrides,
                    runtime=self._render_runtime,
                )
            )
            td._strip_hash = _hash_strips(td.strips)
            td._last_render_key = render_key
            td._widest_strip = _compute_widest(td.strips)
            td._pending_filter_snapshot = None
            td._filter_revision = self._active_filter_revision
        self._recalculate_offsets()

    # ─── Sprint 2: Follow mode ───────────────────────────────────────────────

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        """Detect scroll position changes from ALL sources.

        CRITICAL: Must call super() to preserve scrollbar sync and refresh.
        CRITICAL: Signature is (old_value, new_value), not (value).

        // [LAW:dataflow-not-control-flow] Transition dispatched to reactive follow store.
        """
        super().watch_scroll_y(old_value, new_value)
        if self._scrolling_programmatically:
            return
        # Compute anchor on user scroll (turn-level anchor for vis_state changes)
        self._scroll_anchor = self._compute_anchor_from_scroll()
        self._dispatch_follow_event(
            FollowEvent.USER_SCROLL,
            at_bottom=bool(self.is_vertical_scroll_end),
        )

    def toggle_follow(self):
        """Toggle follow mode.

        // [LAW:dataflow-not-control-flow] Transition dispatched to reactive follow store.
        """
        self._dispatch_follow_event(FollowEvent.TOGGLE, at_bottom=False)

    def scroll_to_bottom(self):
        """Scroll to bottom. Transitions ENGAGED→ACTIVE; OFF stays OFF.

        // [LAW:dataflow-not-control-flow] Transition dispatched to reactive follow store.
        """
        self._dispatch_follow_event(FollowEvent.SCROLL_BOTTOM, at_bottom=False)

    def scroll_to_top(self) -> None:
        """Scroll to top and deactivate follow mode."""
        self._dispatch_follow_event(FollowEvent.DEACTIVATE, at_bottom=False)
        with self._programmatic_scroll():
            self.scroll_home(animate=False)

    def capture_scroll_anchor(self) -> None:
        """Capture the current turn-level anchor for later restore.

        // [LAW:one-source-of-truth] ConversationView owns `_scroll_anchor` lifecycle.
        """
        self._scroll_anchor = self._compute_anchor_from_scroll()

    def restore_scroll_y(self, y: float) -> None:
        """Restore absolute vertical scroll position without animation."""
        with self._programmatic_scroll():
            self.scroll_to(y=y, animate=False)
        # // [LAW:one-source-of-truth] Refresh anchor after programmatic restore
        # because watch_scroll_y skips recompute while the guard is active.
        self.capture_scroll_anchor()

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

        # // [LAW:dataflow-not-control-flow] Deactivate via follow transition event.
        self._dispatch_follow_event(FollowEvent.DEACTIVATE, at_bottom=False)
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

    def _compute_anchor_from_scroll(self) -> ScrollAnchor | None:
        """Compute turn-level anchor from current scroll_y.

        Returns ScrollAnchor(turn_index, line_in_turn).
        Returns None if no turns or scroll position invalid.
        """
        if not self._turns:
            return None

        scroll_y = int(self.scroll_offset.y)
        turn = self._find_turn_for_line(scroll_y)
        if turn is None:
            return None

        line_in_turn = scroll_y - turn.line_offset
        return ScrollAnchor(turn_index=turn.turn_index, line_in_turn=max(0, line_in_turn))

    def _scroll_programmatically_to(self, *, y: int) -> None:
        with self._programmatic_scroll():
            self.scroll_to(y=y, animate=False)

    def _last_visible_turn_index(self) -> int | None:
        for idx in range(len(self._turns) - 1, -1, -1):
            if self._turns[idx].line_count > 0:
                return idx
        return None

    def _resolve_anchor_turn_index(self, *, anchor_turn_index: int) -> int | None:
        """Resolve the canonical topmost-visible-turn anchor index.

        // [LAW:one-source-of-truth] One anchor strategy: scan forward from anchor turn,
        // wrapping once, and pick the first visible turn.
        """
        turn_count = len(self._turns)
        if turn_count == 0:
            return None

        if anchor_turn_index >= turn_count:
            # // [LAW:dataflow-not-control-flow] Stale out-of-range anchors map to
            # // the last visible turn to preserve bottom-of-viewport semantics.
            return self._last_visible_turn_index()

        start = min(max(anchor_turn_index, 0), turn_count - 1)
        for step in range(turn_count):
            idx = (start + step) % turn_count
            if self._turns[idx].line_count > 0:
                return idx
        return None

    @staticmethod
    def _coerce_non_negative_int(raw_value: object, *, default: int = 0) -> int:
        """Convert persisted state to a safe, non-negative integer."""
        # // [LAW:single-enforcer] Persisted anchor integer coercion is centralized here.
        if isinstance(raw_value, int):
            coerced = raw_value
        elif isinstance(raw_value, float):
            coerced = int(raw_value)
        elif isinstance(raw_value, (str, bytes, bytearray)):
            try:
                coerced = int(raw_value)
            except ValueError:
                return default
        else:
            return default
        return max(0, coerced)

    def _resolve_anchor(self):
        """Resolve stored anchor to scroll_y after content changes.

        Scrolls to the position that matches the stored anchor.
        Uses _scrolling_programmatically guard to prevent anchor corruption.
        """
        anchor = self._scroll_anchor
        if anchor is None:
            return

        resolved_turn_index = self._resolve_anchor_turn_index(
            anchor_turn_index=anchor.turn_index
        )
        if resolved_turn_index is None:
            return

        turn = self._turns[resolved_turn_index]
        line_in_turn = (
            min(anchor.line_in_turn, turn.line_count - 1)
            if resolved_turn_index == anchor.turn_index
            else 0
        )
        target_y = turn.line_offset + line_in_turn
        self._scroll_programmatically_to(y=target_y)

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
        """Store click position for block-scoped double-click selection."""
        # Store for text_select_all (called by Widget._on_click on double-click)
        self._last_click_content_y = int(event.y + self.scroll_offset.y)

    # ─── Error indicator ────────────────────────────────────────────────────

    def update_error_items(self, items: list) -> None:
        """Set error indicator items. Called by app when stale files change."""
        _items, expanded = self._indicator_state.get()
        self._set_indicator_state(items=items, expanded=(expanded if items else False))

    def on_mouse_move(self, event) -> None:
        """Track hover for error indicator expansion."""
        content_offset = event.get_content_offset(self)
        hit = (
            content_offset is not None
            and cc_dump.tui.error_indicator.hit_test_event(
                self._indicator, content_offset.x, content_offset.y, self._content_width
            )
        )
        items, expanded = self._indicator_state.get()
        if hit != expanded:
            self._set_indicator_state(items=items, expanded=hit)

    # ─── State management ────────────────────────────────────────────────────

    def get_state(self) -> dict:
        """Extract view state for hot-reload preservation.

        Domain data (block lists, streams) lives in DomainStore and persists
        across widget replacement. This only captures view/rendering state.
        """
        # Serialize scroll anchor for position preservation across hot-reload
        anchor = self._scroll_anchor
        anchor_dict = (
            {"turn_index": anchor.turn_index, "line_in_turn": anchor.line_in_turn}
            if anchor is not None
            else None
        )

        return {
            "follow_state": self._follow_state.value,
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

        # Restore view overrides
        vo_data = state.get("view_overrides", {})
        self._view_overrides = cc_dump.tui.view_overrides.ViewOverrides.from_dict(vo_data)
        self.mark_overrides_changed()

    def _render_restore(self, filters: dict | None = None) -> None:
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
                line_in_turn_raw = anchor_dict.get(
                    "line_in_turn",
                    anchor_dict.get("line_in_block", 0),  # Legacy hot-reload state shape.
                )
                self._scroll_anchor = ScrollAnchor(
                    turn_index=self._coerce_non_negative_int(
                        anchor_dict.get("turn_index", 0)
                    ),
                    line_in_turn=self._coerce_non_negative_int(line_in_turn_raw),
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
        self._render_state: Observable[tuple[int, dict[str, object]]] = Observable(
            (self._view_index, self._last_snapshot)
        )
        # [LAW:single-enforcer] One reactive projection owns stats panel rendering.
        self._render_reaction = reaction(
            lambda: self._render_state.get(),
            self._apply_render_state,
            fire_immediately=False,
        )

    def on_mount(self) -> None:
        self._store_reaction = stx.reaction(
            self.app,
            lambda: self.app._view_store.get("panel:stats_snapshot"),
            self._apply_store_snapshot,
            fire_immediately=True,
        )
        self._apply_render_state(self._render_state.get())

    def on_unmount(self) -> None:
        self._store_reaction.dispose()
        self._render_reaction.dispose()

    def _apply_store_snapshot(self, payload: object) -> None:
        self.update_display(payload if isinstance(payload, dict) else {})

    def update_display(self, snapshot: dict[str, object]) -> None:
        """Apply canonical stats snapshot projection from view store."""
        # [LAW:one-source-of-truth] Panel renders from canonical view-store snapshot shape.
        summary = snapshot.get("summary", {})
        timeline = snapshot.get("timeline", [])
        models = snapshot.get("models", [])
        self._last_snapshot = {
            "summary": dict(summary) if isinstance(summary, dict) else {},
            "timeline": list(timeline) if isinstance(timeline, list) else [],
            "models": list(models) if isinstance(models, list) else [],
        }
        self._refresh_display()

    def _refresh_display(self):
        self._render_state.set((self._view_index, self._last_snapshot))

    def _apply_render_state(self, render_state: tuple[int, dict[str, object]]) -> None:
        """Rebuild the display text."""
        # // [LAW:dataflow-not-control-flow] exception: Textual update() requires an attached app context.
        if not self.is_attached:
            return
        view_index, snapshot = render_state
        view_mode = self._VIEW_ORDER[view_index]
        text = cc_dump.tui.panel_renderers.render_analytics_panel(
            snapshot,
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
        return {"view_index": self._view_index}

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self._view_index = int(state.get("view_index", 0)) % len(self._VIEW_ORDER)
        self._refresh_display()


class LogsPanel(RichLog):
    """Panel showing cc-dump application logs (debug, errors, internal messages)."""

    def __init__(self):
        super().__init__(highlight=False, markup=False, wrap=True, max_lines=1000)

    # [LAW:dataflow-not-control-flow] Log level style dispatch
    def _get_log_level_styles(self):
        p = cc_dump.core.palette.PALETTE
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
def create_conversation_view(
    view_store=None,
    domain_store=None,
    runtime: "RenderRuntime | None" = None,
) -> ConversationView:
    """Create a new ConversationView instance."""
    return ConversationView(
        view_store=view_store,
        domain_store=domain_store,
        runtime=runtime,
    )


def create_stats_panel() -> StatsPanel:
    """Create a new StatsPanel instance."""
    return StatsPanel()


def create_logs_panel() -> LogsPanel:
    """Create a new LogsPanel instance."""
    return LogsPanel()
