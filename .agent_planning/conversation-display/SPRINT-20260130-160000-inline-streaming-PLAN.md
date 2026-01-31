# Sprint: inline-streaming - Eliminate StreamingRichLog, Render Streaming Inline
Generated: 2026-01-30T16:00:00
Confidence: HIGH: 5, MEDIUM: 2, LOW: 0
Status: PARTIALLY READY

## Sprint Goal
Remove the separate StreamingRichLog widget and render streaming content directly inside ConversationView using the Line API, so streaming appears as a normal part of the conversation.

## Architecture Decision: TextDelta Rendering Strategy

TextDeltaBlock tokens arrive at ~50-100/sec. Full turn re-render per token is too expensive.

**Approach: Buffered append with stable prefix.**

- Streaming TurnData has two strip regions: a "stable" prefix (non-delta blocks, rendered once) and a "delta tail" (current text buffer, re-rendered on each delta).
- `_stable_strip_count` marks the boundary.
- On TextDeltaBlock: append to buffer, re-render only the delta tail.
- On non-TextDeltaBlock: flush buffer into stable strips, render new block, advance stable prefix.
- On finalize: consolidate TextDeltaBlocks → TextContentBlocks, full re-render.

## Work Items

### P0 [HIGH] TurnData streaming fields
**Dependencies**: None

Add to TurnData dataclass:
- `is_streaming: bool = False`
- `_text_delta_buffer: list[str]` — accumulates delta text
- `_stable_strip_count: int = 0` — boundary between stable and delta strips

#### Acceptance Criteria
- [ ] TurnData can be constructed with `is_streaming=True`
- [ ] Fields initialized correctly, non-streaming turns unaffected

---

### P0 [HIGH] ConversationView.begin_streaming_turn()
**Dependencies**: TurnData streaming fields

Creates an empty streaming TurnData at end of `_turns`.

#### Acceptance Criteria
- [ ] New empty turn with `is_streaming=True` appended to `_turns`
- [ ] `_recalculate_offsets()` called (safe with 0 strips)
- [ ] Idempotent — second call is a no-op if streaming turn exists

---

### P0 [HIGH] ConversationView.append_streaming_block()
**Dependencies**: begin_streaming_turn, TurnData streaming fields

Core method replacing StreamingRichLog.append_block(). Handles:
- TextDeltaBlock: buffer text, re-render delta tail only (`strips[_stable_strip_count:]`)
- Non-TextDeltaBlock: flush delta buffer into stable strips, render new block, extend stable prefix
- Auto-scroll if follow mode
- Update virtual_size without full _recalculate_offsets()

Helpers:
- `_refresh_streaming_delta(td)` — re-render delta buffer portion only
- `_flush_streaming_delta(td, filters)` — convert buffer to stable strips
- `_render_single_block_to_strips(text_obj, console, width)` — render one Rich Text to Strip list
- `_update_streaming_size(td)` — update total_lines and virtual_size for streaming turn only

#### Acceptance Criteria
- [ ] TextDeltaBlock tokens accumulate in buffer and render incrementally
- [ ] Non-delta blocks flush buffer and render their own strips
- [ ] Follow mode auto-scrolls after each append
- [ ] virtual_size grows as strips are added
- [ ] Line cache cleared on streaming updates
- [ ] Filters respected for non-delta blocks

---

### P0 [HIGH] ConversationView.finalize_streaming_turn()
**Dependencies**: append_streaming_block

Replaces StreamingRichLog.finalize(). Consolidates TextDeltaBlocks → TextContentBlocks, full re-render from consolidated blocks, marks turn as non-streaming.

#### Acceptance Criteria
- [ ] TextDeltaBlocks consolidated into TextContentBlocks
- [ ] Turn fully re-rendered from consolidated blocks
- [ ] `is_streaming` set to False
- [ ] `block_strip_map` populated (enables scroll anchoring)
- [ ] `compute_relevant_keys()` called
- [ ] `_recalculate_offsets()` called
- [ ] Returns consolidated block list

---

### P0 [HIGH] Update event handlers
**Dependencies**: All ConversationView streaming methods

Modify event_handlers.py to route through ConversationView:
- `handle_response_headers` → `conv.begin_streaming_turn()` + `conv.append_streaming_block()`
- `handle_response_event` → `conv.append_streaming_block()` (begin_streaming_turn if not started)
- `handle_response_done` → `conv.finalize_streaming_turn()` (no more `streaming.finalize()` + `conv.add_turn()`)

Remove all `widgets["streaming"]` references.

#### Acceptance Criteria
- [ ] All streaming events route through ConversationView methods
- [ ] No references to `streaming` widget in event handlers
- [ ] Response headers appear inline in streaming turn
- [ ] response_done finalizes correctly
- [ ] Token tracking (current_turn_usage) still works

---

### P1 [MEDIUM] Filter interaction during streaming
**Dependencies**: append_streaming_block

When user toggles a filter mid-stream, `rerender()` iterates all turns. The streaming turn is actively being built — re-rendering it from blocks while streaming would conflict with the delta buffer approach.

#### Acceptance Criteria
- [ ] Filter toggle mid-stream doesn't crash or corrupt streaming turn
- [ ] Streaming turn either skips re-render (guard: `if td.is_streaming: continue`) or handles it correctly
- [ ] After finalize, filter changes re-render the completed turn normally

#### Unknowns to Resolve
1. Skip vs. handle: Should we skip re-rendering the streaming turn on filter toggle, or fully re-render it (flush delta, re-render all blocks, resume streaming)?
   - Skip is simpler and safer
   - Full re-render means filters take effect immediately on streaming content

#### Exit Criteria
- [ ] Decision made: skip or re-render
- [ ] Implementation verified with mid-stream filter toggle

---

### P1 [MEDIUM] Hot-reload and removal of StreamingRichLog
**Dependencies**: All streaming methods working

1. Update get_state/restore_state to handle streaming turns
2. Remove StreamingRichLog class, factory function, CSS, re-exports
3. Remove from app.py compose, hot-reload, widget accessors
4. Update tests

#### Acceptance Criteria
- [ ] Hot-reload preserves streaming state (blocks, delta buffer, is_streaming flag)
- [ ] After reload, streaming continues appending to correct turn
- [ ] No remaining references to StreamingRichLog in codebase
- [ ] StreamingRichLog CSS removed from styles.css
- [ ] All existing tests pass (modified as needed)
- [ ] New tests cover streaming turn lifecycle

#### Unknowns to Resolve
1. After hot-reload, do we re-render the streaming turn's visible strips from preserved blocks, or just wait for new deltas to trigger render?
   - Re-render from blocks is safer (ensures visible content)

#### Exit Criteria
- [ ] Hot-reload tested with active streaming turn

## Dependencies
- Sprints 1-5 (conversation-display) complete
- ConversationView Line API architecture stable

## Risks
- **MEDIUM**: Delta rendering performance — rendering full accumulated text buffer per token could slow on very long responses (10K+ chars). Mitigate with throttle if needed.
- **LOW**: Line offset correctness — streaming turn is always last, no other turn offsets shift.
- **LOW**: Filter mid-stream — guard with `is_streaming` check in rerender loop.
