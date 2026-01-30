# Implementation Context: widget-arch
Generated: 2026-01-29T12:00:00
Updated: 2026-01-29T18:30:00
Confidence: PARTIALLY READY (HIGH: 6, MEDIUM: 2)
Source: EVALUATION-20260129.md
Plan: SPRINT-20260129-120000-widget-arch-PLAN.md

## Architecture Overview

**Key Insight**: RichLog extends ScrollView (Line API). Content is `list[Strip]`, `render_line(y)` returns one strip per visible line per frame. This is true virtual rendering. ScrollableContainer with Static children does NOT virtualize.

**Revised approach**: ConversationView extends ScrollView. Turns stored as data (`TurnData` with blocks + pre-rendered strips). `render_line(y)` maps virtual line y → turn → strip via offset table. StreamingRichLog (RichLog) handles incremental append during streaming. On finalize, blocks transfer to ConversationView as a new TurnData.

## File: src/cc_dump/tui/rendering.py

### Add BLOCK_FILTER_KEY dict (after line 260, after BLOCK_RENDERERS)

```python
# Mapping: block type -> filter key that controls its visibility.
# None means always visible (never filtered out).
# Used by TurnData.re_render() to skip re-render when irrelevant filters change.
BLOCK_FILTER_KEY: dict[type[FormattedBlock], str | None] = {
    SeparatorBlock: "headers",
    HeaderBlock: "headers",
    MetadataBlock: "metadata",
    TurnBudgetBlock: "expand",
    SystemLabelBlock: "system",
    TrackedContentBlock: "system",
    RoleBlock: "system",             # _render_role checks filters["system"] for system roles
    TextContentBlock: None,
    ToolUseBlock: "tools",
    ToolResultBlock: "tools",
    ImageBlock: None,
    UnknownTypeBlock: None,
    StreamInfoBlock: "metadata",
    StreamToolUseBlock: "tools",
    TextDeltaBlock: None,
    StopReasonBlock: "metadata",
    ErrorBlock: None,
    ProxyErrorBlock: None,
    LogBlock: None,
    NewlineBlock: None,
}
```

### Add render_turn_to_strips helper (after render_blocks at line 281)

```python
def combine_rendered_texts(texts: list[Text]) -> Text:
    """Join rendered Text objects into a single Text with newline separators."""
    if not texts:
        return Text()
    if len(texts) == 1:
        return texts[0]
    combined = Text()
    for i, t in enumerate(texts):
        if i > 0:
            combined.append("\n")
        combined.append(t)
    return combined


def render_turn_to_strips(
    blocks: list[FormattedBlock],
    filters: dict,
    console,
    width: int,
    wrap: bool = True,
) -> list:
    """Render blocks to Strip objects for Line API storage.

    Args:
        blocks: FormattedBlock list for one turn
        filters: Current filter state
        console: Rich Console instance (from app.console)
        width: Render width in cells
        wrap: Enable word wrapping

    Returns:
        list[Strip] — pre-rendered lines for this turn
    """
    from rich.segment import Segment
    from textual.strip import Strip

    texts = render_blocks(blocks, filters)
    if not texts:
        return []

    combined = combine_rendered_texts(texts)

    render_options = console.options
    if not wrap:
        render_options = render_options.update(overflow="ignore", no_wrap=True)
    render_options = render_options.update_width(width)

    segments = console.render(combined, render_options)
    lines = list(Segment.split_lines(segments))

    if not lines:
        return [Strip.blank(width)]

    strips = Strip.from_lines(lines)
    for strip in strips:
        strip.adjust_cell_length(width)
    return strips
```

This mirrors RichLog's `write()` method (lines 175-284 of `_rich_log.py`): render → split_lines → Strip.from_lines → adjust_cell_length.

## File: src/cc_dump/tui/widget_factory.py

### Imports to change (line 2)

Current:
```python
from textual.widgets import RichLog, Static
```

