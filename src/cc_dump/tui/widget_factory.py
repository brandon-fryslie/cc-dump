"""Widget factory - creates widget instances that can be hot-swapped.

This module is RELOADABLE. When it reloads, the app can create new widget
instances from the updated class definitions and swap them in.

Widget classes are defined here, not in widgets.py. The widgets.py module
becomes a thin non-reloadable shell that just holds the current instances.
"""

import json
from textual.widgets import RichLog, Static
from rich.text import Text

# Use module-level imports for hot-reload
import cc_dump.analysis
import cc_dump.tui.rendering
import cc_dump.tui.panel_renderers
import cc_dump.db_queries


class ConversationView(RichLog):
    """Scrollable conversation display with support for re-rendering with filters."""

    def __init__(self):
        super().__init__(highlight=False, markup=False, wrap=True)
        self._turn_blocks: list[list] = []  # stored blocks for re-render
        self._current_turn_blocks: list = []  # accumulating current turn
        self._text_delta_buffer: list[str] = []  # accumulate text deltas

    def append_block(self, block, filters: dict):
        """Append a single block to the current turn."""
        from cc_dump.formatting import TextDeltaBlock

        self._current_turn_blocks.append(block)

        if isinstance(block, TextDeltaBlock):
            # Accumulate text deltas in buffer
            self._text_delta_buffer.append(block.text)
        else:
            # Flush any buffered text before rendering non-delta block
            self._flush_text_buffer()

            # Render and write the non-delta block
            rendered = cc_dump.tui.rendering.render_block(block, filters)
            if rendered is not None:
                self.write(rendered)

    def _flush_text_buffer(self):
        """Flush accumulated text deltas as a single write."""
        if self._text_delta_buffer:
            combined_text = "".join(self._text_delta_buffer)
            self.write(Text(combined_text))
            self._text_delta_buffer.clear()

    def finish_turn(self):
        """Mark the current turn as complete and save for re-render."""
        self._flush_text_buffer()  # flush any remaining text
        if self._current_turn_blocks:
            self._turn_blocks.append(self._current_turn_blocks)
            self._current_turn_blocks = []

    def rerender(self, filters: dict):
        """Re-render all stored turns with new filters."""
        from cc_dump.formatting import TextDeltaBlock

        self.clear()
        for blocks in self._turn_blocks:
            text_buffer = []

            for block in blocks:
                if isinstance(block, TextDeltaBlock):
                    text_buffer.append(block.text)
                else:
                    # Flush accumulated text before non-delta block
                    if text_buffer:
                        self.write(Text("".join(text_buffer)))
                        text_buffer.clear()

                    # Render non-delta block
                    rendered = cc_dump.tui.rendering.render_block(block, filters)
                    if rendered is not None:
                        self.write(rendered)

            # Flush any remaining text at end of turn
            if text_buffer:
                self.write(Text("".join(text_buffer)))

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {
            "turn_blocks": self._turn_blocks,
            "current_turn_blocks": self._current_turn_blocks,
            "text_delta_buffer": self._text_delta_buffer,
        }

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self._turn_blocks = state.get("turn_blocks", [])
        self._current_turn_blocks = state.get("current_turn_blocks", [])
        self._text_delta_buffer = state.get("text_delta_buffer", [])


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
