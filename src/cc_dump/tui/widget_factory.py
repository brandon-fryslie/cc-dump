"""Widget factory - creates widget instances that can be hot-swapped.

This module is RELOADABLE. When it reloads, the app can create new widget
instances from the updated class definitions and swap them in.

Widget classes are defined here, not in widgets.py. The widgets.py module
becomes a thin non-reloadable shell that just holds the current instances.
"""

import json
from dataclasses import dataclass, field
from textual.widgets import RichLog, Static
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.cache import LRUCache
from textual.geometry import Size
from rich.text import Text

# Use module-level imports for hot-reload
import cc_dump.analysis
import cc_dump.tui.rendering
import cc_dump.tui.panel_renderers
import cc_dump.db_queries


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


class StatsPanel(Static):
    """Live statistics display showing request counts, tokens, and models.

    Queries database as single source of truth for token counts.
    Only tracks request_count and models_seen in memory (not in DB).
    """

    def __init__(self):
        super().__init__("")
        self.request_count = 0
        self.models_seen: set = set()

    def update_stats(self, **kwargs):
        """Update statistics and refresh display.

        Only updates in-memory fields (requests, models).
        Token counts come from database via refresh_from_db().
        """
        if "requests" in kwargs:
            self.request_count = kwargs["requests"]
        if "model" in kwargs and kwargs["model"]:
            self.models_seen.add(kwargs["model"])

        # No longer accumulating token counts here - they come from DB

    def refresh_from_db(self, db_path: str, session_id: str, current_turn: dict = None):
        """Refresh token counts from database.

        Args:
            db_path: Path to SQLite database
            session_id: Session identifier
            current_turn: Optional dict with in-progress turn data to merge for real-time display
        """
        if not db_path or not session_id:
            # No database - show only in-memory fields
            self._refresh_display(0, 0, 0, 0)
            return

        stats = cc_dump.db_queries.get_session_stats(db_path, session_id, current_turn)
        self._refresh_display(
            stats["input_tokens"],
            stats["output_tokens"],
            stats["cache_read_tokens"],
            stats["cache_creation_tokens"],
        )

    def _refresh_display(self, input_tokens: int, output_tokens: int,
                        cache_read_tokens: int, cache_creation_tokens: int):
        """Rebuild the display text."""
        text = cc_dump.tui.panel_renderers.render_stats_panel(
            self.request_count,
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_creation_tokens,
            self.models_seen,
        )
        self.update(text)

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {
            "request_count": self.request_count,
            "models_seen": set(self.models_seen),
        }

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self.request_count = state.get("request_count", 0)
        self.models_seen = state.get("models_seen", set())
        # Trigger display refresh (will need DB query to get token counts)
        self._refresh_display(0, 0, 0, 0)


class ToolEconomicsPanel(Static):
    """Panel showing per-tool token usage aggregates.

    Queries database as single source of truth.
    """

    def __init__(self):
        super().__init__("")

    def refresh_from_db(self, db_path: str, session_id: str):
        """Refresh panel data from database.

        Args:
            db_path: Path to SQLite database
            session_id: Session identifier
        """
        if not db_path or not session_id:
            self._refresh_display([])
            return

        # Query tool invocations from database
        invocations = cc_dump.db_queries.get_tool_invocations(db_path, session_id)

        # Aggregate using existing analysis function
        aggregates = cc_dump.analysis.aggregate_tools(invocations)

        self._refresh_display(aggregates)

    def _refresh_display(self, aggregates: list[cc_dump.analysis.ToolAggregates]):
        """Rebuild the economics table."""
        text = cc_dump.tui.panel_renderers.render_economics_panel(aggregates)
        self.update(text)

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {}  # No state to preserve - queries DB on demand

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self._refresh_display([])