New (keep RichLog for LogsPanel at line 325 and StreamingRichLog):
```python
from textual.widgets import RichLog, Static
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.cache import LRUCache
from textual.geometry import Size
```

### Add TurnData dataclass (before ConversationView)

```python
from dataclasses import dataclass, field


@dataclass
class TurnData:
    """Pre-rendered turn data for Line API storage."""
    turn_index: int
    blocks: list             # list[FormattedBlock] - source of truth
    strips: list             # list[Strip] - pre-rendered lines
    relevant_filter_keys: set = field(default_factory=set)
    line_offset: int = 0     # start line in virtual space
    _last_filter_snapshot: dict = field(default_factory=dict)

    @property
    def line_count(self) -> int:
        return len(self.strips)

    def compute_relevant_keys(self):
        """Compute which filter keys affect this turn's blocks."""
        keys = set()
        for block in self.blocks:
            key = cc_dump.tui.rendering.BLOCK_FILTER_KEY.get(type(block))
            if key is not None:
                keys.add(key)
        self.relevant_filter_keys = keys

    def re_render(self, filters: dict, console, width: int) -> bool:
        """Re-render if a relevant filter changed. Returns True if strips changed."""
        snapshot = {k: filters.get(k, False) for k in self.relevant_filter_keys}
        if snapshot == self._last_filter_snapshot:
            return False
        self._last_filter_snapshot = snapshot
        self.strips = cc_dump.tui.rendering.render_turn_to_strips(
            self.blocks, filters, console, width
        )
        return True
```

### Add StreamingRichLog class (after TurnData)

```python
class StreamingRichLog(RichLog):
    """RichLog used for in-progress streaming turns.

    Accumulates FormattedBlock list alongside RichLog's native append.
    On finalize(), returns blocks for conversion to TurnData.
    """

    def __init__(self):
        super().__init__(highlight=False, markup=False, wrap=True)
        self._blocks: list = []
        self._text_delta_buffer: list[str] = []
        self.display = False

    def append_block(self, block, filters: dict):
        """Append a block, writing to RichLog for immediate display."""
        from cc_dump.formatting import TextDeltaBlock

        self._blocks.append(block)
        self.display = True

        if isinstance(block, TextDeltaBlock):
            self._text_delta_buffer.append(block.text)
        else:
            # Flush text buffer first
            self._flush_text_buffer()
            rendered = cc_dump.tui.rendering.render_block(block, filters)
            if rendered is not None:
                self.write(rendered)

    def _flush_text_buffer(self):
        if self._text_delta_buffer:
            from rich.text import Text as RichText
            combined = "".join(self._text_delta_buffer)
            self.write(RichText(combined))
            self._text_delta_buffer.clear()

    def finalize(self) -> list:
        """Return accumulated blocks, clear state, hide widget."""
        self._flush_text_buffer()
        blocks = self._blocks
        self._blocks = []
        self._text_delta_buffer = []
        self.clear()
        self.display = False
        return blocks

    def get_state(self) -> dict:
        return {
            "blocks": list(self._blocks),
            "text_delta_buffer": list(self._text_delta_buffer),
        }

    def restore_state(self, state: dict):
        self._blocks = state.get("blocks", [])
        self._text_delta_buffer = state.get("text_delta_buffer", [])
```

### Rewrite ConversationView (replace lines 21-101)

