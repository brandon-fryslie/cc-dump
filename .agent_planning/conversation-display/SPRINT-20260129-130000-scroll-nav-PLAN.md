# Sprint: scroll-nav - Scroll and Navigation
Generated: 2026-01-29T13:00:00
Confidence: HIGH: 5, MEDIUM: 1, LOW: 0
Status: PARTIALLY READY
Source: EVALUATION-20260129.md

## Sprint Goal
Add follow mode toggle, turn-by-turn keyboard/mouse navigation, and scroll anchor preservation on filter toggle.

## Scope
**Deliverables:**
- Follow mode with auto-scroll toggle (keybinding: `f`)
- Turn navigation: j/k (next/prev), n/N (next/prev tool turn), g/G (first/last)
- Mouse click to select turn
- TurnSelected message
- CSS `.selected` state for highlighted turn
- Scroll anchor on filter toggle (preserve viewport position)

## Work Items

### P0 - Follow mode toggle
**Confidence**: HIGH
**Dependencies**: Sprint 1 (widget-arch) -- ConversationView must be ScrollView
**Spec Reference**: Phase 2 of technical design | **Status Reference**: EVALUATION-20260129.md Finding 8 (Follow Mode Detection)

#### Description
Add `_follow_mode: bool = True` to ConversationView. When enabled, `scroll_end(animate=False)` is called after `add_turn()` and when StreamingRichLog content grows. On **any** scroll away from bottom — keyboard, mouse wheel, programmatic — auto-disable follow. Use `watch_scroll_y` to catch ALL scroll sources.

The rule is simple: **if scrolled to bottom → follow. If not → don't follow.**

#### Acceptance Criteria
- [ ] `_follow_mode = True` by default on ConversationView
- [ ] After `add_turn()`, if `_follow_mode` is True, calls `self.scroll_end(animate=False)`
- [ ] `watch_scroll_y` detects scroll position: sets `_follow_mode = False` when not at bottom, `True` when at bottom
- [ ] Works with ALL scroll sources: mouse wheel, keyboard arrows, page up/down, programmatic scroll
- [ ] `toggle_follow()` method flips `_follow_mode`; if re-enabling, scrolls to bottom
- [ ] `scroll_to_bottom()` explicitly re-enables follow mode

