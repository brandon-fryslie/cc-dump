# Sprint: widget-arch - Core Widget Architecture
Generated: 2026-01-29T12:00:00
Updated: 2026-01-29T18:30:00
Confidence: HIGH: 6, MEDIUM: 2, LOW: 0
Status: PARTIALLY READY
Source: EVALUATION-20260129.md

## Sprint Goal
Replace the current clear+re-render ConversationView with a Line API-based virtual rendering system that stores turns as data, renders only visible lines per frame, uses RichLog for streaming, and supports in-place filter re-render without losing scroll position.

## Architecture Revision (from original plan)

### Key Insight from Textual Source Analysis

**RichLog** extends `ScrollView` which uses the **Line API**: content is stored as a flat `list[Strip]` (pre-rendered line segments). `render_line(y)` is called per-visible-line per frame. Only visible lines are ever rendered. This is true virtual rendering.

**ScrollableContainer** with many `Static` children does NOT virtualize — every child participates in layout. With 500+ turns this would degrade.

### Revised Architecture

```
ConversationView (ScrollView — Line API)
  ├── Turn data: list[TurnData]        # blocks + pre-rendered strips per turn
  ├── Line index: turn → line range    # maps turn index to line range in virtual space
  ├── Viewport window: renders only visible lines via render_line(y)
  └── StreamingRichLog (RichLog)       # child for in-progress streaming
```

**Three-layer data model:**
1. **TurnData** — stores `list[FormattedBlock]` (source of truth for re-render) + `list[Strip]` (pre-rendered lines for current filters) + metadata (turn index, turn type)
2. **ConversationView (ScrollView)** — owns `list[TurnData]`, implements `render_line(y)` to look up which turn owns line `y` and return the corresponding Strip. Sets `virtual_size` based on total line count.
3. **StreamingRichLog (RichLog)** — separate widget for in-progress streaming. On `finalize()`, its blocks are converted to a `TurnData` and appended to the ConversationView's data store.

**Why this works:**
- Virtual rendering: only visible lines rendered → O(viewport_height) per frame regardless of conversation length
- Smooth scrolling: line-level granularity, not widget-level. No jumping between turns.
- Filter toggle: re-render affected TurnData strips in place, update virtual_size, restore scroll position. No clear needed.
- Streaming: RichLog handles incremental append natively with its own Line API. On finalize, strips transfer to main store.

## Scope
**Deliverables:**
- TurnData dataclass for per-turn block + strip storage
- ConversationView (ScrollView/Line API) with virtual rendering
- StreamingRichLog (RichLog) for in-progress streaming, replacing on finalize
- BLOCK_FILTER_KEY optimization dict (including RoleBlock -> "system")
- render_blocks -> single Text join helper (for re-rendering turns to strips)
- Updated finish_turn signature in event_handlers.py
- CSS updates
- Hot-reload get_state/restore_state compatibility

## Work Items

### P0 - BLOCK_FILTER_KEY dict in rendering.py
**Confidence**: HIGH
**Dependencies**: None

#### Description
Add a `BLOCK_FILTER_KEY` dict to `rendering.py` mapping each `FormattedBlock` subclass to its controlling filter key (or `None` for always-visible blocks). `RoleBlock` maps to `"system"` because `_render_role()` checks `filters["system"]` for system roles. This is an intentional over-approximation — non-system RoleBlocks will trigger unnecessary re-renders when the system filter changes, but the trade-off is simplicity (type-level mapping) vs correctness (instance-level inspection). The re-render cost per turn is trivial (list of Rich Text objects → Strip conversion), so over-rendering is acceptable.

#### Acceptance Criteria
- [ ] `BLOCK_FILTER_KEY` is defined in `rendering.py` covering all 18+ block types in `BLOCK_RENDERERS`
- [ ] `RoleBlock` maps to `"system"` (not `None`)
- [ ] Unmapped types (`TextContentBlock`, `ImageBlock`, `UnknownTypeBlock`, `ErrorBlock`, `ProxyErrorBlock`, `LogBlock`, `NewlineBlock`) map to `None`
- [ ] All types that check a filter in their renderer function have a matching key in the dict

#### Technical Notes
Enables selective re-render optimization: skip re-rendering a turn when the changed filter key doesn't affect any block type in that turn. The optimization is simple integer comparison on filter snapshots — the cost of over-rendering a turn (re-rendering blocks to strips) is negligible compared to the cost of re-rendering ALL turns on every filter toggle.

---

### P0 - Text-to-Strips rendering helper in rendering.py
**Confidence**: HIGH
**Dependencies**: None

#### Description
Add helpers to convert `list[FormattedBlock]` → `list[Strip]` for a given filter state and console width. This is the bridge between the FormattedBlock IR and the Line API's Strip-based storage.

