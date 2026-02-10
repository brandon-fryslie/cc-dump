"""Widget factory - creates widget instances that can be hot-swapped.

This module is RELOADABLE. When it reloads, the app can create new widget
instances from the updated class definitions and swap them in.

Widget classes are defined here, not in widgets.py. The widgets.py module
becomes a thin non-reloadable shell that just holds the current instances.
"""

import json
from dataclasses import dataclass, field
from textual.widgets import RichLog, Static
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.cache import LRUCache
from textual.geometry import Size
from rich.text import Text
from rich.markdown import Markdown

# Use module-level imports for hot-reload
import cc_dump.palette
import cc_dump.analysis
import cc_dump.tui.rendering
import cc_dump.tui.panel_renderers
import cc_dump.db_queries


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
    blocks: list  # list[FormattedBlock] - source of truth
    strips: list  # list[Strip] - pre-rendered lines
    block_strip_map: dict = field(
        default_factory=dict
    )  # block_index → first strip line
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
        """
        keys = set()
        for block in self.blocks:
            cat = cc_dump.tui.rendering.get_category(block)
            if cat is not None:
                keys.add(cat.value)
        self.relevant_filter_keys = keys

    def re_render(
        self,
        filters: dict,
        console,
        width: int,
        force: bool = False,
        block_cache=None,
        search_ctx=None,
    ) -> bool:
        """Re-render if a relevant filter changed. Returns True if strips changed.

        Args:
            force: Force re-render even if filter snapshot hasn't changed.
            block_cache: Optional LRUCache for caching rendered strips per block.
            search_ctx: Optional SearchContext for highlighting matches.
        """
        from cc_dump.formatting import Level

        snapshot = {k: filters.get(k, Level.FULL) for k in self.relevant_filter_keys}
        # Force re-render when search context changes
        if not force and search_ctx is None and snapshot == self._last_filter_snapshot:
            return False
        self._last_filter_snapshot = snapshot
        self._pending_filter_snapshot = None  # clear deferred state
        self.strips, self.block_strip_map = cc_dump.tui.rendering.render_turn_to_strips(
            self.blocks,
            filters,
            console,
            width,
            block_cache=block_cache,
            search_ctx=search_ctx,
            turn_index=self.turn_index,
        )
        self._widest_strip = _compute_widest(self.strips)
        return True

    def strip_offset_for_block(self, block_index: int) -> int | None:
        """Return the first strip line for a given block index, or None if filtered out."""
        return self.block_strip_map.get(block_index)


class ConversationView(ScrollView):
    """Virtual-rendering conversation display using Line API.

    Stores turns as TurnData (blocks + pre-rendered strips).
    render_line(y) maps virtual line y to the correct turn's strip.
    Only visible lines are rendered per frame.
    """

    DEFAULT_CSS = """
    ConversationView {
        background: $surface;
        color: $foreground;
        overflow-y: scroll;
        overflow-x: hidden;
        &:focus {
            background-tint: $foreground 5%;
        }
    }
    """

    def __init__(self):
        super().__init__()
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
        self._follow_mode: bool = True
        self._pending_restore: dict | None = None
        self._scrolling_programmatically: bool = False

    def on_mount(self):
        """Push markdown theme onto console when widget mounts.

        Builds theme dynamically from Textual's theme colors for consistency.
        """
        # Extract colors from Textual's theme
        # Use screen styles as reference for theme colors
        text_color = str(self.app.screen.styles.color.rich_color)
        bg_color = str(self.app.screen.styles.background.rich_color)

        # Derive semantic colors from theme
        # For code backgrounds, we want a subtle contrast
        is_dark = self.app.dark

        # Build markdown theme dynamically from Textual colors
        from rich.theme import Theme

        markdown_theme = Theme({
            # Inline code: primary text on subtle background variation
            # Use a slightly different background for contrast
            "markdown.code": f"{text_color} on {bg_color}",
            "markdown.code_block": f"on {bg_color}",
            # Headings: use primary text color with emphasis
            "markdown.h1": f"bold underline {text_color}",
            "markdown.h2": f"bold {text_color}",
            "markdown.h3": f"bold {text_color}",
            "markdown.h4": f"italic {text_color}",
            "markdown.h5": f"italic {text_color}",
            "markdown.h6": f"dim italic {text_color}",
            # Links: use primary text color with underline
            "markdown.link": f"underline {text_color}",
            "markdown.link_url": f"dim underline {text_color}",
            # Block quotes: dimmed text
            "markdown.block_quote": f"dim italic {text_color}",
            # Table: dim borders, bold headers
            "markdown.table.border": f"dim {text_color}",
            "markdown.table.header": f"bold {text_color}",
            # Horizontal rules: very dim
            "markdown.hr": f"dim {text_color}",
        })

        self.app.console.push_theme(markdown_theme)

    def render_line(self, y: int) -> Strip:
        """Line API: render a single line at virtual position y."""
        scroll_x, scroll_y = self.scroll_offset
        actual_y = scroll_y + y
        width = self._content_width

        if actual_y >= self._total_lines:
            return Strip.blank(width, self.rich_style)

        key = (actual_y, scroll_x, width, self._widest_line)
        if key in self._line_cache:
            return self._line_cache[key].apply_style(self.rich_style)

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

        # Apply base style
        strip = strip.apply_style(self.rich_style)

        self._line_cache[key] = strip

        # Track which turn this cache key belongs to (for selective invalidation)
        turn_idx = turn.turn_index
        if turn_idx not in self._cache_keys_by_turn:
            self._cache_keys_by_turn[turn_idx] = set()
        self._cache_keys_by_turn[turn_idx].add(key)

        return strip

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
        )
        # re_render clears _pending_filter_snapshot

        # Schedule offset recalculation after current render pass completes.
        # We can't recalculate inline because it invalidates the line cache
        # and virtual_size while render_line() is still iterating.
        self.call_later(self._deferred_offset_recalc, turn.turn_index)

    def _deferred_offset_recalc(self, from_turn_index: int):
        """Recalculate offsets after a lazy re-render, then refresh display.

        Captures and restores turn-level anchor to prevent viewport drift
        when off-viewport turns lazily re-render and shift line offsets.
        """
        anchor = self._find_viewport_anchor() if not self._follow_mode else None
        self._recalculate_offsets_from(from_turn_index)
        if anchor is not None:
            self._restore_anchor(anchor)
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

        strips, block_strip_map = cc_dump.tui.rendering.render_turn_to_strips(
            blocks, filters, console, width, block_cache=self._block_strip_cache
        )
        td = TurnData(
            turn_index=len(self._turns),
            blocks=blocks,
            strips=strips,
            block_strip_map=block_strip_map,
        )
        td._widest_strip = _compute_widest(strips)
        td.compute_relevant_keys()
        from cc_dump.formatting import Level

        td._last_filter_snapshot = {
            k: filters.get(k, Level.FULL) for k in td.relevant_filter_keys
        }
        self._turns.append(td)
        self._recalculate_offsets()

        if self._follow_mode:
            self._scrolling_programmatically = True
            self.scroll_end(animate=False, immediate=False, x_axis=False)
            self._scrolling_programmatically = False

    # ─── Sprint 6: Inline streaming ──────────────────────────────────────────

    def begin_streaming_turn(self):
        """Create an empty streaming TurnData at end of turns list.

        Idempotent - if a streaming turn already exists, does nothing.
        """
        # Check if we already have a streaming turn
        if self._turns and self._turns[-1].is_streaming:
            return

        td = TurnData(
            turn_index=len(self._turns),
            blocks=[],
            strips=[],
            is_streaming=True,
        )
        self._turns.append(td)
        self._recalculate_offsets()

    def _render_single_block_to_strips(
        self, renderable, console, width: int
    ) -> list:
        """Render a single Rich renderable (Text, Markdown, etc.) to Strip list.

        Helper for rendering individual blocks during streaming.
        """
        from rich.segment import Segment
        from textual.strip import Strip

        render_options = console.options.update_width(width)
        segments = console.render(renderable, render_options)
        lines = list(Segment.split_lines(segments))
        if not lines:
            return []

        block_strips = Strip.from_lines(lines)
        for strip in block_strips:
            strip.adjust_cell_length(width)
        return block_strips

    def _refresh_streaming_delta(self, td: TurnData):
        """Re-render delta buffer portion only.

        Replaces strips[_stable_strip_count:] with freshly rendered delta text.
        Streaming deltas are always ASSISTANT category, so render as Markdown.
        """
        if not td._text_delta_buffer:
            # No delta text - trim to stable strips only
            td.strips = td.strips[: td._stable_strip_count]
            td._widest_strip = _compute_widest(td.strips)
            return

        width = self._content_width if self._size_known else self._last_width
        console = self.app.console

        # Combine delta buffer into Markdown (streaming deltas are ASSISTANT)
        combined_text = "".join(td._text_delta_buffer)
        renderable = Markdown(combined_text, code_theme="github-dark")

        # Render to strips
        delta_strips = self._render_single_block_to_strips(renderable, console, width)

        # Replace delta tail
        td.strips = td.strips[: td._stable_strip_count] + delta_strips
        td._widest_strip = _compute_widest(td.strips)

    def _flush_streaming_delta(self, td: TurnData, filters: dict):
        """Convert delta buffer to stable strips.

        If delta buffer has content, consolidate it into stable strips
        and advance _stable_strip_count. Streaming deltas are ASSISTANT, use Markdown.
        """
        if not td._text_delta_buffer:
            return

        width = self._content_width if self._size_known else self._last_width
        console = self.app.console

        # Render delta buffer to strips as Markdown (streaming deltas are ASSISTANT)
        combined_text = "".join(td._text_delta_buffer)
        renderable = Markdown(combined_text, code_theme="github-dark")
        delta_strips = self._render_single_block_to_strips(renderable, console, width)

        # Replace delta tail with stable strips
        td.strips = td.strips[: td._stable_strip_count] + delta_strips
        td._widest_strip = _compute_widest(td.strips)

        # Advance stable boundary
        td._stable_strip_count = len(td.strips)

        # Clear delta buffer
        td._text_delta_buffer.clear()

    def _update_streaming_size(self, td: TurnData):
        """Update total_lines and virtual_size for streaming turn.

        Delegates to _recalculate_offsets() to avoid code duplication.
        """
        self._recalculate_offsets()

    def _handle_text_delta_block(self, block, td):
        """Handle TextDeltaBlock - buffer and re-render tail."""
        td._text_delta_buffer.append(block.text)
        self._refresh_streaming_delta(td)

    def _handle_non_delta_block(self, block, td, filters):
        """Handle non-delta blocks - flush, render, and append to stable strips."""
        # Flush delta buffer first
        self._flush_streaming_delta(td, filters)

        # Render this block
        rendered = cc_dump.tui.rendering.render_block(block)
        if rendered is not None:
            width = self._content_width if self._size_known else self._last_width
            console = self.app.console
            new_strips = self._render_single_block_to_strips(rendered, console, width)

            # Add to stable strips
            td.strips.extend(new_strips)
            td._widest_strip = _compute_widest(td.strips)

            # Update block_strip_map (track where this block starts)
            block_idx = len(td.blocks) - 1
            td.block_strip_map[block_idx] = td._stable_strip_count

            # Advance stable boundary
            td._stable_strip_count = len(td.strips)

    # [LAW:dataflow-not-control-flow] Streaming block dispatch table
    # Use string keys for hot-reload safety (isinstance fails across reloads)
    def _get_streaming_block_handler(self, block_type_name: str):
        """Get handler for a streaming block type."""
        if block_type_name == "TextDeltaBlock":
            return self._handle_text_delta_block
        else:
            return self._handle_non_delta_block

    def append_streaming_block(self, block, filters: dict = None):
        """Append a block to the streaming turn.

        Handles TextDeltaBlock (buffer + render delta tail) and
        non-delta blocks (flush + render + stable prefix).

        During streaming, only USER and ASSISTANT category blocks are rendered.
        All blocks are stored in td.blocks for finalization.
        """
        if filters is None:
            filters = self._last_filters

        # Ensure streaming turn exists
        if not self._turns or not self._turns[-1].is_streaming:
            self.begin_streaming_turn()

        td = self._turns[-1]

        # Add block to blocks list (always store for finalization)
        td.blocks.append(block)

        # Filter: only render USER and ASSISTANT content during streaming
        # [LAW:dataflow-not-control-flow] Category resolved via lookup, not control flow
        from cc_dump.formatting import Category
        block_category = cc_dump.tui.rendering.get_category(block)
        if block_category not in (Category.USER, Category.ASSISTANT, None):
            # Skip rendering (but keep in blocks for finalize). None = always visible (ErrorBlock etc)
            return

        # [LAW:dataflow-not-control-flow] Dispatch via handler lookup
        block_type_name = type(block).__name__
        handler = self._get_streaming_block_handler(block_type_name)

        # TextDeltaBlock takes (block, td), others take (block, td, filters)
        if block_type_name == "TextDeltaBlock":
            handler(block, td)
        else:
            handler(block, td, filters)

        # Update virtual size
        self._update_streaming_size(td)

        # Auto-scroll if follow mode
        if self._follow_mode:
            self._scrolling_programmatically = True
            self.scroll_end(animate=False, immediate=False, x_axis=False)
            self._scrolling_programmatically = False

    def finalize_streaming_turn(self) -> list:
        """Finalize the streaming turn.

        Consolidates TextDeltaBlocks → TextContentBlocks, full re-render
        from consolidated blocks, marks turn as non-streaming.

        Returns the consolidated block list.
        """
        # Import the CURRENT TextContentBlock class (post-reload) for creating new blocks
        from cc_dump.formatting import TextContentBlock

        if not self._turns or not self._turns[-1].is_streaming:
            return []

        td = self._turns[-1]

        # Consolidate consecutive TextDeltaBlock runs into TextContentBlock
        # Use class name for hot-reload safety
        from cc_dump.formatting import Category

        consolidated = []
        delta_buffer = []

        for block in td.blocks:
            if type(block).__name__ == "TextDeltaBlock":
                delta_buffer.append(block.text)
            else:
                # Flush accumulated deltas as a single TextContentBlock with ASSISTANT category
                if delta_buffer:
                    combined_text = "".join(delta_buffer)
                    consolidated.append(
                        TextContentBlock(text=combined_text, category=Category.ASSISTANT)
                    )
                    delta_buffer.clear()
                # Add the non-delta block
                consolidated.append(block)

        # Flush any remaining deltas
        if delta_buffer:
            combined_text = "".join(delta_buffer)
            consolidated.append(
                TextContentBlock(text=combined_text, category=Category.ASSISTANT)
            )

        # Full re-render from consolidated blocks
        width = self._content_width if self._size_known else self._last_width
        console = self.app.console
        strips, block_strip_map = cc_dump.tui.rendering.render_turn_to_strips(
            consolidated,
            self._last_filters,
            console,
            width,
            block_cache=self._block_strip_cache,
        )

        # Update turn data
        td.blocks = consolidated
        td.strips = strips
        td.block_strip_map = block_strip_map
        td._widest_strip = _compute_widest(td.strips)
        td.is_streaming = False
        td._text_delta_buffer.clear()
        td._stable_strip_count = 0

        # Compute relevant filter keys
        td.compute_relevant_keys()
        from cc_dump.formatting import Level

        td._last_filter_snapshot = {
            k: self._last_filters.get(k, Level.FULL) for k in td.relevant_filter_keys
        }

        # Recalculate offsets
        self._recalculate_offsets()

        return consolidated

    # ─────────────────────────────────────────────────────────────────────────

    def _find_viewport_anchor(self) -> tuple[int, int] | None:
        """Find turn at top of viewport and offset within it (turn-level anchor for filter toggles)."""
        if not self._turns:
            return None
        scroll_y = int(self.scroll_offset.y)
        turn = self._find_turn_for_line(scroll_y)
        if turn is None:
            return None
        offset_within = scroll_y - turn.line_offset
        return (turn.turn_index, offset_within)

    def _restore_anchor(self, anchor: tuple[int, int]):
        """Restore scroll position to anchor turn after re-render (turn-level anchor for filter toggles)."""
        turn_index, offset_within = anchor
        if turn_index < len(self._turns):
            turn = self._turns[turn_index]
            if turn.line_count > 0:
                target_y = turn.line_offset + min(offset_within, turn.line_count - 1)
                self.scroll_to(y=target_y, animate=False)
                return
        # Anchor turn invisible — find nearest visible
        for delta in range(1, len(self._turns)):
            for idx in [turn_index + delta, turn_index - delta]:
                if 0 <= idx < len(self._turns) and self._turns[idx].line_count > 0:
                    self.scroll_to(y=self._turns[idx].line_offset, animate=False)
                    return

    def rerender(self, filters: dict, search_ctx=None):
        """Re-render affected turns in place. Preserves scroll position.

        Single strategy: capture turn-level anchor before re-render,
        restore after. Stateless — no state persists between calls.

        Args:
            filters: Current filter state (category name -> Level)
            search_ctx: Optional SearchContext for highlighting matches
        """
        self._last_filters = filters

        if self._pending_restore is not None:
            self._rebuild_from_state(filters)
            return

        # Capture turn-level anchor BEFORE re-render (skip if follow mode)
        anchor = self._find_viewport_anchor() if not self._follow_mode else None

        width = self._content_width if self._size_known else self._last_width
        console = self.app.console

        # Viewport-only re-rendering: only process visible turns + buffer
        vp_start, vp_end = self._viewport_turn_range()

        # When search is active, force re-render all viewport turns
        force = search_ctx is not None

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
                ):
                    if first_changed is None:
                        first_changed = idx
            else:
                # Off-viewport turn: defer re-render, mark pending
                from cc_dump.formatting import Level

                snapshot = {
                    k: filters.get(k, Level.FULL) for k in td.relevant_filter_keys
                }
                if snapshot != td._last_filter_snapshot:
                    td._pending_filter_snapshot = snapshot

        if first_changed is not None:
            self._recalculate_offsets_from(first_changed)

        # Single restore: turn-level anchor only
        if anchor is not None:
            self._restore_anchor(anchor)

    def _rebuild_from_state(self, filters: dict):
        """Rebuild from restored state."""
        state = self._pending_restore
        self._pending_restore = None
        self._turns.clear()
        for block_list in state.get("all_blocks", []):
            self.add_turn(block_list, filters)

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
                td.strips, td.block_strip_map = (
                    cc_dump.tui.rendering.render_turn_to_strips(
                        td.blocks,
                        self._last_filters,
                        console,
                        width,
                        block_cache=self._block_strip_cache,
                    )
                )
                td._widest_strip = _compute_widest(td.strips)
            self._recalculate_offsets()

    # ─── Sprint 2: Follow mode ───────────────────────────────────────────────

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        """Detect scroll position changes from ALL sources.

        CRITICAL: Must call super() to preserve scrollbar sync and refresh.
        CRITICAL: Signature is (old_value, new_value), not (value).
        """
        super().watch_scroll_y(old_value, new_value)
        if self._scrolling_programmatically:
            return
        if self.is_vertical_scroll_end:
            self._follow_mode = True
        else:
            self._follow_mode = False

    def toggle_follow(self):
        """Toggle follow mode."""
        self._follow_mode = not self._follow_mode
        if self._follow_mode:
            self._scrolling_programmatically = True
            self.scroll_end(animate=False)
            self._scrolling_programmatically = False

    def scroll_to_bottom(self):
        """Scroll to bottom and enable follow mode."""
        self._follow_mode = True
        self._scrolling_programmatically = True
        self.scroll_end(animate=False)
        self._scrolling_programmatically = False

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

        self._follow_mode = False
        self._scrolling_programmatically = True
        self.scroll_to(y=centered_y, animate=False)
        self._scrolling_programmatically = False

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
        """Check if a block was truncated (set by render_turn_to_strips)."""
        return getattr(block, "_expandable", False)

    def on_click(self, event) -> None:
        """Toggle expand on truncated blocks."""
        # event.y is viewport-relative; add scroll offset for content-space
        content_y = int(event.y + self.scroll_offset.y)
        turn = self._find_turn_for_line(content_y)
        if turn is None:
            return

        # Check if click hit an expandable block
        block_idx = self._block_index_at_line(turn, content_y)
        if block_idx is not None and block_idx < len(turn.blocks):
            block = turn.blocks[block_idx]
            if self._is_expandable_block(block):
                self._toggle_block_expand(turn, block_idx)

    def _toggle_block_expand(self, turn: TurnData, block_idx: int):
        """Toggle expand state for a single block and re-render its turn."""
        from cc_dump.formatting import Level

        block = turn.blocks[block_idx]

        # [LAW:dataflow-not-control-flow] Coalesce None to default, then toggle
        cat = cc_dump.tui.rendering.get_category(block)
        filter_value = self._last_filters.get(cat.value, Level.FULL) if cat else Level.FULL
        # _last_filters stores (Level, bool) tuples or bare Level values
        if isinstance(filter_value, tuple):
            level, category_expanded = filter_value
        else:
            level = filter_value
            category_expanded = cc_dump.tui.rendering.DEFAULT_EXPANDED[level]

        # Coalesce: treat None as default
        current = block.expanded if block.expanded is not None else category_expanded

        # Toggle
        new_value = not current

        # Store override (None if matches default)
        block.expanded = None if new_value == category_expanded else new_value

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
            )
            self._recalculate_offsets()

    # ─── State management ────────────────────────────────────────────────────

    def get_state(self) -> dict:
        """Extract state for hot-reload preservation.

        Preserves streaming turn state including blocks, delta buffer, and is_streaming flag.
        """
        all_blocks = []
        streaming_states = []

        for td in self._turns:
            all_blocks.append(td.blocks)
            if td.is_streaming:
                streaming_states.append(
                    {
                        "turn_index": td.turn_index,
                        "text_delta_buffer": list(td._text_delta_buffer),
                        "stable_strip_count": td._stable_strip_count,
                    }
                )

        return {
            "all_blocks": all_blocks,
            "follow_mode": self._follow_mode,
            "turn_count": len(self._turns),
            "streaming_states": streaming_states,
        }

    def restore_state(self, state: dict):
        """Restore state from a previous instance.

        Restores streaming turn state and re-renders from preserved blocks.
        """
        self._pending_restore = state
        self._follow_mode = state.get("follow_mode", True)

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

        all_blocks = state.get("all_blocks", [])
        streaming_states = state.get("streaming_states", [])
        streaming_by_index = {s["turn_index"]: s for s in streaming_states}

        for turn_idx, block_list in enumerate(all_blocks):
            if turn_idx in streaming_by_index:
                # Restore as streaming turn
                s = streaming_by_index[turn_idx]
                width = self._content_width if self._size_known else self._last_width
                console = self.app.console

                # Render blocks to get initial strips
                strips, block_strip_map = cc_dump.tui.rendering.render_turn_to_strips(
                    block_list,
                    filters,
                    console,
                    width,
                    block_cache=self._block_strip_cache,
                )

                td = TurnData(
                    turn_index=turn_idx,
                    blocks=block_list,
                    strips=strips,
                    block_strip_map=block_strip_map,
                    is_streaming=True,
                    _text_delta_buffer=s["text_delta_buffer"],
                    _stable_strip_count=s["stable_strip_count"],
                )
                self._turns.append(td)

                # Re-render streaming delta to update display
                self._refresh_streaming_delta(td)
            else:
                # Regular completed turn
                self.add_turn(block_list, filters)

        self._recalculate_offsets()


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
        Token counts come from database via refresh_from_db().
        """
        if "requests" in kwargs:
            self.request_count = kwargs["requests"]
        if "model" in kwargs and kwargs["model"]:
            self.models_seen.add(kwargs["model"])

        # No longer accumulating token counts here - they come from DB

    def refresh_from_db(self, db_path: str, session_id: str, current_turn: dict = None):
        """Refresh token counts from database.

        Args:
            db_path: Path to SQLite database
            session_id: Session identifier
            current_turn: Optional dict with in-progress turn data to merge for real-time display
        """
        if not db_path or not session_id:
            # No database - show only in-memory fields
            self._refresh_display(0, 0, 0, 0)
            return

        stats = cc_dump.db_queries.get_session_stats(db_path, session_id, current_turn)
        self._refresh_display(
            stats["input_tokens"],
            stats["output_tokens"],
            stats["cache_read_tokens"],
            stats["cache_creation_tokens"],
        )

    def _refresh_display(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_creation_tokens: int,
    ):
        """Rebuild the display text."""
        text = cc_dump.tui.panel_renderers.render_stats_panel(
            self.request_count,
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_creation_tokens,
            self.models_seen,
        )
        self.update(text)

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
        # Trigger display refresh (will need DB query to get token counts)
        self._refresh_display(0, 0, 0, 0)


