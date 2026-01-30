# Evaluation: Composable Conversation Rendering System
Timestamp: 2026-01-29
Git Commit: 92da2f7

## Executive Summary
Overall: 0% complete (design only, no implementation started) | Critical issues: 0 | Tests reliable: N/A

This is an evaluation of a **proposed design** (plan at `/Users/bmf/.claude/plans/virtual-fluttering-turing.md`) against the existing codebase. No implementation work has begun. The design is sound in its fundamentals but has several gaps that need resolution before or during implementation.

## Design Feasibility Assessment

### API Compatibility: VERIFIED
- Textual 7.3.0 is installed (far exceeds `>=0.80.0` requirement)
- `ScrollableContainer` has all required methods: `scroll_end`, `scroll_to_widget`, `is_vertical_scroll_end`, `mount`, `query`, `query_one`
- `Static.update()` accepts `VisualType` which includes `rich.text.Text` -- confirmed
- Rich `Text` objects can be concatenated via `Text.append(other_text)` -- confirmed

### Surface Area Analysis
The plan touches 6 files. Here is the impact and risk for each:

| File | Change Scope | Risk |
|------|-------------|------|
| `widget_factory.py` | Major rewrite of ConversationView, 2 new classes | HIGH - central widget |
| `rendering.py` | Add `BLOCK_FILTER_KEY` dict | LOW - additive |
| `event_handlers.py` | Add `filters` param to `finish_turn()` calls | LOW - 4 call sites |
| `app.py` | Change `rerender` -> `apply_filters` in watcher, add keybindings | MEDIUM |
| `styles.css` | Add TurnWidget/StreamingTurnWidget/selected styles | LOW |
| `widgets.py` | Re-export 2 new classes | LOW |

## Findings

### 1. ConversationView RichLog -> ScrollableContainer Migration
**Status**: NOT_STARTED (design complete)
**Feasibility**: HIGH

The current `ConversationView(RichLog)` uses only `self.write(Text)` and `self.clear()`. The public API (`append_block`, `finish_turn`, `rerender`, `get_state`, `restore_state`) is well-contained. No external code calls RichLog-specific methods.

**Key concern**: RichLog handles text wrapping, line-by-line display, and internal virtual scrolling. Switching to `ScrollableContainer` with `Static` children changes the rendering model fundamentally:
- RichLog: each `write()` appends a line to an internal buffer; scrolls line-by-line
- ScrollableContainer + Static: each child is a full widget with its own layout; scrolls by widget regions

This means the new `TurnWidget` must combine ALL blocks for a turn into a single `Text` object passed to `Static.update()`. This works (verified via Rich Text concatenation) but requires joining blocks with newlines, which the current `rerender()` method already does implicitly via separate `write()` calls.

### 2. TurnWidget Block-to-Text Aggregation
**Status**: NOT_STARTED (design specifies approach)
**Issue**: The plan says `_render()` calls `render_blocks()` then `self.update(combined_rich_text)`. But `render_blocks()` returns `list[Text]` -- there is no existing function to join those into a single `Text` with newlines. This is trivial to implement but is not acknowledged in the plan.

**Evidence**: `rendering.py:274-281` -- `render_blocks()` returns `list[Text]`, not a single `Text`.

**Impact**: LOW -- straightforward to add a join step.

### 3. TextDeltaBlock Handling in StreamingTurnWidget
**Status**: NOT_STARTED (design specifies approach)
**Issue**: The current `ConversationView` accumulates `TextDeltaBlock` text in `_text_delta_buffer` and flushes on non-delta blocks or `finish_turn()`. The plan says `StreamingTurnWidget` should "accumulate TextDeltaBlock text in a buffer, renders other blocks immediately."

The design does not specify how `StreamingTurnWidget` renders incrementally. If it calls `self.update()` on every delta, that means rebuilding the entire content of the widget on each keystroke of streaming output. For long responses, this could be expensive.

**Concern**: RichLog `write()` is append-only (O(1) per operation). `Static.update()` replaces the entire content. For streaming with hundreds of deltas, the widget must rebuild its content on each update. This is potentially O(n^2) in total work for n deltas.