#### Acceptance Criteria
- [ ] Function `render_turn_to_strips(blocks: list[FormattedBlock], filters: dict, console: Console, width: int) -> list[Strip]` exists in `rendering.py`
- [ ] Renders blocks via existing `render_blocks()`, combines into single `Text`, then renders to `list[Strip]` via `console.render()` + `Segment.split_lines()`
- [ ] Handles text delta blocks by joining their text inline (not as separate writes)
- [ ] Returns empty list when all blocks are filtered out
- [ ] Existing `render_block()` / `render_blocks()` functions unchanged

#### Technical Notes
Use `console.render(combined_text, options.update_width(width))` to get segments, then `Segment.split_lines()` → `Strip.from_lines()`. This mirrors RichLog's internal `write()` logic. The strips include cell-width adjustment for proper scrolling.

---

### P0 - TurnData dataclass in widget_factory.py
**Confidence**: HIGH
**Dependencies**: Text-to-Strips helper

#### Description
Create `TurnData` dataclass that holds per-turn state: the source blocks, pre-rendered strips for current filters, relevant filter keys, and metadata.

#### Acceptance Criteria
- [ ] `TurnData` dataclass with fields: `turn_index: int`, `blocks: list[FormattedBlock]`, `strips: list[Strip]`, `relevant_filter_keys: set[str]`, `line_offset: int` (start line in virtual space)
- [ ] `re_render(filters, console, width)` method that re-renders blocks to strips only if a relevant filter key changed
- [ ] `line_count` property returning `len(self.strips)`

#### Technical Notes
`relevant_filter_keys` is computed once from blocks via `BLOCK_FILTER_KEY`. `re_render()` compares the new filter dict (restricted to relevant keys) against the stored snapshot to skip unnecessary re-renders.

---

### P0 - ConversationView (ScrollView/Line API) in widget_factory.py
**Confidence**: MEDIUM
**Dependencies**: TurnData, Text-to-Strips helper

#### Description
Rewrite `ConversationView` to extend `ScrollView` instead of `RichLog`. Stores turns as `list[TurnData]`. Implements `render_line(y)` to look up which turn owns line `y` and return the corresponding Strip. Maintains same public API: `append_block()`, `finish_turn()`, `rerender()`, `get_state()`, `restore_state()`.

#### Acceptance Criteria
- [ ] `ConversationView(ScrollView)` replaces `ConversationView(RichLog)`
- [ ] `render_line(y)` correctly maps virtual line `y` to the right turn's strip via binary search or offset table
- [ ] `virtual_size` is updated when turns are added or filters change line counts
- [ ] `rerender(filters)` re-renders affected TurnData in place, updates line offsets and virtual_size, preserves scroll position
- [ ] Smooth line-level scrolling (no atomic jumping between turns)
- [ ] Public API backward-compatible with `event_handlers.py` and `app.py`
- [ ] LRU line cache for rendered strips (mirrors RichLog's caching pattern)

#### Unknowns to Resolve
1. **Line offset maintenance**: When a filter toggle changes the strip count of turn N, all subsequent turns' `line_offset` values must be updated. Need to verify this is fast enough for 500+ turns (should be — it's just integer arithmetic).
2. **Width changes on resize**: When the terminal resizes, all strips need re-rendering at the new width. RichLog handles this in `on_resize`. We need the same pattern.

#### Exit Criteria (to reach HIGH confidence)
- [ ] Prototype `render_line(y)` with a small test harness showing correct line lookup
- [ ] Verify resize handling works (strips re-rendered at new width)

#### Technical Notes
- Binary search on `line_offset` to find which turn contains line `y`. Within that turn, `strips[y - turn.line_offset]` gives the strip.
- `_line_cache: LRUCache` keyed by `(line_y, scroll_x, width)` — same pattern as RichLog.
- `_recalculate_offsets()` iterates turns and sets each `line_offset` to the cumulative sum. Called after any turn add/filter change.
- During streaming: `append_block()` delegates to the StreamingRichLog (see next item). The main ConversationView only stores finalized turns.

---

### P0 - StreamingRichLog in widget_factory.py
**Confidence**: MEDIUM
**Dependencies**: ConversationView rewrite

#### Description
Use a **RichLog** instance for the in-progress streaming turn. RichLog already handles incremental `write()` with Line API virtual rendering and delta buffering natively. On `finalize()`, extract the accumulated `FormattedBlock` list, re-render to strips, and append as a `TurnData` to ConversationView's data store.

#### Acceptance Criteria
- [ ] `StreamingRichLog` class (or protocol) wraps a RichLog for streaming
- [ ] `append_block(block, filters)` — for `TextDeltaBlock`, buffers text and periodically calls `richlog.write()`. For other blocks, flushes buffer then writes rendered block.
- [ ] `finalize() -> list[FormattedBlock]` returns accumulated blocks, clears RichLog state
- [ ] RichLog is mounted as a child of a container alongside the ConversationView, shown only during streaming
- [ ] Delta buffering follows the same pattern as current ConversationView (flush before non-delta blocks)

