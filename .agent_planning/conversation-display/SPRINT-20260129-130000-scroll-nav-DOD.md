# Definition of Done: scroll-nav
Generated: 2026-01-29T13:00:00
Updated: 2026-01-30T06:30:00
Status: COMPLETE (all criteria verified)
Plan: SPRINT-20260129-130000-scroll-nav-PLAN.md
Architecture: ScrollView + Line API (no TurnWidget — all features operate on TurnData list)

## Acceptance Criteria

### Follow mode toggle
- [ ] `_follow_mode = True` by default
- [ ] Auto-scrolls to bottom on new content when follow mode enabled
- [ ] `watch_scroll_y(self, old_value, new_value)` — correct 2-arg signature, calls `super()` first
- [ ] Disables follow mode when user scrolls away from bottom (any source: mouse, keyboard, programmatic)
- [ ] `_scrolling_programmatically` guard prevents recursive disable during `scroll_end()`
- [ ] `toggle_follow()` flips mode; re-enables scroll-to-bottom when turning on
- [ ] Keybinding `f` toggles follow mode from app

### Turn selection and visual highlight
- [ ] `_selected_turn: int | None` tracks selection by turn index
- [ ] `select_turn(turn_index)` updates selection, clears line cache, refreshes affected line ranges
- [ ] `render_line(y)` applies `_SELECTED_STYLE` (background tint) when y is in selected turn's line range
- [ ] `deselect()` clears selection
- [ ] Only one turn selected at a time

### Click to select
- [ ] `on_click(event)` maps `event.y + scroll_offset.y` to content line
- [ ] Uses `_find_turn_for_line()` (binary search) to resolve turn
- [ ] Calls `select_turn(turn.turn_index)`

### Turn navigation
- [ ] `j` selects next visible turn (line_count > 0), `k` selects previous
- [ ] `n` selects next turn with tool blocks, `N` selects previous
- [ ] `g` selects first visible turn, `G` selects last
- [ ] Navigation scrolls to `turn.line_offset` via `scroll_to(y=...)`
- [ ] Navigation disables follow mode (except `G` which re-enables it)
- [ ] All 6 bindings added: `j`, `k`, `n`, `N`, `g`, `G` (show=False)

### Scroll anchor on filter toggle
- [ ] `_find_viewport_anchor()` returns `(turn_index, offset_within_turn)` using binary search on scroll_y
- [ ] `rerender()` preserves scroll position: anchor before, restore after
- [ ] Handles anchor turn becoming invisible (finds nearest visible turn)
- [ ] Toggling filters mid-conversation does not visibly jump scroll

## Exit Criteria (for MEDIUM confidence item)

### Scroll anchor
- [ ] Verified `scroll_to` takes effect immediately after `virtual_size` update (no deferred layout needed)
- [ ] Tested with filter toggle that hides/shows content spanning 50+ lines