**Mitigation options**:
1. Buffer deltas and update on a timer (e.g., every 50ms) -- reduces frequency but not total work
2. Use a different widget for streaming (e.g., keep RichLog for streaming, replace with Static on finalize)
3. Accept the cost -- Static.update is fast enough for typical response lengths

**Impact**: MEDIUM -- streaming performance needs benchmarking.

### 4. finish_turn() Signature Change
**Status**: NOT_STARTED
**Evidence**: The plan says `finish_turn()` needs `filters` param, but the current code at `event_handlers.py` lines 37, 123, 175, 203 calls `conv.finish_turn()` with no args. The plan also says `finish_turn()` "creates a permanent TurnWidget from streaming blocks, mounts before the streaming widget."

**Question**: Why does `finish_turn()` need `filters`? The plan says to create a `TurnWidget` from accumulated blocks. The `TurnWidget` needs filters to decide initial rendering. But `filters` is already available in `widgets["filters"]` at all 4 call sites. The plan could pass it explicitly or the `ConversationView` could store the current filter state.

**Design decision**: The plan chose explicit parameter passing (pass `widgets["filters"]`), which is fine. The 4 call sites in `event_handlers.py` all have access to `widgets["filters"]`.

### 5. BLOCK_FILTER_KEY Mapping Completeness
**Status**: NOT_STARTED
**Evidence**: The plan at lines 55-68 defines `BLOCK_FILTER_KEY` covering 10 block types. There are 18 block types in `formatting.py`. The unmapped types (RoleBlock, TextContentBlock, ImageBlock, UnknownTypeBlock, ErrorBlock, ProxyErrorBlock, LogBlock, NewlineBlock) are commented as "always visible, never filtered."

**Verification**: Cross-checked against `rendering.py` BLOCK_RENDERERS:
- `RoleBlock` -- filters system role, but the plan maps it to None. Actually, `_render_role` at line 139 checks `filters["system"]` for system roles. This is a **partial filter** -- it depends on the role value, not just block type. The `BLOCK_FILTER_KEY` approach of mapping type->filter is insufficient here.
- `TextContentBlock` -- always shown, correct
- `ImageBlock` -- always shown, correct
- `ErrorBlock`, `ProxyErrorBlock` -- always shown, correct
- `LogBlock` -- always shown, correct
- `NewlineBlock` -- always shown, correct

**Issue**: `RoleBlock` filtering depends on `block.role == "system"`, not just block type. The `BLOCK_FILTER_KEY` optimization that skips re-render when "no relevant filter changed" will miss this case. If `show_system` changes but the turn has no blocks mapped to "system" in `BLOCK_FILTER_KEY`, the turn won't re-render, but it actually should because `RoleBlock(role="system")` should appear/disappear.

**Impact**: MEDIUM -- the optimization will produce incorrect results for turns containing system role blocks. Need either:
- Map `RoleBlock` to "system" in `BLOCK_FILTER_KEY` (over-rerenders non-system roles but correct)
- Use a more granular check that inspects block data

### 6. Hot-Reload State Transfer
**Status**: NOT_STARTED
**Evidence**: The plan specifies `get_state()` returns `{"all_blocks": list[list[FormattedBlock]], "follow_mode": bool, "selected_turn": int|None, "streaming_blocks": list, "streaming_buffer": list}`. The current `get_state()` at `widget_factory.py:88-94` returns `{"turn_blocks", "current_turn_blocks", "text_delta_buffer"}`.

**Issue**: The plan changes the state key names from `turn_blocks` to `all_blocks`. The `_replace_all_widgets()` method in `app.py:229-308` calls `get_state()` on the old widget and `restore_state()` on the new one. As long as both methods agree on key names, this is fine. But if a hot-reload happens mid-migration (old code state -> new code restore), the key mismatch will silently drop data.

**Impact**: LOW -- hot-reload during a code deploy is an edge case, and the state keys just need to be consistent within a version.

### 7. Scroll Anchor on Filter Toggle (Phase 4)
**Status**: NOT_STARTED (design complete)
**Evidence**: Plan lines 136-143 describe finding a "viewport anchor" turn before applying filters, then scrolling it back into view afterward.

**Issue**: `_find_viewport_anchor()` is not specified in detail. Textual's `ScrollableContainer` does not have a built-in "find first visible child" method. Implementation requires:
1. Get current scroll offset (`self.scroll_y`)
2. Iterate children, check if their `region.y` intersects with viewport
3. Return the first matching turn's ID

