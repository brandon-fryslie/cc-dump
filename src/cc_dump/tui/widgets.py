"""Custom widgets for the TUI interface."""

from textual.widgets import RichLog, Static

# Use module-level imports so hot-reload takes effect
import cc_dump.analysis
import cc_dump.tui.rendering


class ConversationView(RichLog):
    """Scrollable conversation display with support for re-rendering with filters."""

    def __init__(self):
        super().__init__(highlight=False, markup=False, wrap=True)
        self._turn_blocks: list[list] = []  # stored blocks for re-render
        self._current_turn_blocks: list = []  # accumulating current turn

    def append_block(self, block, filters: dict):
        """Append a single block to the current turn."""
        self._current_turn_blocks.append(block)
        rendered = cc_dump.tui.rendering.render_block(block, filters)
        if rendered is not None:
            self.write(rendered)

    def finish_turn(self):
        """Mark the current turn as complete and save for re-render."""
        if self._current_turn_blocks:
            self._turn_blocks.append(self._current_turn_blocks)
            self._current_turn_blocks = []

    def rerender(self, filters: dict):
        """Re-render all stored turns with new filters."""
        self.clear()
        for blocks in self._turn_blocks:
            rendered = cc_dump.tui.rendering.render_blocks(blocks, filters)
            for text in rendered:
                self.write(text)


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
        parts = []
        parts.append("Requests: {}".format(self.request_count))
        parts.append("In: {:,}".format(self.input_tokens))
        parts.append("Out: {:,}".format(self.output_tokens))
        if self.cache_read_tokens > 0:
            total_input = self.input_tokens + self.cache_read_tokens
            hit_pct = (100 * self.cache_read_tokens / total_input) if total_input > 0 else 0
            parts.append("Cache: {:,} ({:.0f}%)".format(self.cache_read_tokens, hit_pct))
        if self.cache_creation_tokens > 0:
            parts.append("Cache Create: {:,}".format(self.cache_creation_tokens))
        models = ", ".join(sorted(self.models_seen)) if self.models_seen else "-"
        parts.append("Models: {}".format(models))

        self.update(" | ".join(parts))


def _fmt_tokens(n: int) -> str:
    """Format token count: 1.2k, 68.9k, etc."""
    if n >= 1000:
        return "{:.1f}k".format(n / 1000)
    return str(n)


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
        if not self._aggregates:
            self.update("Tool Economics: (no tool calls yet)")
            return

        lines = []
        lines.append("Tool Economics (session total):")
        lines.append("  {:<12} {:>5}  {:>8}  {:>8}  {:>8}".format(
            "Tool", "Calls", "Input\u2191", "Results\u2193", "Total"
        ))
        for agg in self._aggregates:
            lines.append("  {:<12} {:>5}  {:>8}  {:>8}  {:>8}".format(
                agg.name[:12],
                agg.calls,
                _fmt_tokens(agg.input_tokens_est) + "t",
                _fmt_tokens(agg.result_tokens_est) + "t",
                _fmt_tokens(agg.total_tokens_est) + "t",
            ))

        self.update("\n".join(lines))


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
        if not self._budgets:
            self.update("Timeline: (no turns yet)")
            return

        lines = []
        lines.append("Timeline:")
        lines.append("  {:>4}  {:>7}  {:>7}  {:>7}  {:>6}  {:>7}  {:>7}".format(
            "Turn", "System", "Tools", "Conv", "Cache%", "Fresh", "\u0394"
        ))
        prev_total = 0
        for i, b in enumerate(self._budgets):
            sys_tok = b.system_tokens_est + b.tool_defs_tokens_est
            conv_tok = b.conversation_tokens_est
            tool_tok = b.tool_use_tokens_est + b.tool_result_tokens_est

            total_actual = b.actual_input_tokens + b.actual_cache_read_tokens
            cache_pct = "{:.0f}%".format(100 * b.actual_cache_read_tokens / total_actual) if total_actual > 0 else "--"
            fresh = _fmt_tokens(b.actual_input_tokens) if b.actual_input_tokens > 0 else "--"

            current_total = b.total_est
            delta = current_total - prev_total if prev_total > 0 else 0
            delta_str = "+{}".format(_fmt_tokens(delta)) if delta > 0 else "--"
            prev_total = current_total

            lines.append("  {:>4}  {:>7}  {:>7}  {:>7}  {:>6}  {:>7}  {:>7}".format(
                i + 1,
                _fmt_tokens(sys_tok),
                _fmt_tokens(tool_tok),
                _fmt_tokens(conv_tok),
                cache_pct,
                fresh,
                delta_str,
            ))

        self.update("\n".join(lines))
