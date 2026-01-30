# Implementation Context: scroll-nav
Generated: 2026-01-29T13:00:00
Confidence: HIGH: 5, MEDIUM: 1
Source: EVALUATION-20260129.md
Plan: SPRINT-20260129-130000-scroll-nav-PLAN.md

## File: src/cc_dump/tui/widget_factory.py

### Add TurnSelected message (top of file, after imports)

```python
from textual.message import Message

class TurnSelected(Message):
    """Posted when a turn is selected (click or navigation)."""
    def __init__(self, turn_index: int):
        super().__init__()
        self.turn_index = turn_index
```

Pattern: Textual messages inherit from `Message` and call `super().__init__()`.

### Add on_click to TurnWidget

Add to the `TurnWidget` class (created in Sprint 1):

```python
    def on_click(self):
        """Post selection message when clicked."""
        turn_index = int(self.id.split("-")[1])
        self.post_message(TurnSelected(turn_index))
```

Store `_turn_index` in constructor for cleaner access:
```python
    def __init__(self, blocks, filters, turn_index):
        super().__init__("")
        self.id = f"turn-{turn_index}"
        self._turn_index = turn_index
        # ... rest of init
```

### Add follow mode to ConversationView

Add to `__init__`:
```python
        self._follow_mode = True
        self._selected_turn: int | None = None
```

Add methods:
```python
    def toggle_follow(self):
        """Toggle follow mode."""
        self._follow_mode = not self._follow_mode
        if self._follow_mode:
            self.scroll_end(animate=False)

    def scroll_to_bottom(self):
        """Scroll to bottom and enable follow mode."""
        self._follow_mode = True
        self.scroll_end(animate=False)

    def watch_scroll_y(self, value: float):
        """Detect manual scroll away from bottom."""
        if not self.is_vertical_scroll_end:
            self._follow_mode = False

    def _auto_scroll(self):
        """Scroll to bottom if follow mode is enabled."""
        if self._follow_mode:
            self.scroll_end(animate=False)
```

Call `self._auto_scroll()` at the end of `finish_turn()`.

For streaming auto-scroll: modify `StreamingTurnWidget._flush()` to post a message or have ConversationView call `_auto_scroll()` on a watcher. Simplest: override `on_static_changed` or use `call_later`:

```python
    # In StreamingTurnWidget._flush, after self.update():
    def _flush(self):
        # ... existing flush logic ...
        if parts:
            combined = cc_dump.tui.rendering.combine_rendered_texts(parts)
            self.update(combined)
            # Signal parent to auto-scroll
            self.post_message(self.ContentUpdated())

    class ContentUpdated(Message):
        """Internal message: streaming content was updated."""
        pass
```

Then in ConversationView:
```python
    def on_streaming_turn_widget_content_updated(self, message):
        self._auto_scroll()
```

### Add selection management to ConversationView

```python
    def select_turn(self, turn_index: int):
        """Select a turn by index."""
        # Deselect previous
        if self._selected_turn is not None:
            try:
                old = self.query_one(f"#turn-{self._selected_turn}")
                old.remove_class("selected")
            except Exception:
                pass
        # Select new
        self._selected_turn = turn_index
        try:
            new = self.query_one(f"#turn-{turn_index}")
            new.add_class("selected")
            new.scroll_visible()
        except Exception:
            pass

    def on_turn_selected(self, message: TurnSelected):
        """Handle turn selection from click."""
        self.select_turn(message.turn_index)

    def select_next_turn(self, forward: bool = True):
        """Select the next/prev visible turn."""
        turns = [tw for tw in self.query(TurnWidget) if tw.display]
        if not turns:
            return
        self._follow_mode = False
        if self._selected_turn is None:
            idx = 0 if forward else len(turns) - 1
        else:
            current_indices = [int(tw.id.split("-")[1]) for tw in turns]
            try:
                pos = current_indices.index(self._selected_turn)
                idx = pos + (1 if forward else -1)
                idx = max(0, min(idx, len(turns) - 1))
            except ValueError:
                idx = 0
        turn_index = int(turns[idx].id.split("-")[1])
        self.select_turn(turn_index)

    def next_turn_of_type(self, forward: bool = True):
        """Select next/prev turn containing tool blocks."""
        from cc_dump.formatting import ToolUseBlock, ToolResultBlock, StreamToolUseBlock
        tool_types = (ToolUseBlock, ToolResultBlock, StreamToolUseBlock)

        turns = [tw for tw in self.query(TurnWidget) if tw.display]
        if not turns:
            return
        self._follow_mode = False

        # Find turns with tool blocks
        tool_turns = []
        for tw in turns:
            if any(isinstance(b, tool_types) for b in tw._blocks):
                tool_turns.append(tw)
        if not tool_turns:
            return

        if self._selected_turn is None:
            target = tool_turns[0] if forward else tool_turns[-1]
        else:
            indices = [int(tw.id.split("-")[1]) for tw in tool_turns]
            if forward:
                later = [i for i, idx in enumerate(indices) if idx > self._selected_turn]
                target = tool_turns[later[0]] if later else tool_turns[0]
            else:
                earlier = [i for i, idx in enumerate(indices) if idx < self._selected_turn]
                target = tool_turns[earlier[-1]] if earlier else tool_turns[-1]

        self.select_turn(int(target.id.split("-")[1]))

    def jump_to_first(self):
        """Select first visible turn."""
        turns = [tw for tw in self.query(TurnWidget) if tw.display]
        if turns:
            self._follow_mode = False
            self.select_turn(int(turns[0].id.split("-")[1]))

    def jump_to_last(self):
        """Select last visible turn."""
        turns = [tw for tw in self.query(TurnWidget) if tw.display]
        if turns:
            self.select_turn(int(turns[-1].id.split("-")[1]))
            self._follow_mode = True
            self.scroll_end(animate=False)
```

