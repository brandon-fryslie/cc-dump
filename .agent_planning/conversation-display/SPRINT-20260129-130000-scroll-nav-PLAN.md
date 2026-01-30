# Sprint: scroll-nav - Scroll and Navigation
Generated: 2026-01-29T13:00:00
Updated: 2026-01-30T06:30:00
Confidence: HIGH: 6, MEDIUM: 0, LOW: 0
Status: COMPLETE
Source: EVALUATION-20260129.md
Architecture: ScrollView + Line API (no TurnWidget — turns are TurnData dataclass instances)

## Sprint Goal
Add follow mode toggle, turn-by-turn keyboard/mouse navigation, and scroll anchor preservation on filter toggle. All features operate on the Line API data model (TurnData list + line offsets), not a widget tree.

## Architecture Constraint

Sprint 1 renders conversation via `ConversationView(ScrollView)` with `render_line(y)`. There are **no child widgets**. Turns exist as `TurnData` objects in `self._turns: list[TurnData]`. Each `TurnData` has `line_offset` (start line in virtual space), `line_count`, `strips`, and `blocks`.

All Sprint 2 features must work through:
- **Line offsets** for scroll positioning (`scroll_to(y=turn.line_offset)`)
- **Binary search** for mapping screen coordinates to turns
- **Strip manipulation** for visual selection (modify strip styles in `render_line()`)
- **`self._turns` iteration** for navigation (skip empty turns)

## Scope
**Deliverables:**
- Follow mode with auto-scroll toggle (keybinding: `f`)
- Turn navigation: j/k (next/prev), n/N (next/prev tool turn), g/G (first/last)
- Mouse click to select turn
- Visual selection highlight via Strip style overlay in render_line()
- Scroll anchor on filter toggle (preserve viewport position)

## Work Items

### P0 - Follow mode toggle
**Confidence**: HIGH
**Dependencies**: Sprint 1 (widget-arch) — ConversationView must be ScrollView

#### Description
Add `_follow_mode: bool = True` to ConversationView. When enabled, `scroll_end(animate=False)` is called after `add_turn()` and when StreamingRichLog content grows. On **any** scroll away from bottom — keyboard, mouse wheel, programmatic — auto-disable follow.

Override `watch_scroll_y` to detect scroll position changes from ALL sources. **Critical**: the Textual signature is `watch_scroll_y(self, old_value: float, new_value: float)` and the override **must call super()** to preserve scrollbar position sync and refresh.

Use a `_scrolling_programmatically: bool` guard flag to prevent `watch_scroll_y` from disabling follow mode when `scroll_end()` triggers the watcher.

#### Acceptance Criteria
- [ ] `_follow_mode = True` by default on ConversationView
- [ ] After `add_turn()`, if `_follow_mode` is True, calls `self.scroll_end(animate=False)`
- [ ] `watch_scroll_y(self, old_value, new_value)` overrides with correct 2-arg signature
- [ ] Override calls `super().watch_scroll_y(old_value, new_value)` first
- [ ] Sets `_follow_mode = False` when `not self.is_vertical_scroll_end` and `not self._scrolling_programmatically`
- [ ] Sets `_follow_mode = True` when `self.is_vertical_scroll_end`
- [ ] Works with ALL scroll sources: mouse wheel, keyboard arrows, page up/down, programmatic scroll
- [ ] `toggle_follow()` method flips `_follow_mode`; if re-enabling, scrolls to bottom
- [ ] `scroll_to_bottom()` explicitly re-enables follow mode
- [ ] `_scrolling_programmatically` guard prevents recursive disable during `scroll_end()`

#### Technical Notes
- `is_vertical_scroll_end` checks `self.scroll_offset.y == self.max_scroll_y or not self.size` (from widget.py:1967)
- Tolerance: use `self.scroll_offset.y >= self.max_scroll_y - 1` for sub-pixel positions
- For StreamingRichLog follow: StreamingRichLog is a separate sibling widget with its own `auto_scroll`. The app keeps it docked below ConversationView. No coordination needed for streaming content — RichLog auto-scrolls itself. The app only needs to keep the StreamingRichLog visible when follow mode is on.