This is feasible but requires understanding Textual's coordinate system (widget regions are relative to the container's virtual space, not the screen). The `scroll_to_widget()` method exists for the restore step.

**Impact**: LOW -- Textual provides sufficient API; implementation is straightforward.

### 8. Follow Mode Detection
**Status**: NOT_STARTED
**Evidence**: Plan says "On manual scroll: detect if scrolled away from bottom -> auto-disable follow. Override `on_scroll_up` to set `_follow_mode = False`."

**Issue**: `is_vertical_scroll_end` is a property on `ScrollableContainer` that indicates whether the container is scrolled to the bottom. A cleaner approach than overriding `on_scroll_up` would be to check `is_vertical_scroll_end` after any scroll action. The plan's approach works but is incomplete -- it only handles keyboard scroll-up, not mouse wheel scroll or page-up.

**Better approach**: Override `watch_scroll_y` to check `is_vertical_scroll_end` after any scroll change.

**Impact**: LOW -- design choice, both approaches work.

## Ambiguities Found (Original)

| Area | Question | How Plan Guessed | Impact | Resolution |
|------|----------|-----------------|--------|------------|
| RoleBlock filtering | Should BLOCK_FILTER_KEY handle value-dependent filters? | Omitted RoleBlock from map | MEDIUM | **RESOLVED**: Map `RoleBlock -> "system"` (over-approximation). Updated in Sprint 1 PLAN and CONTEXT. |
| Streaming performance | Is Static.update() fast enough for per-delta updates? | Not addressed | MEDIUM | **RESOLVED by architecture change**: StreamingRichLog uses native RichLog.write() (O(1) append), not Static.update(). No performance concern. |
| Turn boundary definition | What constitutes a "turn"? | Plan shows alternating | LOW | **RESOLVED**: Follows current `finish_turn()` semantics. Request = one turn, response = one turn. |
| follow_mode auto-disable | Which scroll actions disable follow? | Only keyboard scroll-up | LOW | **RESOLVED**: Use `watch_scroll_y` (catches ALL sources). Correct 2-arg signature verified against scroll_view.py:52. |
| Hot-reload mid-transition | State key mismatch between versions? | Not addressed | LOW | **Accepted risk**: User chose not to add migration shim. First hot-reload after deploy may lose conversation display (data preserved in DB). |
| Sprint 2 architecture mismatch | Sprint 2 designed for TurnWidget, Sprint 1 uses Line API | TurnWidget references throughout | CRITICAL | **RESOLVED**: Sprint 2 fully rewritten for Line API (2026-01-29T20:00:00). All features use TurnData list + line offsets. |
| watch_scroll_y signature | Sprint 2 used wrong 1-arg signature | `(self, value)` | HIGH | **RESOLVED**: Correct signature `(self, old_value, new_value)` with `super()` call. Verified against scroll_view.py:52. |

## Missing Checks / Tests Needed

1. **Unit test for TurnData.re_render()** -- verify that changing a filter correctly updates or skips strip re-rendering
2. **Integration test for scroll position preservation** -- toggle filter while scrolled to middle, verify anchor
3. **Test for BLOCK_FILTER_KEY correctness** -- verify all block types that check filters are in the map
4. **Test for follow-mode behavior** -- verify scroll-to-bottom re-enables, manual scroll disables via watch_scroll_y
5. **Test for turn selection rendering** -- verify render_line() applies selection style to correct line range
6. **Test for click-to-select** -- verify event.y + scroll_offset maps to correct turn

## Remaining MEDIUM Confidence Item

**Scroll anchor timing** (Sprint 2): Does `scroll_to(y=N)` work immediately after updating `virtual_size`? ScrollView's `scroll_to` calls `_scroll_to` directly (no deferred layout). Should work — verify with test script in Sprint 2 CONTEXT.

## Verdict
- [x] CONTINUE - All critical issues resolved
- [ ] PAUSE - Ambiguities need clarification

Sprint 1 is internally consistent and ready for implementation. Sprint 2 has been rewritten for the Line API architecture (2026-01-29T20:00:00) with one remaining MEDIUM confidence item (scroll anchor timing) that can be resolved during implementation via the provided test script.