class ToolEconomicsPanel(Static):
    """Panel showing per-tool token usage aggregates.

    Queries database as single source of truth.
    Supports two view modes:
    - Aggregate (default): one row per tool (all models combined)
    - Breakdown (Ctrl+M): separate rows per (tool, model) combination
    """

    def __init__(self):
        super().__init__("")
        self._breakdown_mode = False  # Default to aggregate view
        self._db_path = None
        self._session_id = None

    def refresh_from_db(self, db_path: str, session_id: str):
        """Refresh panel data from database.

        Args:
            db_path: Path to SQLite database
            session_id: Session identifier
        """
        # Store for use in toggle_breakdown
        self._db_path = db_path
        self._session_id = session_id

        if not db_path or not session_id:
            self._refresh_display([])
            return

        # Query tool economics with real tokens and cache attribution
        rows = cc_dump.db_queries.get_tool_economics(
            db_path, session_id, group_by_model=self._breakdown_mode
        )
        self._refresh_display(rows)

    def toggle_breakdown(self):
        """Toggle between aggregate and breakdown view modes."""
        self._breakdown_mode = not self._breakdown_mode
        # Re-query with new mode
        if self._db_path and self._session_id:
            self.refresh_from_db(self._db_path, self._session_id)

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

    Queries database as single source of truth.
    """

    def __init__(self):
        super().__init__("")

    def refresh_from_db(self, db_path: str, session_id: str):
        """Refresh panel data from database.

        Args:
            db_path: Path to SQLite database
            session_id: Session identifier
        """
        if not db_path or not session_id:
            self._refresh_display([])
            return

        # Query turn timeline from database
        turn_data = cc_dump.db_queries.get_turn_timeline(db_path, session_id)

        # Reconstruct TurnBudget objects from database data
        budgets = []
        for row in turn_data:
            # Parse request JSON to compute budget estimates
            request_json = row["request_json"]
            request_body = json.loads(request_json) if request_json else {}

            budget = cc_dump.analysis.compute_turn_budget(request_body)

            # Fill in actual token counts from database
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

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {}  # No state to preserve - queries DB on demand

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self._refresh_display([])


class FilterStatusBar(Static):
    """Status bar showing which filters are currently active with colored indicators."""

    def __init__(self):
        # Initialize with placeholder text so widget is visible
        super().__init__("Active: (initializing...)")

    def update_filters(self, filters: dict):
        """Update the status bar to show active filters with level indicators.

        Args:
            filters: Dict with filter states (category name -> Level int)
        """
        from cc_dump.formatting import Level

        _LEVEL_ICONS = {
            Level.EXISTENCE: "\u00b7",
            Level.SUMMARY: "\u25d0",
            Level.FULL: "\u25cf",
        }

        p = cc_dump.palette.PALETTE
        categories = [
            ("1", "Headers", "headers"),
            ("2", "User", "user"),
            ("3", "Assistant", "assistant"),
            ("4", "Tools", "tools"),
            ("5", "System", "system"),
            ("6", "Budget", "budget"),
            ("7", "Metadata", "metadata"),
        ]

        text = Text()
        for i, (key, name, cat_name) in enumerate(categories):
            level = filters.get(cat_name, Level.FULL)
            if not isinstance(level, Level):
                level = Level(level)
            color = p.filter_color(cat_name)
            icon = _LEVEL_ICONS.get(level, "\u25cf")
            if i > 0:
                text.append(" ", style="dim")
            text.append(icon, style=f"bold {color}")
            text.append(f"{name}", style=color if level > Level.EXISTENCE else "dim")

        self.update(text)

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {}

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        pass


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

    def log(self, level: str, message: str):
        """Add an application log entry.

        Args:
            level: Log level (DEBUG, INFO, WARNING, ERROR)
            message: Log message
        """
        import datetime

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
def create_conversation_view() -> ConversationView:
    """Create a new ConversationView instance."""
    return ConversationView()


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