---

### P0 - Keybinding for follow mode
**Confidence**: HIGH
**Dependencies**: Follow mode toggle

#### Description
Add `Binding("f", "toggle_follow", "f|ollow", show=True)` to `CcDumpApp.BINDINGS` and implement `action_toggle_follow()`.

#### Acceptance Criteria
- [ ] Binding `f` -> `toggle_follow` added to `BINDINGS` in `app.py`
- [ ] `action_toggle_follow()` calls `self._get_conv().toggle_follow()`
- [ ] Footer shows follow mode state (via binding description)

---

### P1 - Turn selection state and visual highlight
**Confidence**: HIGH
**Dependencies**: Sprint 1 (ConversationView with TurnData list)

#### Description
Add `_selected_turn: int | None` to ConversationView. When a turn is selected, `render_line(y)` applies a style overlay (background tint + left border character) to strips belonging to the selected turn. Selection is tracked by turn index into `self._turns`.

Since there are no child widgets, the selection visual is implemented entirely in `render_line()` — when `y` falls within the selected turn's line range, the returned Strip gets a style applied.

#### Acceptance Criteria
- [ ] `_selected_turn: int | None = None` on ConversationView
- [ ] `select_turn(turn_index: int)` sets `_selected_turn`, clears line cache, refreshes affected lines
- [ ] `render_line(y)` applies selection style when `y` is in selected turn's line range
- [ ] Selection visual: background tint (e.g., `Style(bgcolor="grey15")`) applied via `strip.apply_style()`
- [ ] Only one turn selected at a time — selecting a new turn refreshes old and new line ranges
- [ ] `deselect()` clears selection and refreshes

#### Technical Notes
- Use `refresh_lines(turn.line_offset, turn.line_count)` to refresh only affected lines on selection change
- In `render_line(y)`, after obtaining the strip from the turn, check if `self._selected_turn == turn.turn_index`. If so, apply `_SELECTED_STYLE` via `strip.apply_style()`
- `_SELECTED_STYLE = Style(bgcolor="grey15")` — subtle background tint
- Clear line cache on selection change (or use a cache key that includes selection state)

---

### P1 - Click to select turn
**Confidence**: HIGH
**Dependencies**: Turn selection state

#### Description
Override `on_click(event: Click)` on ConversationView. Map the click's viewport-relative `y` coordinate to a content line, then binary-search for the turn containing that line.

#### Acceptance Criteria
- [ ] `on_click(self, event: Click)` on ConversationView
- [ ] Maps `event.y + self.scroll_offset.y` to content line
- [ ] Uses `_find_turn_for_line()` (from Sprint 1) to find the turn
- [ ] Calls `self.select_turn(turn.turn_index)` if found

#### Technical Notes
- Click `event.y` is relative to the widget's viewport (visible area), not the full content
- Adding `self.scroll_offset.y` converts to content-space line number
- `_find_turn_for_line()` already exists from Sprint 1 (binary search on line offsets)

---

### P1 - Turn navigation keybindings (j/k/n/N/g/G)
**Confidence**: HIGH
**Dependencies**: Turn selection state, follow mode

#### Description
Add navigation methods to ConversationView and keybindings to CcDumpApp. Navigation operates on `self._turns` list directly (no widget queries). A turn is "visible" if `turn.line_count > 0` (all blocks filtered out → empty strips → invisible).

- `j`/`k`: next/prev visible turn
- `n`/`N`: next/prev turn containing a tool block
- `g`/`G`: first/last turn

Navigation selects the turn, scrolls it into view, and disables follow mode.