```python
class ConversationView(ScrollView):
    """Virtual-rendering conversation display using Line API.

    Stores turns as TurnData (blocks + pre-rendered strips).
    render_line(y) maps virtual line y to the correct turn's strip.
    Only visible lines are rendered per frame.
    """

    DEFAULT_CSS = """
    ConversationView {
        background: $surface;
        color: $foreground;
        overflow-y: scroll;
        &:focus {
            background-tint: $foreground 5%;
        }
    }
    """

    def __init__(self):
        super().__init__()
        self._turns: list[TurnData] = []
        self._total_lines: int = 0
        self._widest_line: int = 0
        self._line_cache: LRUCache = LRUCache(1024)
        self._last_filters: dict = {}
        self._last_width: int = 78
        self._follow_mode: bool = True
        self._pending_restore: dict | None = None

    def render_line(self, y: int) -> Strip:
        """Line API: render a single line at virtual position y."""
        scroll_x, scroll_y = self.scroll_offset
        actual_y = scroll_y + y
        width = self.scrollable_content_region.width

        if actual_y >= self._total_lines:
            return Strip.blank(width, self.rich_style)

        key = (actual_y, scroll_x, width, self._widest_line)
        if key in self._line_cache:
            return self._line_cache[key].apply_style(self.rich_style)

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

        self._line_cache[key] = strip
        return strip.apply_style(self.rich_style)

    def _find_turn_for_line(self, line_y: int) -> TurnData | None:
        """Binary search for turn containing virtual line y."""
        turns = self._turns
        if not turns:
            return None
        lo, hi = 0, len(turns) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            turn = turns[mid]
            if line_y < turn.line_offset:
                hi = mid - 1
            elif line_y >= turn.line_offset + turn.line_count:
                lo = mid + 1
            else:
                return turn
        return None

    def _recalculate_offsets(self):
        """Rebuild line offsets and virtual size."""
        offset = 0
        widest = 0
        for turn in self._turns:
            turn.line_offset = offset
            offset += turn.line_count
            for strip in turn.strips:
                w = strip.cell_length
                if w > widest:
                    widest = w
        self._total_lines = offset
        self._widest_line = max(widest, self._last_width)
        self.virtual_size = Size(self._widest_line, self._total_lines)
        self._line_cache.clear()

    def append_block(self, block, filters: dict):
        """Delegate to StreamingRichLog (managed by app layout)."""
        self._last_filters = filters
        # StreamingRichLog is a sibling widget, not managed here.
        # This method exists for API compatibility; the app routes
        # append_block to the StreamingRichLog directly.
        # See app.py _handle_event for routing.
        pass

    def finish_turn(self, filters=None):
        """Add a finalized turn from blocks."""
        # Called by app after StreamingRichLog.finalize() returns blocks
        pass

    def add_turn(self, blocks: list, filters: dict = None):
        """Add a completed turn from block list."""
        if filters is None:
            filters = self._last_filters
        width = self.scrollable_content_region.width if self._size_known else self._last_width
        console = self.app.console

        td = TurnData(
            turn_index=len(self._turns),
            blocks=blocks,
            strips=cc_dump.tui.rendering.render_turn_to_strips(
                blocks, filters, console, width
            ),
        )
        td.compute_relevant_keys()
        td._last_filter_snapshot = {
            k: filters.get(k, False) for k in td.relevant_filter_keys
        }
        self._turns.append(td)
        self._recalculate_offsets()

        if self._follow_mode:
            self.scroll_end(animate=False, immediate=False, x_axis=False)

    def rerender(self, filters: dict):
        """Re-render affected turns in place. Preserves scroll position."""
        self._last_filters = filters

        # Rebuild from pending restore if needed
        if self._pending_restore is not None:
            self._rebuild_from_state(filters)
            return

        width = self.scrollable_content_region.width if self._size_known else self._last_width
        console = self.app.console
        changed = False
        for td in self._turns:
            if td.re_render(filters, console, width):
                changed = True
        if changed:
            self._recalculate_offsets()

    def _rebuild_from_state(self, filters: dict):
        """Rebuild from restored state."""
        state = self._pending_restore
        self._pending_restore = None
        self._turns.clear()
        for block_list in state.get("all_blocks", []):
            self.add_turn(block_list, filters)

    @property
    def _size_known(self) -> bool:
        return self.size.width > 0

    def on_resize(self, event):
        """Re-render all strips at new width."""
        width = self.scrollable_content_region.width
        if width != self._last_width and width > 0:
            self._last_width = width
            console = self.app.console
            for td in self._turns:
                td.strips = cc_dump.tui.rendering.render_turn_to_strips(
                    td.blocks, self._last_filters, console, width
                )
            self._recalculate_offsets()

    def get_state(self) -> dict:
        return {
            "all_blocks": [td.blocks for td in self._turns],
            "follow_mode": self._follow_mode,
            "turn_count": len(self._turns),
        }

    def restore_state(self, state: dict):
        self._pending_restore = state
        self._follow_mode = state.get("follow_mode", True)
```