#### Technical Notes
- `watch_scroll_y` is a Textual watcher on the `scroll_y` reactive (ScrollView inherits this). Override it on ConversationView.
- Use `self.scroll_y >= self.max_scroll_y - 1` as the "at bottom" check (1-line tolerance for sub-pixel positions).
- For StreamingRichLog follow: the app can poll or observe StreamingRichLog's content growth. Since StreamingRichLog is a separate widget, ConversationView doesn't scroll it — the StreamingRichLog's own `auto_scroll` handles following its content. The app's job is to keep the StreamingRichLog visible when follow mode is on (ensure it's not scrolled off-screen).
- **Guard against recursive triggers**: `watch_scroll_y` fires when `scroll_end()` is called. Use a `_scrolling_programmatically` flag to avoid disabling follow mode during programmatic scrolls.

---

### P0 - Keybinding for follow mode
**Confidence**: HIGH
**Dependencies**: Follow mode toggle
**Spec Reference**: Phase 2 keybinding | **Status Reference**: N/A

#### Description
Add `Binding("f", "toggle_follow", "f|ollow", show=True)` to `CcDumpApp.BINDINGS` and implement `action_toggle_follow()` which calls `self._get_conv().toggle_follow()`.

#### Acceptance Criteria
- [ ] Binding `f` -> `toggle_follow` added to `BINDINGS` in `app.py`
- [ ] `action_toggle_follow()` calls `self._get_conv().toggle_follow()`
- [ ] Footer shows follow mode state (via binding description)

#### Technical Notes
Insert in BINDINGS list. The `show=True` makes it appear in the footer.

---

### P1 - TurnSelected message and turn selection state
**Confidence**: HIGH
**Dependencies**: Sprint 1 (TurnWidget exists)
**Spec Reference**: Phase 3 TurnSelected message, _selected_turn | **Status Reference**: N/A

#### Description
Add `TurnSelected(Message)` with `turn_index: int`. Add `_selected_turn: int | None` to ConversationView. TurnWidget posts `TurnSelected` on `on_click()`. ConversationView handles the message, updates selection, adds/removes `.selected` CSS class.

#### Acceptance Criteria
- [ ] `TurnSelected(Message)` class defined (in widget_factory.py or a messages module)
- [ ] `TurnWidget.on_click()` posts `TurnSelected(self._turn_index)`
- [ ] `ConversationView._selected_turn: int | None = None`
- [ ] `ConversationView.on_turn_selected(message)` updates selection: removes `.selected` from old, adds to new
- [ ] `select_turn(turn_index)` method on ConversationView for programmatic selection

#### Technical Notes
Use `self.add_class("selected")` and `self.remove_class("selected")` on TurnWidget instances. Query by `#turn-{index}` to find specific turns.

---

### P1 - Turn navigation keybindings (j/k/n/N/g/G)
**Confidence**: HIGH
**Dependencies**: TurnSelected message, follow mode
**Spec Reference**: Phase 3 keybindings | **Status Reference**: N/A

#### Description
Add navigation methods to ConversationView and keybindings to CcDumpApp:
- `j`/`k`: next/prev visible turn
- `n`/`N`: next/prev turn containing a tool block
- `g`/`G`: first/last turn

Navigation selects the turn and scrolls it into view. It also disables follow mode (user is navigating).

#### Acceptance Criteria
- [ ] `select_next_turn(forward=True)` on ConversationView: finds next visible TurnWidget, selects it, scrolls visible
- [ ] `next_turn_of_type(block_type, forward=True)` on ConversationView: finds next turn containing tool blocks
- [ ] `jump_to_first()` and `jump_to_last()` select and scroll to first/last visible turn
- [ ] All 6 keybindings added to `CcDumpApp.BINDINGS` with `show=False`
- [ ] Navigation disables follow mode (sets `_follow_mode = False`)

#### Technical Notes
- Use `self.query(TurnWidget)` to get ordered list of turns. Filter by `tw.display == True` for visible turns.
- `scroll_to_widget(tw)` or `tw.scroll_visible()` to bring the selected turn into view.
- For "next tool turn", check if any block in `tw._blocks` is `ToolUseBlock`, `ToolResultBlock`, or `StreamToolUseBlock`.
- Bindings:
  ```python
  Binding("j", "next_turn", "next", show=False),
  Binding("k", "prev_turn", "prev", show=False),
  Binding("n", "next_tool_turn", "next tool", show=False),
  Binding("shift+n", "prev_tool_turn", "prev tool", show=False),
  Binding("g", "first_turn", "top", show=False),
  Binding("shift+g", "last_turn", "bottom", show=False),
  ```

---

### P1 - CSS for .selected state
**Confidence**: HIGH
**Dependencies**: TurnSelected message
**Spec Reference**: Phase 3 CSS | **Status Reference**: N/A

#### Description
Add CSS rule for `TurnWidget.selected` with a subtle background highlight and left border accent.

#### Acceptance Criteria
- [ ] `TurnWidget.selected` CSS rule added to `styles.css`
- [ ] Visual distinction is subtle (background darken + left border)
- [ ] Selection is visible but does not distract from content

#### Technical Notes
```css
TurnWidget.selected {
    background: $surface-darken-1;
    border-left: tall $accent;
}
```

---

### P2 - Scroll anchor on filter toggle
**Confidence**: MEDIUM
**Dependencies**: Sprint 1 (ConversationView with TurnWidget children), follow mode
**Spec Reference**: Phase 4 of technical design | **Status Reference**: EVALUATION-20260129.md Finding 7 (Scroll Anchor)

#### Description
Before applying filter changes, identify the first TurnWidget visible in the viewport (the anchor). After applying filters, scroll the anchor back into view. This prevents content jumps when toggling filters that hide/show large amounts of content.

#### Acceptance Criteria
- [ ] `_find_viewport_anchor() -> int | None` returns the turn index of the first visible TurnWidget in the viewport
- [ ] `rerender(filters)` calls `_find_viewport_anchor()` before applying filters, then scrolls the anchor back after
- [ ] Toggling a filter while scrolled to the middle of a conversation does not jump scroll position

#### Unknowns to Resolve
1. **Viewport anchor detection**: Textual's `ScrollableContainer` exposes `scroll_y` and child widgets have `region` (Region with x, y, width, height). The region coordinates are relative to the container's virtual canvas. Need to verify: does `widget.region.y` give the position relative to the container content, and is `scroll_y` the offset into that content? Research approach: read Textual source for `ScrollableContainer` and `Widget.region`, or write a small test that logs these values.

2. **Timing of scroll restoration**: After `apply_filters()`, widgets may resize asynchronously (Textual layout is deferred). The `scroll_to_widget()` call may need to be posted via `call_later()` or `call_after_refresh()` to ensure layout is computed before scrolling. Research approach: test with a filter that shows/hides many turns and observe if direct scroll works or needs deferral.

#### Exit Criteria (to reach HIGH confidence)
- [ ] Confirmed that `widget.region.y - self.scroll_y` gives viewport-relative position
- [ ] Confirmed that `scroll_to_widget()` works immediately after `apply_filters()` or identified the correct deferral mechanism

#### Technical Notes
Implementation sketch:
```python
def _find_viewport_anchor(self) -> int | None:
    scroll_y = self.scroll_y
    viewport_height = self.size.height
    for tw in self.query(TurnWidget):
        if tw.display and tw.region.y >= scroll_y and tw.region.y < scroll_y + viewport_height:
            return int(tw.id.split("-")[1])  # extract turn index
    return None
```

If the direct approach does not work due to coordinate system issues, fallback: store `scroll_y / max_scroll_y` ratio before filter, restore ratio after.

## Dependencies
- **Sprint 1 (widget-arch)**: All work items depend on Sprint 1 being complete. ConversationView must be a ScrollableContainer with TurnWidget children.
- Internal ordering: Follow mode should be done first (navigation disables it). TurnSelected + navigation depend on each other. Scroll anchor is independent and can be done last.

## Risks
- **Textual scroll coordinate system**: The MEDIUM-confidence scroll anchor item depends on understanding Textual's coordinate system for `widget.region` vs `scroll_y`. If the API does not behave as expected, the fallback ratio-based approach should work.
- **Shift+key bindings**: Textual's `Binding("shift+n", ...)` syntax needs verification. Some Textual versions use `"N"` (uppercase) instead of `"shift+n"`. Test early.
- **Performance of query(TurnWidget)**: For very long conversations (hundreds of turns), iterating all TurnWidgets on every navigation keystroke could be slow. If so, maintain a cached ordered list. This is unlikely to be an issue for typical usage.