#### Acceptance Criteria
- [ ] `select_next_turn(forward=True)` iterates `self._turns`, skips turns with `line_count == 0`
- [ ] `next_tool_turn(forward=True)` finds next turn whose blocks contain tool types
- [ ] `jump_to_first()` and `jump_to_last()` select first/last visible turn
- [ ] All navigation calls `scroll_to(y=turn.line_offset, animate=False)`
- [ ] All navigation sets `_follow_mode = False` (except `jump_to_last()` which re-enables it)
- [ ] All 6 keybindings added to `CcDumpApp.BINDINGS` with `show=False`

#### Technical Notes
- Keybindings use the character directly for shift variants: `"N"` (uppercase) not `"shift+n"`, `"G"` not `"shift+g"`
- Tool block types: `ToolUseBlock`, `ToolResultBlock`, `StreamToolUseBlock`
- Navigation wraps: j at last turn → stays at last. k at first → stays at first. (No wrapping.)
- `jump_to_last()` re-enables follow mode and calls `scroll_end()`

---

### P2 - Scroll anchor on filter toggle
**Confidence**: MEDIUM
**Dependencies**: Sprint 1 (ConversationView with TurnData), follow mode

#### Description
Before applying filter changes in `rerender()`, identify the first turn visible in the viewport. After re-rendering, scroll so that turn is back at (approximately) the same viewport position. This prevents content jumps when toggling filters that show/hide large amounts of content.

With Line API, this is pure arithmetic — no widget coordinate system to worry about:
1. **Before**: Find the turn containing `self.scroll_offset.y` (binary search)
2. **Record**: The offset within that turn: `offset_within = scroll_y - turn.line_offset`
3. **After re-render**: Recalculate offsets (turn line counts may have changed). Scroll to `turn.line_offset + offset_within` (clamped)

#### Acceptance Criteria
- [ ] `_find_viewport_anchor() -> tuple[int, int] | None` returns `(turn_index, offset_within_turn)`
- [ ] `rerender(filters)` calls `_find_viewport_anchor()` before re-rendering, restores after
- [ ] Toggling a filter while scrolled to the middle does not visibly jump scroll position
- [ ] If the anchor turn becomes empty (all blocks filtered), scrolls to nearest visible turn

#### Unknowns to Resolve
1. **Timing**: Does `scroll_to(y=...)` take effect immediately after updating `virtual_size`? ScrollView's `scroll_to` calls `_scroll_to` directly (no deferred layout needed since Line API doesn't use child widget layout). Should work immediately — verify.
2. **Edge case**: If a filter toggle makes the anchor turn invisible (line_count → 0), the offset formula breaks. Fallback: find the nearest visible turn (search forward then backward from anchor index).

#### Exit Criteria (to reach HIGH confidence)
- [ ] Verified `scroll_to` takes effect immediately after `virtual_size` update
- [ ] Tested with filter toggle that hides/shows content spanning 50+ lines

#### Technical Notes
Implementation:
```python
def _find_viewport_anchor(self) -> tuple[int, int] | None:
    """Find turn at top of viewport and offset within it."""
    scroll_y = int(self.scroll_offset.y)
    turn = self._find_turn_for_line(scroll_y)
    if turn is None:
        return None
    offset_within = scroll_y - turn.line_offset
    return (turn.turn_index, offset_within)

def _restore_anchor(self, anchor: tuple[int, int]):
    """Restore scroll position to anchor turn."""
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
```

## Dependencies
- **Sprint 1 (widget-arch)**: All work items depend on Sprint 1 being complete. ConversationView must be a ScrollView with TurnData list, render_line(), and _find_turn_for_line().
- Internal ordering: Follow mode first → Turn selection → Click/Navigation → Scroll anchor

## Risks
- **Strip style overlay performance**: Applying selection style in `render_line()` adds a `strip.apply_style()` call per visible line. This is the same pattern RichLog uses for its `rich_style` — negligible cost.
- **Scroll anchor timing**: If `scroll_to` doesn't take effect immediately after `virtual_size` update, may need `call_later`. MEDIUM confidence item — verify empirically.
- **Shift+key bindings**: Textual uses `"N"` (uppercase character) not `"shift+n"`. Verify early.
