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

## Ambiguities Found

| Area | Question | How Plan Guessed | Impact |
|------|----------|-----------------|--------|
| RoleBlock filtering | Should BLOCK_FILTER_KEY handle value-dependent filters? | Omitted RoleBlock from map (None = always visible) | MEDIUM -- system role blocks won't hide/show correctly with the optimization |
| Streaming performance | Is Static.update() fast enough for per-delta updates? | Not addressed | MEDIUM -- needs benchmarking |
| Turn boundary definition | What constitutes a "turn"? Request blocks vs response blocks? | Plan shows request turn + response turn alternating | LOW -- follows current `finish_turn()` semantics |
| follow_mode auto-disable | Which scroll actions disable follow? | Only keyboard scroll-up | LOW -- should be all scroll sources |
| Hot-reload mid-transition | What happens if state keys change between versions? | Not addressed | LOW -- edge case |

## Missing Checks / Tests Needed

1. **Unit test for TurnWidget.apply_filters()** -- verify that changing a filter correctly updates or skips rendering
2. **Benchmark test for StreamingTurnWidget** -- measure update latency with 500+ deltas
3. **Integration test for scroll position preservation** -- toggle filter while scrolled to middle, verify anchor
4. **Test for BLOCK_FILTER_KEY correctness** -- verify all block types that check filters are in the map
5. **Test for follow-mode behavior** -- verify scroll-to-bottom re-enables, manual scroll disables

## Recommendations

1. **Resolve RoleBlock filter mapping** before implementation. Either map `RoleBlock -> "system"` (safe, slightly over-renders) or add a data-dependent check. The simpler option is better for Phase 1.

2. **Benchmark StreamingTurnWidget** early. Create a prototype that calls `Static.update()` in a loop with increasing text sizes. If it's too slow (>16ms per update for typical sizes), plan a buffered update strategy.

3. **Implement phases sequentially as designed.** Phase 1 (replace internals) is self-contained and testable. Phases 2-4 are additive. Do not start Phase 2 until Phase 1 passes all existing PTY integration tests.

4. **Use `watch_scroll_y`** instead of `on_scroll_up` for follow-mode detection. This catches all scroll sources (keyboard, mouse, programmatic).

5. **Add `_combine_texts(texts: list[Text]) -> Text`** helper to `rendering.py` for joining rendered blocks into a single Text with newlines. This is the missing piece between `render_blocks()` output and `Static.update()` input.

6. **Keep `finish_turn()` backward-compatible** during implementation. Accept `filters` as optional kwarg with default `None`. If `None`, use the last-known filter state stored on the ConversationView. This avoids a breaking change in the event_handlers interface.

## Verdict
- [x] CONTINUE - Issues clear, implementer can fix
- [ ] PAUSE - Ambiguities need clarification

The design is feasible. The Textual API supports all proposed operations. The main risks are streaming performance (benchmarkable) and the RoleBlock filter optimization (resolvable with a simple mapping choice). All existing PTY tests should pass since they test through the terminal, not widget internals. The phased approach is sound -- Phase 1 is a clean replacement of ConversationView internals with no external API changes.
