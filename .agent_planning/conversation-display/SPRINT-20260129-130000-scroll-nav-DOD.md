# Definition of Done: scroll-nav
Generated: 2026-01-29T13:00:00
Status: PARTIALLY READY
Plan: SPRINT-20260129-130000-scroll-nav-PLAN.md

## Acceptance Criteria

### Follow mode toggle
- [ ] `_follow_mode = True` by default
- [ ] Auto-scrolls to bottom on new content when follow mode enabled
- [ ] `watch_scroll_y` disables follow mode when user scrolls away from bottom
- [ ] `toggle_follow()` flips mode; re-enables scroll-to-bottom when turning on
- [ ] Keybinding `f` toggles follow mode from app

### TurnSelected message and selection
- [ ] `TurnSelected(Message)` defined with `turn_index: int`
- [ ] Mouse click on TurnWidget posts `TurnSelected`
- [ ] ConversationView tracks `_selected_turn` and applies `.selected` CSS class
- [ ] Only one turn has `.selected` at a time

### Turn navigation
- [ ] `j` selects next visible turn, `k` selects previous
- [ ] `n` selects next turn with tool blocks, `N` (shift+n) selects previous
- [ ] `g` selects first visible turn, `G` (shift+g) selects last
- [ ] Selected turn is scrolled into view
- [ ] Navigation disables follow mode

### CSS .selected state
- [ ] `TurnWidget.selected` has visible background/border distinction
- [ ] Non-selected turns have no extra styling

### Scroll anchor on filter toggle
- [ ] `_find_viewport_anchor()` identifies the first visible turn in viewport
- [ ] `rerender()` preserves scroll position around filter application
- [ ] Toggling filters mid-conversation does not visibly jump scroll

## Exit Criteria (for MEDIUM confidence items)

### Scroll anchor
- [ ] Verified Textual coordinate system for widget.region vs scroll_y
- [ ] Verified scroll_to_widget timing (immediate vs call_after_refresh)
- [ ] Tested with filter toggle that hides/shows 50+ turns of content
