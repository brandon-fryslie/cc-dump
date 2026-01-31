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
from rich.style import Style

# Use module-level imports for hot-reload
import cc_dump.analysis
import cc_dump.tui.rendering
import cc_dump.tui.panel_renderers
import cc_dump.db_queries


@dataclass
class TurnData:
    """Pre-rendered turn data for Line API storage."""
    turn_index: int
    blocks: list             # list[FormattedBlock] - source of truth
    strips: list             # list[Strip] - pre-rendered lines
    block_strip_map: dict = field(default_factory=dict)  # block_index → first strip line
    relevant_filter_keys: set = field(default_factory=set)
    line_offset: int = 0     # start line in virtual space
    _last_filter_snapshot: dict = field(default_factory=dict)
    # Streaming fields
    is_streaming: bool = False
    _text_delta_buffer: list = field(default_factory=list)  # list[str] - accumulated delta text
    _stable_strip_count: int = 0  # boundary between stable and delta strips

    @property
    def line_count(self) -> int:
        return len(self.strips)

    def compute_relevant_keys(self):
        """Compute which filter keys affect this turn's blocks."""
        keys = set()
        for block in self.blocks:
            key = cc_dump.tui.rendering.BLOCK_FILTER_KEY.get(type(block))
            if key is not None:
                keys.add(key)
        self.relevant_filter_keys = keys

    def re_render(self, filters: dict, console, width: int) -> bool:
        """Re-render if a relevant filter changed. Returns True if strips changed."""
        snapshot = {k: filters.get(k, False) for k in self.relevant_filter_keys}
        if snapshot == self._last_filter_snapshot:
            return False
        self._last_filter_snapshot = snapshot
        self.strips, self.block_strip_map = cc_dump.tui.rendering.render_turn_to_strips(
            self.blocks, filters, console, width
        )
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
        &:focus {
            background-tint: $foreground 5%;
        }
    }
    """

    _SELECTED_STYLE = Style(bgcolor="grey15")

    def __init__(self):
        super().__init__()
        self._turns: list[TurnData] = []
        self._total_lines: int = 0
        self._widest_line: int = 0
        self._line_cache: LRUCache = LRUCache(1024)
        self._last_filters: dict = {}
        self._last_width: int = 78
        self._follow_mode: bool = True
        self._pending_restore: dict | None = None
        # Saved anchor: set when a filter hides the anchor block, so we
        # can restore to the exact position when the block reappears.
        # Cleared when the saved block becomes visible again.
        self._saved_anchor: tuple[int, int, int] | None = None
        # Sprint 2: selection and programmatic scroll guard
        self._selected_turn: int | None = None
        self._scrolling_programmatically: bool = False

    def _compute_anchor_from_scroll(self) -> tuple[int, int, int] | None:
        """Compute (turn_index, block_index, line_within_block) from current scroll position."""
        if not self._turns:
            return None

        scroll_y = int(self.scroll_offset.y)
        turn = self._find_turn_for_line(scroll_y)
        if turn is None:
            return (self._turns[-1].turn_index, 0, 0) if self._turns else None

        local_y = scroll_y - turn.line_offset
        best_block_idx = 0
        best_strip_start = 0
        for block_idx, strip_start in sorted(turn.block_strip_map.items()):
            if strip_start <= local_y:
                best_block_idx = block_idx
                best_strip_start = strip_start
            else:
                break

        line_within_block = local_y - best_strip_start
        return (turn.turn_index, best_block_idx, line_within_block)

    def render_line(self, y: int) -> Strip:
        """Line API: render a single line at virtual position y."""
        scroll_x, scroll_y = self.scroll_offset
        actual_y = scroll_y + y
        width = self.scrollable_content_region.width

        if actual_y >= self._total_lines:
            return Strip.blank(width, self.rich_style)

        # Cache key includes selection state
        key = (actual_y, scroll_x, width, self._widest_line, self._selected_turn)
        if key in self._line_cache:
            return self._line_cache[key].apply_style(self.rich_style)

        # Binary search for the turn containing this line
        turn = self._find_turn_for_line(actual_y)
        if turn is None:
            return Strip.blank(width, self.rich_style)

        local_y = actual_y - turn.line_offset
        if local_y < len(turn.strips):
            strip = turn.strips[local_y].crop_extend(
                scroll_x, scroll_x + width, self.rich_style
            )
        else:
            strip = Strip.blank(width, self.rich_style)

        # Apply base style
        strip = strip.apply_style(self.rich_style)

        # Apply selection highlight
        if self._selected_turn is not None and self._selected_turn == turn.turn_index:
            strip = strip.apply_style(self._SELECTED_STYLE)

        self._line_cache[key] = strip
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

    def _recalculate_offsets(self):
        """Rebuild line offsets and virtual size."""
        offset = 0
        widest = 0
        for turn in self._turns:
            turn.line_offset = offset
            offset += turn.line_count
            for strip in turn.strips:
                w = strip.cell_length
                if w > widest:
                    widest = w
        self._total_lines = offset
        self._widest_line = max(widest, self._last_width)
        self.virtual_size = Size(self._widest_line, self._total_lines)
        self._line_cache.clear()

    def add_turn(self, blocks: list, filters: dict = None):
        """Add a completed turn from block list."""
        if filters is None:
            filters = self._last_filters
        width = self.scrollable_content_region.width if self._size_known else self._last_width
        console = self.app.console

        strips, block_strip_map = cc_dump.tui.rendering.render_turn_to_strips(
            blocks, filters, console, width
        )
        td = TurnData(
            turn_index=len(self._turns),
            blocks=blocks,
            strips=strips,
            block_strip_map=block_strip_map,
        )
        td.compute_relevant_keys()
        td._last_filter_snapshot = {
            k: filters.get(k, False) for k in td.relevant_filter_keys
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

    def _render_single_block_to_strips(self, text_obj: Text, console, width: int) -> list:
        """Render a single Rich Text object to Strip list.

        Helper for rendering individual blocks during streaming.
        """
        from rich.segment import Segment
        from textual.strip import Strip

        render_options = console.options.update_width(width)
        segments = console.render(text_obj, render_options)
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
        """
        if not td._text_delta_buffer:
            # No delta text - trim to stable strips only
            td.strips = td.strips[:td._stable_strip_count]
            return

        width = self.scrollable_content_region.width if self._size_known else self._last_width
        console = self.app.console

        # Combine delta buffer into single text
        combined_text = "".join(td._text_delta_buffer)
        text_obj = Text(combined_text)

        # Render to strips
        delta_strips = self._render_single_block_to_strips(text_obj, console, width)

        # Replace delta tail
        td.strips = td.strips[:td._stable_strip_count] + delta_strips

    def _flush_streaming_delta(self, td: TurnData, filters: dict):
        """Convert delta buffer to stable strips.

        If delta buffer has content, consolidate it into stable strips
        and advance _stable_strip_count.
        """
        if not td._text_delta_buffer:
            return

        width = self.scrollable_content_region.width if self._size_known else self._last_width
        console = self.app.console

        # Render delta buffer to strips
        combined_text = "".join(td._text_delta_buffer)
        text_obj = Text(combined_text)
        delta_strips = self._render_single_block_to_strips(text_obj, console, width)

        # Replace delta tail with stable strips
        td.strips = td.strips[:td._stable_strip_count] + delta_strips

        # Advance stable boundary
        td._stable_strip_count = len(td.strips)

        # Clear delta buffer
        td._text_delta_buffer.clear()

    def _update_streaming_size(self, td: TurnData):
        """Update total_lines and virtual_size for streaming turn.

        Lighter-weight than full _recalculate_offsets() - only updates
        the streaming turn's contribution to virtual size.
        """
        # Recalculate widest line from all turns
        widest = 0
        for turn in self._turns:
            for strip in turn.strips:
                w = strip.cell_length
                if w > widest:
                    widest = w

        # Recalculate total lines
        offset = 0
        for turn in self._turns:
            turn.line_offset = offset
            offset += turn.line_count

        self._total_lines = offset
        self._widest_line = max(widest, self._last_width)
        self.virtual_size = Size(self._widest_line, self._total_lines)
        self._line_cache.clear()

    def append_streaming_block(self, block, filters: dict = None):
        """Append a block to the streaming turn.

        Handles TextDeltaBlock (buffer + render delta tail) and
        non-delta blocks (flush + render + stable prefix).
        """
        from cc_dump.formatting import TextDeltaBlock

        if filters is None:
            filters = self._last_filters

        # Ensure streaming turn exists
        if not self._turns or not self._turns[-1].is_streaming:
            self.begin_streaming_turn()

        td = self._turns[-1]

        # Add block to blocks list
        td.blocks.append(block)

        if isinstance(block, TextDeltaBlock):
            # Buffer the delta text
            td._text_delta_buffer.append(block.text)

            # Re-render delta tail
            self._refresh_streaming_delta(td)

        else:
            # Non-delta block: flush delta buffer first
            self._flush_streaming_delta(td, filters)

            # Render this block
            rendered = cc_dump.tui.rendering.render_block(block, filters)
            if rendered is not None:
                width = self.scrollable_content_region.width if self._size_known else self._last_width
                console = self.app.console
                new_strips = self._render_single_block_to_strips(rendered, console, width)

                # Add to stable strips
                td.strips.extend(new_strips)

                # Update block_strip_map (track where this block starts)
                block_idx = len(td.blocks) - 1
                td.block_strip_map[block_idx] = td._stable_strip_count

                # Advance stable boundary
                td._stable_strip_count = len(td.strips)

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
        from cc_dump.formatting import TextDeltaBlock, TextContentBlock

        if not self._turns or not self._turns[-1].is_streaming:
            return []

        td = self._turns[-1]

        # Consolidate consecutive TextDeltaBlock runs into TextContentBlock
        consolidated = []
        delta_buffer = []

        for block in td.blocks:
            if isinstance(block, TextDeltaBlock):
                delta_buffer.append(block.text)
            else:
                # Flush accumulated deltas as a single TextContentBlock
                if delta_buffer:
                    combined_text = "".join(delta_buffer)
                    consolidated.append(TextContentBlock(text=combined_text))
                    delta_buffer.clear()
                # Add the non-delta block
                consolidated.append(block)

        # Flush any remaining deltas
        if delta_buffer:
            combined_text = "".join(delta_buffer)
            consolidated.append(TextContentBlock(text=combined_text))

        # Full re-render from consolidated blocks
        width = self.scrollable_content_region.width if self._size_known else self._last_width
        console = self.app.console
        strips, block_strip_map = cc_dump.tui.rendering.render_turn_to_strips(
            consolidated, self._last_filters, console, width
        )

        # Update turn data
        td.blocks = consolidated
        td.strips = strips
        td.block_strip_map = block_strip_map
        td.is_streaming = False
        td._text_delta_buffer.clear()
        td._stable_strip_count = 0

        # Compute relevant filter keys
        td.compute_relevant_keys()
        td._last_filter_snapshot = {
            k: self._last_filters.get(k, False) for k in td.relevant_filter_keys
        }

        # Recalculate offsets
        self._recalculate_offsets()

        return consolidated

    # ─────────────────────────────────────────────────────────────────────────

    def _scroll_to_anchor(self, anchor: tuple[int, int, int]) -> bool:
        """Try to scroll to an anchor position. Returns True if the block was visible."""
        turn_index, block_index, line_within_block = anchor

        if turn_index >= len(self._turns):
            return False

        turn = self._turns[turn_index]

        # Try exact block match
        strip_offset = turn.strip_offset_for_block(block_index)
        if strip_offset is not None:
            target_y = turn.line_offset + strip_offset + min(
                line_within_block,
                max(turn.line_count - strip_offset - 1, 0),
            )
            self.scroll_to(y=target_y, animate=False)
            return True

        # Block is filtered out — fall back to nearest visible block
        if turn.block_strip_map:
            visible = sorted(turn.block_strip_map.keys())
            closest = min(visible, key=lambda bi: abs(bi - block_index))
            target_y = turn.line_offset + turn.block_strip_map[closest]
            self.scroll_to(y=target_y, animate=False)
            return False

        # Entire turn empty — find nearest visible turn
        for delta in range(1, len(self._turns)):
            for idx in [turn_index + delta, turn_index - delta]:
                if 0 <= idx < len(self._turns) and self._turns[idx].line_count > 0:
                    self.scroll_to(y=self._turns[idx].line_offset, animate=False)
                    return False

        return False

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

    def rerender(self, filters: dict):
        """Re-render affected turns in place. Preserves scroll position.

        On each rerender:
        1. If we have a saved anchor (from a previous fallback), check if
           its block is now visible. If so, restore to it exactly.
        2. Otherwise, compute a fresh anchor from current scroll position.
        3. If the anchor block is filtered out, save it for later.
        """
        self._last_filters = filters

        if self._pending_restore is not None:
            self._rebuild_from_state(filters)
            return

        # Capture turn-level anchor before re-render (for scroll position preservation)
        anchor = self._find_viewport_anchor() if not self._follow_mode else None

        # Compute fresh block-level anchor BEFORE re-rendering changes the strips
        fresh_anchor = self._compute_anchor_from_scroll()

        width = self.scrollable_content_region.width if self._size_known else self._last_width
        console = self.app.console
        changed = False
        for td in self._turns:
            # Skip streaming turns during filter changes
            if td.is_streaming:
                continue
            if td.re_render(filters, console, width):
                changed = True

        if changed:
            self._recalculate_offsets()

        # Try saved anchor first (from a previous filter-out).
        # Check even when nothing changed — the saved block may now be
        # visible due to external state changes.
        if self._saved_anchor is not None:
            if self._scroll_to_anchor(self._saved_anchor):
                self._saved_anchor = None
            return

        # Restore turn-level anchor if not in follow mode
        if changed and anchor is not None:
            self._restore_anchor(anchor)

        # No saved anchor — use fresh (only if strips actually changed)
        if changed and fresh_anchor is not None:
            if not self._scroll_to_anchor(fresh_anchor):
                self._saved_anchor = fresh_anchor

    def _rebuild_from_state(self, filters: dict):
        """Rebuild from restored state."""
        state = self._pending_restore
        self._pending_restore = None
        self._turns.clear()
        for block_list in state.get("all_blocks", []):
            self.add_turn(block_list, filters)

    @property
    def _size_known(self) -> bool:
        return self.size.width > 0

    def on_resize(self, event):
        """Re-render all strips at new width."""
        width = self.scrollable_content_region.width
        if width != self._last_width and width > 0:
            self._last_width = width
            console = self.app.console
            for td in self._turns:
                # Skip re-rendering streaming turns on resize
                if td.is_streaming:
                    continue
                td.strips, td.block_strip_map = cc_dump.tui.rendering.render_turn_to_strips(
                    td.blocks, self._last_filters, console, width
                )
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

    # ─── Sprint 2: Turn selection ────────────────────────────────────────────

    def select_turn(self, turn_index: int):
        """Select a turn by index. Refreshes affected line ranges."""
        old_selected = self._selected_turn
        self._selected_turn = turn_index

        # Clear line cache (selection state changes rendered output)
        self._line_cache.clear()

        # Refresh old selection line range
        if old_selected is not None and old_selected < len(self._turns):
            old_turn = self._turns[old_selected]
            if old_turn.line_count > 0:
                self.refresh_lines(old_turn.line_offset, old_turn.line_count)

        # Refresh new selection line range
        if turn_index < len(self._turns):
            new_turn = self._turns[turn_index]
            if new_turn.line_count > 0:
                self.refresh_lines(new_turn.line_offset, new_turn.line_count)

    def deselect(self):
        """Clear selection."""
        if self._selected_turn is not None:
            old = self._selected_turn
            self._selected_turn = None
            self._line_cache.clear()
            if old < len(self._turns):
                turn = self._turns[old]
                if turn.line_count > 0:
                    self.refresh_lines(turn.line_offset, turn.line_count)

    def on_click(self, event) -> None:
        """Select turn at click position."""
        # event.y is viewport-relative; add scroll offset for content-space
        content_y = int(event.y + self.scroll_offset.y)
        turn = self._find_turn_for_line(content_y)
        if turn is not None:
            self.select_turn(turn.turn_index)

    # ─── Sprint 2: Turn navigation ───────────────────────────────────────────

    def _visible_turns(self) -> list[TurnData]:
        """Returns turns with line_count > 0 (not fully filtered out)."""
        return [t for t in self._turns if t.line_count > 0]

    def select_next_turn(self, forward: bool = True):
        """Select next/prev visible turn."""
        visible = self._visible_turns()
        if not visible:
            return
        self._follow_mode = False

        if self._selected_turn is None:
            # Nothing selected — pick first or last
            target = visible[0] if forward else visible[-1]
        else:
            # Find current position in visible list
            current_idx = None
            for i, t in enumerate(visible):
                if t.turn_index == self._selected_turn:
                    current_idx = i
                    break
            if current_idx is None:
                target = visible[0] if forward else visible[-1]
            else:
                next_idx = current_idx + (1 if forward else -1)
                next_idx = max(0, min(next_idx, len(visible) - 1))
                target = visible[next_idx]

        self.select_turn(target.turn_index)
        self.scroll_to(y=target.line_offset, animate=False)

    def next_tool_turn(self, forward: bool = True):
        """Select next/prev turn containing tool blocks."""
        from cc_dump.formatting import ToolUseBlock, ToolResultBlock, StreamToolUseBlock
        tool_types = (ToolUseBlock, ToolResultBlock, StreamToolUseBlock)

        visible = self._visible_turns()
        tool_turns = [t for t in visible if any(isinstance(b, tool_types) for b in t.blocks)]
        if not tool_turns:
            return
        self._follow_mode = False

        if self._selected_turn is None:
            target = tool_turns[0] if forward else tool_turns[-1]
        else:
            if forward:
                later = [t for t in tool_turns if t.turn_index > self._selected_turn]
                target = later[0] if later else tool_turns[0]
            else:
                earlier = [t for t in tool_turns if t.turn_index < self._selected_turn]
                target = earlier[-1] if earlier else tool_turns[-1]

        self.select_turn(target.turn_index)
        self.scroll_to(y=target.line_offset, animate=False)

    def jump_to_first(self):
        """Select first visible turn."""
        visible = self._visible_turns()
        if visible:
            self._follow_mode = False
            self.select_turn(visible[0].turn_index)
            self.scroll_to(y=visible[0].line_offset, animate=False)

    def jump_to_last(self):
        """Select last visible turn and re-enable follow mode."""
        visible = self._visible_turns()
        if visible:
            self.select_turn(visible[-1].turn_index)
            self._follow_mode = True
            self._scrolling_programmatically = True
            self.scroll_end(animate=False)
            self._scrolling_programmatically = False

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
                streaming_states.append({
                    "turn_index": td.turn_index,
                    "text_delta_buffer": list(td._text_delta_buffer),
                    "stable_strip_count": td._stable_strip_count,
                })

        return {
            "all_blocks": all_blocks,
            "follow_mode": self._follow_mode,
            "selected_turn": self._selected_turn,
            "turn_count": len(self._turns),
            "streaming_states": streaming_states,
        }

    def restore_state(self, state: dict):
        """Restore state from a previous instance.

        Restores streaming turn state and re-renders from preserved blocks.
        """
        self._pending_restore = state
        self._follow_mode = state.get("follow_mode", True)
        self._selected_turn = state.get("selected_turn", None)

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
                width = self.scrollable_content_region.width if self._size_known else self._last_width
                console = self.app.console

                # Render blocks to get initial strips
                strips, block_strip_map = cc_dump.tui.rendering.render_turn_to_strips(
                    block_list, filters, console, width
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

    def _refresh_display(self, input_tokens: int, output_tokens: int,
                        cache_read_tokens: int, cache_creation_tokens: int):
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

        # Query tool invocations from database
        invocations = cc_dump.db_queries.get_tool_invocations(db_path, session_id)

        # Aggregate using existing analysis function
        aggregates = cc_dump.analysis.aggregate_tools(invocations)

        self._refresh_display(aggregates)

    def _refresh_display(self, aggregates: list[cc_dump.analysis.ToolAggregates]):
        """Rebuild the economics table."""
        text = cc_dump.tui.panel_renderers.render_economics_panel(aggregates)
        self.update(text)

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {}  # No state to preserve - queries DB on demand

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
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
        """Update the status bar to show active filters.

        Args:
            filters: Dict with filter states (headers, tools, system, expand, metadata)
        """

        # Filter names and their colors (matching FILTER_INDICATORS in rendering.py)
        filter_info = [
            ("h", "Headers", "cyan", filters.get("headers", False)),
            ("t", "Tools", "blue", filters.get("tools", False)),
            ("s", "System", "yellow", filters.get("system", False)),
            ("e", "Context", "green", filters.get("expand", False)),
            ("m", "Metadata", "magenta", filters.get("metadata", False)),
        ]

        text = Text()
        text.append("Active: ", style="dim")

        active_filters = [(key, name, color) for key, name, color, active in filter_info if active]

        if not active_filters:
            text.append("none", style="dim")
        else:
            for i, (key, name, color) in enumerate(active_filters):
                if i > 0:
                    text.append(" ", style="dim")
                # Add colored indicator bar
                text.append("▌", style=f"bold {color}")
                text.append(f"{name}", style=color)

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

        # Color-code by level
        if level == "ERROR":
            log_text.append(f"{level:7s} ", style="bold red")
        elif level == "WARNING":
            log_text.append(f"{level:7s} ", style="bold yellow")
        elif level == "INFO":
            log_text.append(f"{level:7s} ", style="bold cyan")
        else:  # DEBUG
            log_text.append(f"{level:7s} ", style="dim")

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


