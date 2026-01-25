"""Widget factory - creates widget instances that can be hot-swapped.

This module is RELOADABLE. When it reloads, the app can create new widget
instances from the updated class definitions and swap them in.

Widget classes are defined here, not in widgets.py. The widgets.py module
becomes a thin non-reloadable shell that just holds the current instances.
"""

from textual.widgets import RichLog, Static
from rich.text import Text

# Use module-level imports for hot-reload
import cc_dump.analysis
import cc_dump.tui.rendering
import cc_dump.tui.panel_renderers
import cc_dump.tui.protocols


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
    """Live statistics display showing request counts, tokens, and models."""

    def __init__(self):
        super().__init__("")
        self.request_count = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_creation_tokens = 0
        self.models_seen: set = set()

    def update_stats(self, **kwargs):
        """Update statistics and refresh display."""
        if "requests" in kwargs:
            self.request_count = kwargs["requests"]
        if "input_tokens" in kwargs:
            self.input_tokens += kwargs["input_tokens"]
        if "output_tokens" in kwargs:
            self.output_tokens += kwargs["output_tokens"]
        if "cache_read_tokens" in kwargs:
            self.cache_read_tokens += kwargs["cache_read_tokens"]
        if "cache_creation_tokens" in kwargs:
            self.cache_creation_tokens += kwargs["cache_creation_tokens"]
        if "model" in kwargs and kwargs["model"]:
            self.models_seen.add(kwargs["model"])

        self._refresh_display()

    def _refresh_display(self):
        """Rebuild the display text."""
        text = cc_dump.tui.panel_renderers.render_stats_panel(
            self.request_count,
            self.input_tokens,
            self.output_tokens,
            self.cache_read_tokens,
            self.cache_creation_tokens,
            self.models_seen,
        )
        self.update(text)

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {
            "request_count": self.request_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "models_seen": set(self.models_seen),
        }

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self.request_count = state.get("request_count", 0)
        self.input_tokens = state.get("input_tokens", 0)
        self.output_tokens = state.get("output_tokens", 0)
        self.cache_read_tokens = state.get("cache_read_tokens", 0)
        self.cache_creation_tokens = state.get("cache_creation_tokens", 0)
        self.models_seen = state.get("models_seen", set())
        self._refresh_display()


class ToolEconomicsPanel(Static):
    """Panel showing per-tool token usage aggregates."""

    def __init__(self):
        super().__init__("")
        self._aggregates: list[cc_dump.analysis.ToolAggregates] = []

    def update_data(self, aggregates: list[cc_dump.analysis.ToolAggregates]):
        """Update with new aggregate data."""
        self._aggregates = aggregates
        self._refresh_display()

    def _refresh_display(self):
        """Rebuild the economics table."""
        text = cc_dump.tui.panel_renderers.render_economics_panel(self._aggregates)
        self.update(text)

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {"aggregates": self._aggregates}

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self._aggregates = state.get("aggregates", [])
        self._refresh_display()


class TimelinePanel(Static):
    """Panel showing per-turn context growth over time."""

    def __init__(self):
        super().__init__("")
        self._budgets: list[cc_dump.analysis.TurnBudget] = []

    def update_data(self, budgets: list[cc_dump.analysis.TurnBudget]):
        """Update with new budget timeline data."""
        self._budgets = list(budgets)
        self._refresh_display()

    def _refresh_display(self):
        """Rebuild the timeline table."""
        text = cc_dump.tui.panel_renderers.render_timeline_panel(self._budgets)
        self.update(text)

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {"budgets": self._budgets}

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self._budgets = state.get("budgets", [])
        self._refresh_display()


# Factory functions for creating widgets
def create_conversation_view() -> cc_dump.tui.protocols.HotSwappableWidget:
    """Create a new ConversationView instance."""
    return ConversationView()


def create_stats_panel() -> cc_dump.tui.protocols.HotSwappableWidget:
    """Create a new StatsPanel instance."""
    return StatsPanel()


def create_economics_panel() -> cc_dump.tui.protocols.HotSwappableWidget:
    """Create a new ToolEconomicsPanel instance."""
    return ToolEconomicsPanel()


def create_timeline_panel() -> cc_dump.tui.protocols.HotSwappableWidget:
    """Create a new TimelinePanel instance."""
    return TimelinePanel()
