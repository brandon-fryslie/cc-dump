# Implementation Context: scroll-nav
Generated: 2026-01-29T13:00:00
Updated: 2026-01-29T20:00:00
Confidence: HIGH: 5, MEDIUM: 1
Source: EVALUATION-20260129.md
Plan: SPRINT-20260129-130000-scroll-nav-PLAN.md
Architecture: ScrollView + Line API (no TurnWidget)

## Architecture Constraint

Sprint 1 creates `ConversationView(ScrollView)` with a `_turns: list[TurnData]` data store. There are **no child widgets** — rendering happens via `render_line(y)` which maps virtual line y → TurnData → Strip. All Sprint 2 features must work through data structures and line arithmetic, not widget queries.

Key Sprint 1 API surface used by Sprint 2:
- `self._turns: list[TurnData]` — all finalized turns
- `self._find_turn_for_line(y) -> TurnData | None` — binary search
- `self._recalculate_offsets()` — rebuilds line_offset and virtual_size
- `self._line_cache: LRUCache` — must be cleared on selection changes
- `self.render_line(y) -> Strip` — virtual rendering entry point
- `self.scroll_to(y=..., animate=False)` — ScrollView scroll control
- `self.scroll_end(animate=False)` — scroll to bottom
- `self.scroll_offset.y` — current scroll position
- `self.is_vertical_scroll_end` — at bottom check
- `self.refresh_lines(y_start, line_count)` — partial screen refresh

## File: src/cc_dump/tui/widget_factory.py

### Add to ConversationView.__init__ (Sprint 1 already adds _follow_mode)

```python
    def __init__(self):
        super().__init__()
        self._turns: list[TurnData] = []
        self._total_lines: int = 0
        self._widest_line: int = 0
        self._line_cache: LRUCache = LRUCache(1024)
        self._last_filters: dict = {}
        self._last_width: int = 78
        # Sprint 2 additions:
        self._follow_mode: bool = True
        self._selected_turn: int | None = None
        self._scrolling_programmatically: bool = False
        self._pending_restore: dict | None = None
```

### Follow mode methods

```python
    _SELECTED_STYLE = Style(bgcolor="grey15")

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
```

### Modify add_turn() — add auto-scroll at end

Sprint 1's `add_turn()` already has follow mode scroll. Verify it uses the guard:

```python
    def add_turn(self, blocks: list, filters: dict = None):
        """Add a completed turn from block list."""
        # ... existing Sprint 1 code ...
        self._turns.append(td)
        self._recalculate_offsets()

        if self._follow_mode:
            self._scrolling_programmatically = True
            self.scroll_end(animate=False, immediate=False, x_axis=False)
            self._scrolling_programmatically = False
```

### Turn selection methods

```python
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
```

### Modify render_line() — add selection style overlay

Add to existing `render_line(y)` from Sprint 1, after the strip is obtained from cache or turn lookup:

```python
    def render_line(self, y: int) -> Strip:
        """Line API: render a single line at virtual position y."""
        scroll_x, scroll_y = self.scroll_offset
        actual_y = scroll_y + y
        width = self.scrollable_content_region.width

        if actual_y >= self._total_lines:
            return Strip.blank(width, self.rich_style)

        # Cache key includes selection state
        cache_key = (actual_y, scroll_x, width, self._widest_line, self._selected_turn)
        if cache_key in self._line_cache:
            return self._line_cache[cache_key]

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

        self._line_cache[cache_key] = strip
        return strip
```

**NOTE**: The cache key now includes `self._selected_turn`. This means changing selection invalidates cache entries for the old and new turn's lines. Since we call `self._line_cache.clear()` in `select_turn()`, this is belt-and-suspenders — the cache key also prevents stale renders if clearing is missed.

### Click handler

```python
    def on_click(self, event) -> None:
        """Select turn at click position."""
        # event.y is viewport-relative; add scroll offset for content-space
        content_y = int(event.y + self.scroll_offset.y)
        turn = self._find_turn_for_line(content_y)
        if turn is not None:
            self.select_turn(turn.turn_index)
```

### Navigation methods

```python
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
```

### Scroll anchor in rerender()

Modify Sprint 1's `rerender()`:

```python
    def rerender(self, filters: dict):
        """Re-render affected turns in place. Preserves scroll position."""
        self._last_filters = filters

        if self._pending_restore is not None:
            self._rebuild_from_state(filters)
            return

        # Capture anchor before re-render
        anchor = self._find_viewport_anchor()

        width = self.scrollable_content_region.width if self._size_known else self._last_width
        console = self.app.console
        changed = False
        for td in self._turns:
            if td.re_render(filters, console, width):
                changed = True
        if changed:
            self._recalculate_offsets()
            # Restore anchor after offsets recalculated
            if anchor is not None and not self._follow_mode:
                self._restore_anchor(anchor)

    def _find_viewport_anchor(self) -> tuple[int, int] | None:
        """Find turn at top of viewport and offset within it."""
        if not self._turns:
            return None
        scroll_y = int(self.scroll_offset.y)
        turn = self._find_turn_for_line(scroll_y)
        if turn is None:
            return None
        offset_within = scroll_y - turn.line_offset
        return (turn.turn_index, offset_within)

    def _restore_anchor(self, anchor: tuple[int, int]):
        """Restore scroll position to anchor turn after re-render."""
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

**NOTE**: Anchor restoration is skipped when `_follow_mode` is True — if the user is following, they want to stay at the bottom, not be anchored to a mid-conversation turn.

### Update get_state/restore_state

```python
    def get_state(self) -> dict:
        return {
            "all_blocks": [td.blocks for td in self._turns],
            "follow_mode": self._follow_mode,
            "selected_turn": self._selected_turn,
            "turn_count": len(self._turns),
        }

    def restore_state(self, state: dict):
        self._pending_restore = state
        self._follow_mode = state.get("follow_mode", True)
        self._selected_turn = state.get("selected_turn", None)
```

## File: src/cc_dump/tui/app.py

### Add keybindings (after existing BINDINGS)

```python
        Binding("f", "toggle_follow", "f|ollow", show=True),
        Binding("j", "next_turn", "next", show=False),
        Binding("k", "prev_turn", "prev", show=False),
        Binding("n", "next_tool_turn", "next tool", show=False),
        Binding("N", "prev_tool_turn", "prev tool", show=False),
        Binding("g", "first_turn", "top", show=False),
        Binding("G", "last_turn", "bottom", show=False),
```

Note: `"N"` and `"G"` (uppercase characters), not `"shift+n"` / `"shift+g"`.

### Add action handlers

```python
    def action_toggle_follow(self):
        self._get_conv().toggle_follow()

    def action_next_turn(self):
        self._get_conv().select_next_turn(forward=True)

    def action_prev_turn(self):
        self._get_conv().select_next_turn(forward=False)

    def action_next_tool_turn(self):
        self._get_conv().next_tool_turn(forward=True)

    def action_prev_tool_turn(self):
        self._get_conv().next_tool_turn(forward=False)

    def action_first_turn(self):
        self._get_conv().jump_to_first()

    def action_last_turn(self):
        self._get_conv().jump_to_last()
```

Pattern follows existing action handlers (lines 399-432 in current app.py).

## Imports needed

In widget_factory.py, add:
```python
from rich.style import Style
```

This is needed for `_SELECTED_STYLE = Style(bgcolor="grey15")`.

## Textual API Reference (verified against installed version)

| API | Signature | Location |
|-----|-----------|----------|
| `watch_scroll_y` | `(self, old_value: float, new_value: float) -> None` | scroll_view.py:52 |
| `is_vertical_scroll_end` | `@property -> bool` | widget.py:1967 |
| `scroll_end` | `(*, animate, speed, duration, easing, force, on_complete, level, immediate, x_axis)` | widget.py:2972 |
| `scroll_to` | `(x, y, *, animate, speed, duration, easing, force, on_complete, level, immediate)` | scroll_view.py:126 |
| `refresh_line` | `(y: int)` | scroll_view.py:168 |
| `refresh_lines` | `(y_start: int, line_count: int = 1)` | scroll_view.py:183 |
| `Click.y` | `@property -> int` (viewport-relative) | events.py:406 |
| `scroll_offset` | `.y -> float` (content offset) | widget.py (Offset named tuple) |

## Research Notes for MEDIUM Confidence Item (Scroll Anchor)

### What to verify:
1. Does `scroll_to(y=N)` take effect immediately after `self.virtual_size = Size(w, h)`?
2. Or does it need `call_later` / `call_after_refresh`?

### How to verify:
Write a minimal test:
```python
from textual.app import App, ComposeResult
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.geometry import Size
from rich.segment import Segment

class TestView(ScrollView):
    def __init__(self):
        super().__init__()
        self._lines = 100
        self.virtual_size = Size(80, self._lines)

    def render_line(self, y):
        scroll_x, scroll_y = self.scroll_offset
        actual_y = scroll_y + y
        return Strip([Segment(f"Line {actual_y}")])

    def key_r(self):
        """Simulate re-render that changes line count."""
        old_scroll = self.scroll_offset.y
        self._lines = 50  # halve content
        self.virtual_size = Size(80, self._lines)
        # Does this work immediately?
        target = min(old_scroll, self._lines - 1)
        self.scroll_to(y=target, animate=False)

class TestApp(App):
    def compose(self) -> ComposeResult:
        yield TestView()

if __name__ == "__main__":
    TestApp().run()
```

Press `r` while scrolled to line 70. If it scrolls to line 49 (last valid), the immediate approach works. If it stays at 70 or shows blank, deferred approach is needed.
