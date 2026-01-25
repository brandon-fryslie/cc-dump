# Implementation Context: textual-tui
Generated: 2026-01-24

## Files to Create
- `src/cc_dump/tui/__init__.py`
- `src/cc_dump/tui/app.py`
- `src/cc_dump/tui/widgets.py`
- `src/cc_dump/tui/rendering.py`
- `src/cc_dump/tui/styles.css`

## Files to Modify
- `pyproject.toml` — add textual dependency
- `src/cc_dump/cli.py` — TUI as default, --no-tui for legacy

## Key Implementation Details

### pyproject.toml change
```toml
dependencies = ["textual>=0.80.0"]
```

### tui/rendering.py

```python
from rich.text import Text
from cc_dump.formatting import (
    FormattedBlock, SeparatorBlock, HeaderBlock, MetadataBlock,
    SystemLabelBlock, TrackedContentBlock, RoleBlock, TextContentBlock,
    ToolUseBlock, ToolResultBlock, ImageBlock, UnknownTypeBlock,
    StreamInfoBlock, StreamToolUseBlock, TextDeltaBlock, StopReasonBlock,
    ErrorBlock, ProxyErrorBlock, LogBlock, NewlineBlock, make_diff_lines,
)

# Rich style equivalents of the ANSI color scheme
ROLE_STYLES = {
    "user": "bold cyan",
    "assistant": "bold green",
    "system": "bold yellow",
}

TAG_STYLES = [
    ("cyan", "on blue"),
    ("black", "on green"),
    ("black", "on yellow"),
    ("white", "on magenta"),
    ("white", "on red"),
    ("white", "on blue"),
    ("black", "on white"),
    ("black", "on cyan"),
]

def render_block(block: FormattedBlock, filters: dict) -> Text | None:
    """Render a FormattedBlock to a Rich Text object. Returns None if filtered out."""
    ...

def render_blocks(blocks: list[FormattedBlock], filters: dict) -> list[Text]:
    """Render a list of blocks, filtering as appropriate."""
    ...
```

### tui/widgets.py

```python
from textual.containers import ScrollableContainer
from textual.widgets import Static, RichLog
from rich.text import Text

class ConversationView(RichLog):
    """Scrollable conversation display."""

    def __init__(self):
        super().__init__(highlight=False, markup=False, wrap=True)
        self._turn_blocks: list[list] = []  # stored blocks for re-render

    def append_turn(self, blocks: list, filters: dict):
        """Append a new turn's blocks."""
        self._turn_blocks.append(blocks)
        rendered = render_blocks(blocks, filters)
        for text in rendered:
            self.write(text)

    def rerender(self, filters: dict):
        """Re-render all stored turns with new filters."""
        self.clear()
        for blocks in self._turn_blocks:
            rendered = render_blocks(blocks, filters)
            for text in rendered:
                self.write(text)

class StatsPanel(Static):
    """Live statistics display."""

    def __init__(self):
        super().__init__("")
        self.request_count = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.models_seen: set = set()

    def update_stats(self, **kwargs):
        self.request_count = kwargs.get("requests", self.request_count)
        self.input_tokens += kwargs.get("input_tokens", 0)
        self.output_tokens += kwargs.get("output_tokens", 0)
        if model := kwargs.get("model"):
            self.models_seen.add(model)
        self._refresh_display()

    def _refresh_display(self):
        self.update(
            f"Requests: {self.request_count} | "
            f"In: {self.input_tokens:,} | Out: {self.output_tokens:,} | "
            f"Models: {', '.join(self.models_seen) or '-'}"
        )
```

### tui/app.py

```python
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Footer, Header
from textual.worker import Worker

class CcDumpApp(App):
    CSS_PATH = "styles.css"

    BINDINGS = [
        Binding("h", "toggle_headers", "Headers", show=True),
        Binding("t", "toggle_tools", "Tools", show=True),
        Binding("a", "toggle_agents", "Agents", show=True),
        Binding("s", "toggle_system", "System", show=True),
        Binding("e", "toggle_expand", "Expand", show=True),
        Binding("m", "toggle_metadata", "Metadata", show=True),
        Binding("p", "toggle_stats", "Stats", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    show_headers = reactive(False)
    show_tools = reactive(True)
    show_agents = reactive(True)
    show_system = reactive(True)
    show_expand = reactive(False)
    show_metadata = reactive(True)
    show_stats = reactive(True)

    def __init__(self, event_queue, state):
        super().__init__()
        self._event_queue = event_queue
        self._state = state

    def compose(self) -> ComposeResult:
        yield Header()
        yield ConversationView()
        yield StatsPanel()
        yield Footer()

    def on_mount(self):
        self.run_worker(self._drain_events, thread=True)
        self.set_interval(1.0, self._check_reload)

    def _drain_events(self):
        """Worker: drain event queue, post to app."""
        while True:
            try:
                event = self._event_queue.get(timeout=0.5)
            except:
                if self._closing:
                    break
                continue
            self.call_from_thread(self._handle_event, event)

    def _handle_event(self, event):
        """Process event on main thread."""
        ...

    @property
    def _filters(self):
        return {
            "headers": self.show_headers,
            "tools": self.show_tools,
            "agents": self.show_agents,
            "system": self.show_system,
            "expand": self.show_expand,
            "metadata": self.show_metadata,
        }

    def watch_show_system(self, value):
        self.query_one(ConversationView).rerender(self._filters)
    # ... similar watchers for other filters
```

### tui/styles.css

```css
Screen {
    layout: vertical;
}

ConversationView {
    height: 1fr;
}

StatsPanel {
    height: 3;
    dock: bottom;
    background: $surface;
    padding: 0 1;
}

Footer {
    dock: bottom;
}
```

### cli.py TUI integration

```python
def main():
    ...
    if args.no_tui:
        # Legacy display loop (current behavior)
        ...
    else:
        # TUI mode
        from cc_dump.tui.app import CcDumpApp
        app = CcDumpApp(display_sub.queue, state)
        app.run()
        router.stop()
        server.shutdown()
```