**NOTE**: The public API changes slightly. `append_block()` and `finish_turn()` on ConversationView become stubs — the app will route streaming to StreamingRichLog and call `conv.add_turn(blocks, filters)` after finalize. This is a MEDIUM-confidence item that needs the app.py routing to be designed.

### Factory function updates

```python
def create_conversation_view() -> ConversationView:
    return ConversationView()

def create_streaming_richlog() -> StreamingRichLog:
    return StreamingRichLog()
```

## File: src/cc_dump/tui/event_handlers.py

### Updated routing pattern

**Key principle: visibility is a view concern, not a lifecycle concern.** Turn creation (`add_turn`) and filter application (`rerender`) are independent operations. Turns are created with all blocks. The rendering path consults current filters at render time.

The `widgets` dict gains a `"streaming"` key pointing to the StreamingRichLog.

```python
# In handle_request (non-streaming — all blocks arrive at once):
blocks = cc_dump.formatting.format_request(body, state)
conv = widgets["conv"]
conv.add_turn(blocks)  # No filters — TurnData stores all blocks, renders at current filter state

# In handle_response_event (streaming):
streaming = widgets["streaming"]
filters = widgets["filters"]
blocks = cc_dump.formatting.format_response_event(event_type, data)
for block in blocks:
    streaming.append_block(block, filters)  # filters only for immediate RichLog display

# In handle_response_done:
streaming = widgets["streaming"]
conv = widgets["conv"]
blocks = streaming.finalize()
if blocks:
    conv.add_turn(blocks)  # No filters — same principle

# In handle_error / handle_proxy_error:
block = cc_dump.formatting.ErrorBlock(code=code, reason=reason)
conv = widgets["conv"]
conv.add_turn([block])
```

The `conv.add_turn(blocks)` method internally renders blocks to strips using the ConversationView's `_last_filters` (set by the most recent `rerender()` call from the reactive watchers). This decouples turn lifecycle from filter state.

## File: src/cc_dump/tui/styles.css

### Remove old ConversationView rule, rely on DEFAULT_CSS

The ConversationView now has `DEFAULT_CSS` inline (see class above). The external CSS can override:

```css
ConversationView {
    height: 1fr;
    border: solid $primary;
}

StreamingRichLog {
    height: auto;
    max-height: 50%;
    border: solid $accent;
}
```

## File: src/cc_dump/tui/app.py

### compose() changes

```python
def compose(self) -> ComposeResult:
    yield Header()
    conv = cc_dump.tui.widget_factory.create_conversation_view()
    conv.id = self._conv_id
    yield conv

    streaming = cc_dump.tui.widget_factory.create_streaming_richlog()
    streaming.id = "streaming-richlog"
    yield streaming

    # ... rest unchanged
```

### Widget accessor additions

```python
def _get_streaming(self):
    return self.query_one("#streaming-richlog")
```

### _handle_event_inner changes

Add `"streaming": self._get_streaming()` to the widgets dict.

## Codebase Patterns to Follow

### Module-level import pattern (widget_factory.py lines 14-18)
```python
import cc_dump.tui.rendering
```
Used as `cc_dump.tui.rendering.render_block(...)` to enable hot-reload.

### Block type checking pattern (widget_factory.py line 36)
```python
from cc_dump.formatting import TextDeltaBlock
isinstance(block, TextDeltaBlock)
```
Uses local import inside method body.

### ScrollView/Line API reference
See `_rich_log.py` (lines 47-321 in Textual source) for the canonical pattern:
- `render_line(y)` with LRU cache
- `virtual_size` management
- `_start_line` offset tracking
- Deferred rendering until size is known