class TimelinePanel(Static):
    """Panel showing per-turn context growth over time.

    Queries database as single source of truth.
    """

    def __init__(self):
        super().__init__("")

    def refresh_from_db(self, db_path: str, session_id: str):
        """Refresh panel data from database.

        Args:
            db_path: Path to SQLite database
            session_id: Session identifier
        """
        if not db_path or not session_id:
            self._refresh_display([])
            return

        # Query turn timeline from database
        turn_data = cc_dump.db_queries.get_turn_timeline(db_path, session_id)

        # Reconstruct TurnBudget objects from database data
        budgets = []
        for row in turn_data:
            # Parse request JSON to compute budget estimates
            request_json = row["request_json"]
            request_body = json.loads(request_json) if request_json else {}

            budget = cc_dump.analysis.compute_turn_budget(request_body)

            # Fill in actual token counts from database
            budget.actual_input_tokens = row["input_tokens"]
            budget.actual_cache_read_tokens = row["cache_read_tokens"]
            budget.actual_cache_creation_tokens = row["cache_creation_tokens"]
            budget.actual_output_tokens = row["output_tokens"]

            budgets.append(budget)

        self._refresh_display(budgets)

    def _refresh_display(self, budgets: list[cc_dump.analysis.TurnBudget]):
        """Rebuild the timeline table."""
        text = cc_dump.tui.panel_renderers.render_timeline_panel(budgets)
        self.update(text)

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {}  # No state to preserve - queries DB on demand

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self._refresh_display([])


class FilterStatusBar(Static):
    """Status bar showing which filters are currently active with colored indicators."""

    def __init__(self):
        # Initialize with placeholder text so widget is visible
        super().__init__("Active: (initializing...)")

    def update_filters(self, filters: dict):
        """Update the status bar to show active filters.

        Args:
            filters: Dict with filter states (headers, tools, system, expand, metadata)
        """
        from rich.text import Text

        # Filter names and their colors (matching FILTER_INDICATORS in rendering.py)
        filter_info = [
            ("h", "Headers", "cyan", filters.get("headers", False)),
            ("t", "Tools", "blue", filters.get("tools", False)),
            ("s", "System", "yellow", filters.get("system", False)),
            ("e", "Context", "green", filters.get("expand", False)),
            ("m", "Metadata", "magenta", filters.get("metadata", False)),
        ]

        text = Text()
        text.append("Active: ", style="dim")

        active_filters = [(key, name, color) for key, name, color, active in filter_info if active]

        if not active_filters:
            text.append("none", style="dim")
        else:
            for i, (key, name, color) in enumerate(active_filters):
                if i > 0:
                    text.append(" ", style="dim")
                # Add colored indicator bar
                text.append("▌", style=f"bold {color}")
                text.append(f"{name}", style=color)

        self.update(text)

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {}

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        pass


class LogsPanel(RichLog):
    """Panel showing cc-dump application logs (debug, errors, internal messages)."""

    def __init__(self):
        super().__init__(highlight=False, markup=False, wrap=True, max_lines=1000)

    def log(self, level: str, message: str):
        """Add an application log entry.

        Args:
            level: Log level (DEBUG, INFO, WARNING, ERROR)
            message: Log message
        """
        from rich.text import Text
        import datetime

        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

        log_text = Text()
        log_text.append(f"[{timestamp}] ", style="dim")

        # Color-code by level
        if level == "ERROR":
            log_text.append(f"{level:7s} ", style="bold red")
        elif level == "WARNING":
            log_text.append(f"{level:7s} ", style="bold yellow")
        elif level == "INFO":
            log_text.append(f"{level:7s} ", style="bold cyan")
        else:  # DEBUG
            log_text.append(f"{level:7s} ", style="dim")

        log_text.append(message)
        self.write(log_text)

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {}  # Logs don't need to be preserved across hot-reload

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        pass  # Nothing to restore


# Factory functions for creating widgets
def create_conversation_view() -> ConversationView:
    """Create a new ConversationView instance."""
    return ConversationView()


def create_streaming_richlog() -> StreamingRichLog:
    """Create a new StreamingRichLog instance."""
    return StreamingRichLog()


def create_stats_panel() -> StatsPanel:
    """Create a new StatsPanel instance."""
    return StatsPanel()


def create_economics_panel() -> ToolEconomicsPanel:
    """Create a new ToolEconomicsPanel instance."""
    return ToolEconomicsPanel()


def create_timeline_panel() -> TimelinePanel:
    """Create a new TimelinePanel instance."""
    return TimelinePanel()


def create_logs_panel() -> LogsPanel:
    """Create a new LogsPanel instance."""
    return LogsPanel()


def create_filter_status_bar() -> FilterStatusBar:
    """Create a new FilterStatusBar instance."""
    return FilterStatusBar()
