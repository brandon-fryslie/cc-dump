# Definition of Done: widget-arch
Generated: 2026-01-29T12:00:00
Updated: 2026-01-29T18:30:00
Status: PARTIALLY READY (HIGH: 6, MEDIUM: 2)
Plan: SPRINT-20260129-120000-widget-arch-PLAN.md

## Acceptance Criteria

### BLOCK_FILTER_KEY dict
- [ ] Dict defined in `rendering.py` with all 18+ block types from `BLOCK_RENDERERS`
- [ ] `RoleBlock` maps to `"system"`
- [ ] Types without filter checks map to `None`
- [ ] Every block type that checks a filter in its renderer has a matching non-None key

### Text-to-Strips rendering helpers
- [ ] `combine_rendered_texts(texts: list[Text]) -> Text` exists in `rendering.py`
- [ ] Empty list returns `Text()`; single item returns without wrapping newlines; multi-item joins with `"\n"`
- [ ] `render_turn_to_strips(blocks, filters, console, width) -> list[Strip]` exists
- [ ] Mirrors RichLog's write() pipeline: render → Segment.split_lines → Strip.from_lines → adjust_cell_length
- [ ] Existing `render_block()` / `render_blocks()` unchanged

### TurnData
- [ ] `TurnData` dataclass in `widget_factory.py` with: `turn_index`, `blocks`, `strips`, `relevant_filter_keys`, `line_offset`
- [ ] `re_render(filters, console, width)` only re-renders when relevant filter key changed
- [ ] `line_count` property returns `len(self.strips)`
- [ ] `compute_relevant_keys()` derives keys from blocks via `BLOCK_FILTER_KEY`

### ConversationView (ScrollView/Line API)
- [ ] Extends `ScrollView` (not `RichLog` or `ScrollableContainer`)
- [ ] `render_line(y)` maps virtual line y → turn → strip via binary search on `line_offset`
- [ ] LRU line cache (1024 entries) keyed by `(y, scroll_x, width, widest_line)`
- [ ] `virtual_size` updated on turn add and filter change
- [ ] `add_turn(blocks, filters)` creates TurnData, appends, recalculates offsets
- [ ] `rerender(filters)` re-renders affected TurnData in place, preserves scroll position
- [ ] `on_resize()` re-renders all strips at new width
- [ ] Smooth line-level scrolling — no atomic jumping between turns
- [ ] Performant for 500+ turns (O(viewport_height) per frame, O(log N) per line lookup)
- [ ] Public API: `append_block`, `finish_turn`, `add_turn`, `rerender`, `get_state`, `restore_state`

### StreamingRichLog
- [ ] Extends `RichLog` (leverages native Line API virtual rendering + incremental append)
- [ ] `append_block(block, filters)` buffers TextDeltaBlock text, writes others via `richlog.write()`
- [ ] Delta buffering: flush before non-delta blocks (same pattern as current ConversationView)
- [ ] `finalize() -> list[FormattedBlock]` returns blocks, clears RichLog, hides widget
- [ ] Hidden by default (`display = False`), shown on first `append_block`
- [ ] `get_state()` / `restore_state()` for hot-reload

### event_handlers.py
- [ ] `handle_request` calls `conv.add_turn(blocks, filters)` directly (non-streaming)
- [ ] `handle_response_event` calls `streaming.append_block(block, filters)`
- [ ] `handle_response_done` calls `streaming.finalize()` → `conv.add_turn(blocks, filters)`
- [ ] `handle_error` / `handle_proxy_error` call `conv.add_turn(blocks, filters)` directly
- [ ] `widgets` dict includes `"streaming"` key

### app.py
- [ ] `compose()` yields both ConversationView and StreamingRichLog
- [ ] `_get_streaming()` accessor added
- [ ] `_handle_event_inner` populates `widgets["streaming"]`
- [ ] `_replace_all_widgets` handles StreamingRichLog state

### CSS
- [ ] `ConversationView` has `height: 1fr; border: solid $primary;` (DEFAULT_CSS handles overflow)
- [ ] `StreamingRichLog` has `height: auto; max-height: 50%;`

### Hot-reload
- [ ] `get_state()` returns all turn block lists, follow_mode
- [ ] `restore_state()` + `rerender()` rebuilds TurnData from blocks
- [ ] `_replace_all_widgets()` works for both ConversationView and StreamingRichLog
- [ ] New classes re-exported from `widgets.py`

### Integration
- [ ] Existing PTY integration tests pass (`pytest tests/`)
- [ ] Filter toggles (h/t/s/e/m) update display without scroll position loss
- [ ] Streaming text appears incrementally during active responses
- [ ] Hot-reload of `widget_factory.py` replaces widgets with state preserved
- [ ] Long conversations (100+ turns) scroll smoothly without lag