### Add scroll anchor to rerender (MEDIUM confidence)

Modify existing `rerender()`:
```python
    def rerender(self, filters: dict):
        """Re-render with scroll anchor preservation."""
        self._last_filters = filters
        if self._pending_restore_state is not None:
            self._rebuild_from_state(filters)
            return
        anchor = self._find_viewport_anchor()
        for tw in self.query(TurnWidget):
            tw.apply_filters(filters)
        if anchor is not None:
            self.call_after_refresh(self._restore_anchor, anchor)

    def _find_viewport_anchor(self) -> int | None:
        """Find the first visible TurnWidget in the viewport."""
        scroll_y = self.scroll_y
        viewport_bottom = scroll_y + self.size.height
        for tw in self.query(TurnWidget):
            if not tw.display:
                continue
            # widget.region.y is relative to container content space
            if tw.region.y + tw.region.height > scroll_y and tw.region.y < viewport_bottom:
                return int(tw.id.split("-")[1])
        return None

    def _restore_anchor(self, turn_index: int):
        """Scroll anchor turn back into view after filter change."""
        try:
            tw = self.query_one(f"#turn-{turn_index}")
            tw.scroll_visible(animate=False)
        except Exception:
            pass
```

NOTE: `call_after_refresh` ensures layout is recomputed before scrolling. This is the MEDIUM confidence item -- if `call_after_refresh` does not exist on ScrollableContainer, use `self.call_later` or `self.set_timer(0.01, ...)`.

### Add follow_mode to get_state/restore_state

In `get_state()`, add:
```python
    "follow_mode": self._follow_mode,
    "selected_turn": self._selected_turn,
```

In `restore_state()`, add:
```python
    self._follow_mode = state.get("follow_mode", True)
    self._selected_turn = state.get("selected_turn", None)
```

## File: src/cc_dump/tui/app.py

### Add keybindings (after existing BINDINGS, around line 36)

```python
        Binding("f", "toggle_follow", "f|ollow", show=True),
        Binding("j", "next_turn", "next", show=False),
        Binding("k", "prev_turn", "prev", show=False),
        Binding("n", "next_tool_turn", "next tool", show=False),
        Binding("N", "prev_tool_turn", "prev tool", show=False),
        Binding("g", "first_turn", "top", show=False),
        Binding("G", "last_turn", "bottom", show=False),
```

Note: Use `"N"` (uppercase) for shift+n and `"G"` for shift+g. Textual uses the character itself, not `shift+` prefix for letter keys.

### Add action handlers (after existing action methods, around line 433)

```python
    def action_toggle_follow(self):
        self._get_conv().toggle_follow()

    def action_next_turn(self):
        self._get_conv().select_next_turn(forward=True)

    def action_prev_turn(self):
        self._get_conv().select_next_turn(forward=False)

    def action_next_tool_turn(self):
        self._get_conv().next_turn_of_type(forward=True)

    def action_prev_tool_turn(self):
        self._get_conv().next_turn_of_type(forward=False)

    def action_first_turn(self):
        self._get_conv().jump_to_first()

    def action_last_turn(self):
        self._get_conv().jump_to_last()
```

Pattern follows existing action handlers (lines 399-432).

## File: src/cc_dump/tui/styles.css

### Add .selected rule (after TurnWidget rule added in Sprint 1)

```css
TurnWidget.selected {
    background: $surface-darken-1;
    border-left: tall $accent;
}
```

Pattern: Textual CSS class selectors use `WidgetType.classname` syntax. `$surface-darken-1` is a Textual design system variable. `tall` is a Textual border style (2-char wide).

## File: src/cc_dump/tui/widgets.py

### Add TurnSelected to re-exports

```python
from cc_dump.tui.widget_factory import (
    ConversationView,
    TurnWidget,
    StreamingTurnWidget,
    TurnSelected,
    # ... rest
)
```

Add `"TurnSelected"` to `__all__`.

## Research Notes for MEDIUM Confidence Item (Scroll Anchor)

### What to verify:
1. `widget.region` on a child of ScrollableContainer -- is `.y` relative to the container's content space or the screen?
2. `self.scroll_y` on ScrollableContainer -- is it the pixel offset into the content?
3. `call_after_refresh` -- does it exist on Widget? Alternative: `call_later`.
4. Does `scroll_to_widget` / `scroll_visible` work correctly after `apply_filters` changes widget visibility?

### How to verify:
Write a minimal test script:
```python
from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer
from textual.widgets import Static

class TestApp(App):
    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="sc"):
            for i in range(50):
                yield Static(f"Item {i}", id=f"item-{i}")

    def on_mount(self):
        sc = self.query_one("#sc")
        item25 = self.query_one("#item-25")
        self.log(f"scroll_y: {sc.scroll_y}")
        self.log(f"item25.region: {item25.region}")
        self.log(f"has call_after_refresh: {hasattr(sc, 'call_after_refresh')}")
```

Run with `textual run` to inspect output.