#### Unknowns to Resolve
1. **Layout composition**: ConversationView (ScrollView) and StreamingRichLog (RichLog) need to coexist in the layout. During streaming, the RichLog shows the in-progress response below the finalized conversation. Options: (a) vertical container with both, RichLog docked bottom; (b) ConversationView allocates space for the RichLog at the bottom of its virtual space. Need to test which gives smoother UX.
2. **Scroll coordination**: When follow-mode is on, scrolling needs to track the streaming RichLog's content, not the ConversationView. When follow-mode is off, the user may be scrolled up in the ConversationView while streaming happens below.

#### Exit Criteria (to reach HIGH confidence)
- [ ] Layout approach chosen and tested (vertical container vs embedded)
- [ ] Scroll coordination verified for both follow and non-follow modes

#### Technical Notes
- The simplest layout: `VerticalScroll` container with ConversationView (flex: 1) and StreamingRichLog (height: auto, max-height: 50%). During streaming, RichLog is visible and grows. On finalize, RichLog hides, strips transfer to ConversationView.
- Alternative: ConversationView manages the StreamingRichLog internally. Mount it as a child within the ScrollView. This is trickier because ScrollView uses Line API (no child widgets expected). Prefer the external layout approach.

---

### P1 - Update event_handlers.py routing
**Confidence**: HIGH
**Dependencies**: ConversationView rewrite, StreamingRichLog

#### Description
Update event handlers to route correctly between ConversationView and StreamingRichLog. **Visibility is a view concern, not a lifecycle concern.** `finish_turn()` does not take filters — it creates TurnData with all blocks. Filter application happens via `rerender(filters)` which is called separately by the reactive watchers.

Routing:
- `handle_request`: blocks arrive all at once (non-streaming) → `conv.add_turn(blocks)` directly
- `handle_response_event`: blocks arrive incrementally → `streaming.append_block(block, filters)` (filters only needed for immediate RichLog display)
- `handle_response_done`: `streaming.finalize()` → `conv.add_turn(blocks)`
- `handle_error` / `handle_proxy_error`: single block → `conv.add_turn([block])`

#### Acceptance Criteria
- [ ] `handle_request` calls `conv.add_turn(blocks)` (no streaming involved)
- [ ] `handle_response_event` calls `streaming.append_block(block, filters)`
- [ ] `handle_response_done` calls `blocks = streaming.finalize()` then `conv.add_turn(blocks)`
- [ ] `handle_error` / `handle_proxy_error` call `conv.add_turn([block])`
- [ ] `widgets` dict includes `"streaming"` key
- [ ] `finish_turn()` is removed from ConversationView API (replaced by `add_turn`)

#### Technical Notes
The key principle: turn completion (`add_turn`) and filter application (`rerender`) are independent operations. Turns are created with all blocks. The rendering path consults current filters at render time. This avoids coupling turn lifecycle to filter state — they change at different rates.

---

### P1 - CSS and layout updates
**Confidence**: HIGH
**Dependencies**: ConversationView, StreamingRichLog

#### Description
Update `styles.css` for the new widget architecture. ConversationView becomes a ScrollView. StreamingRichLog needs sizing rules.

#### Acceptance Criteria
- [ ] `ConversationView` CSS: `height: 1fr; overflow-y: scroll;`
- [ ] `StreamingRichLog` (or its container): `height: auto; max-height: 50%; dock: bottom;` when visible
- [ ] Existing panel styles unchanged

---

### P1 - Hot-reload get_state/restore_state
**Confidence**: HIGH
**Dependencies**: ConversationView rewrite

#### Description
Implement state transfer for the new ConversationView. State includes all turn block lists (not strips — strips are re-rendered from blocks on restore).

#### Acceptance Criteria
- [ ] `get_state()` returns: `all_blocks` (list of block lists), `streaming_blocks`, `text_delta_buffer`, `follow_mode`, `turn_count`
- [ ] `restore_state()` stores pending state; `rerender()` rebuilds TurnData from blocks
- [ ] `_replace_all_widgets()` in `app.py` works without modification
- [ ] Re-export new classes from `widgets.py`

## Dependencies
- No external sprint dependencies (Sprint 1)
- Internal: BLOCK_FILTER_KEY + Strips helper → TurnData → ConversationView → StreamingRichLog → event_handlers/CSS/hot-reload

## Risks
- **ScrollView Line API complexity**: Building a custom ScrollView is more work than using ScrollableContainer, but necessary for performance. RichLog's source code provides a clear reference implementation.
- **Streaming layout**: Coordinating two scrollable regions (finalized conversation + streaming response) is the trickiest UX challenge. The vertical container approach is simplest but may have visual seams.
- **Resize re-rendering**: All strips must re-render on terminal resize. For 500+ turns this could cause a brief pause. Mitigation: lazy re-render (only re-render turns whose strips are accessed via `render_line`).
