"""Main TUI application using Textual."""

import queue

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Footer, Header

from cc_dump.analysis import (
    TurnBudget, correlate_tools, aggregate_tools, ToolInvocation,
)
from cc_dump.tui.widgets import ConversationView, StatsPanel, ToolEconomicsPanel, TimelinePanel
from cc_dump.formatting import (
    format_request, format_response_event,
    StreamInfoBlock, TurnBudgetBlock,
)


class CcDumpApp(App):
    """TUI application for cc-dump."""

    CSS_PATH = "styles.css"

    BINDINGS = [
        Binding("h", "toggle_headers", "Headers", show=True),
        Binding("t", "toggle_tools", "Tools", show=True),
        Binding("s", "toggle_system", "System", show=True),
        Binding("e", "toggle_expand", "Context", show=True),
        Binding("m", "toggle_metadata", "Metadata", show=True),
        Binding("p", "toggle_stats", "Stats", show=True),
        Binding("x", "toggle_economics", "Economics", show=True),
        Binding("l", "toggle_timeline", "Timeline", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    show_headers = reactive(False)
    show_tools = reactive(True)
    show_system = reactive(True)
    show_expand = reactive(False)
    show_metadata = reactive(True)
    show_stats = reactive(True)
    show_economics = reactive(False)
    show_timeline = reactive(False)

    def __init__(self, event_queue, state, router):
        super().__init__()
        self._event_queue = event_queue
        self._state = state
        self._router = router
        self._closing = False
        # Track budgets per turn for timeline
        self._turn_budgets: list[TurnBudget] = []
        self._current_budget: TurnBudget | None = None
        # Track all tool invocations for economics
        self._all_invocations: list[ToolInvocation] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield ConversationView()
        yield ToolEconomicsPanel()
        yield TimelinePanel()
        yield StatsPanel()
        yield Footer()

    def on_mount(self):
        """Initialize app after mounting."""
        # Start worker to drain events
        self.run_worker(self._drain_events, thread=True, exclusive=False)

        # Set initial panel visibility
        self.query_one(StatsPanel).display = self.show_stats
        self.query_one(ToolEconomicsPanel).display = self.show_economics
        self.query_one(TimelinePanel).display = self.show_timeline

    def _drain_events(self):
        """Worker: drain event queue and post to app main thread."""
        while not self._closing:
            try:
                event = self._event_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            except Exception:
                if self._closing:
                    break
                continue

            # Post to main thread for handling
            self.call_from_thread(self._handle_event, event)

    def _handle_event(self, event):
        """Process event on main thread."""
        kind = event[0]
        conv = self.query_one(ConversationView)
        stats = self.query_one(StatsPanel)

        if kind == "request":
            body = event[1]
            blocks = format_request(body, self._state)
            for block in blocks:
                conv.append_block(block, self.active_filters)
                # Capture the budget for this turn
                if isinstance(block, TurnBudgetBlock):
                    self._current_budget = block.budget
            conv.finish_turn()

            # Correlate tool invocations from this request
            messages = body.get("messages", [])
            invocations = correlate_tools(messages)
            self._all_invocations.extend(invocations)

            # Update stats
            stats.update_stats(requests=self._state["request_counter"])

        elif kind == "response_start":
            # Response starts are implicit in streaming events
            pass

        elif kind == "response_event":
            event_type, data = event[1], event[2]
            blocks = format_response_event(event_type, data)

            for block in blocks:
                conv.append_block(block, self.active_filters)

                # Extract stats from message_start and message_delta
                if isinstance(block, StreamInfoBlock):
                    stats.update_stats(model=block.model)
                elif event_type == "message_start":
                    msg = data.get("message", {})
                    usage = msg.get("usage", {})
                    input_tokens = usage.get("input_tokens", 0)
                    cache_read = usage.get("cache_read_input_tokens", 0)
                    cache_create = usage.get("cache_creation_input_tokens", 0)
                    stats.update_stats(
                        input_tokens=input_tokens,
                        cache_read_tokens=cache_read,
                        cache_creation_tokens=cache_create,
                    )
                    # Fill actual data into current budget
                    if self._current_budget:
                        self._current_budget.actual_input_tokens = input_tokens
                        self._current_budget.actual_cache_read_tokens = cache_read
                        self._current_budget.actual_cache_creation_tokens = cache_create
                elif event_type == "message_delta":
                    usage = data.get("usage", {})
                    stats.update_stats(
                        output_tokens=usage.get("output_tokens", 0),
                    )

        elif kind == "response_done":
            conv.finish_turn()
            # Finalize turn budget and update panels
            if self._current_budget:
                self._turn_budgets.append(self._current_budget)
                # Re-render expand view to show cache data
                if self.show_expand:
                    conv.rerender(self.active_filters)
                self._current_budget = None
            # Update economics and timeline panels
            self._refresh_economics()
            self._refresh_timeline()

        elif kind == "error":
            from cc_dump.formatting import ErrorBlock
            code, reason = event[1], event[2]
            block = ErrorBlock(code=code, reason=reason)
            conv.append_block(block, self.active_filters)
            conv.finish_turn()

        elif kind == "proxy_error":
            from cc_dump.formatting import ProxyErrorBlock
            err = event[1]
            block = ProxyErrorBlock(error=err)
            conv.append_block(block, self.active_filters)
            conv.finish_turn()

        elif kind == "log":
            # Logs are less important in TUI, skip for now
            pass

    @property
    def active_filters(self):
        """Current filter state as a dict."""
        return {
            "headers": self.show_headers,
            "tools": self.show_tools,
            "system": self.show_system,
            "expand": self.show_expand,
            "metadata": self.show_metadata,
        }

    # Action handlers for key bindings

    def action_toggle_headers(self):
        self.show_headers = not self.show_headers

    def action_toggle_tools(self):
        self.show_tools = not self.show_tools

    def action_toggle_system(self):
        self.show_system = not self.show_system

    def action_toggle_expand(self):
        self.show_expand = not self.show_expand

    def action_toggle_metadata(self):
        self.show_metadata = not self.show_metadata

    def action_toggle_stats(self):
        self.show_stats = not self.show_stats
        self.query_one(StatsPanel).display = self.show_stats

    def action_toggle_economics(self):
        self.show_economics = not self.show_economics
        self.query_one(ToolEconomicsPanel).display = self.show_economics
        if self.show_economics:
            self._refresh_economics()

    def action_toggle_timeline(self):
        self.show_timeline = not self.show_timeline
        self.query_one(TimelinePanel).display = self.show_timeline
        if self.show_timeline:
            self._refresh_timeline()

    def _refresh_economics(self):
        """Update tool economics panel with current data."""
        if not self.is_running:
            return
        panel = self.query_one(ToolEconomicsPanel)
        aggregates = aggregate_tools(self._all_invocations)
        panel.update_data(aggregates)

    def _refresh_timeline(self):
        """Update timeline panel with current turn budgets."""
        if not self.is_running:
            return
        panel = self.query_one(TimelinePanel)
        panel.update_data(self._turn_budgets)

    # Reactive watchers - trigger re-render when filters change

    def _rerender_if_mounted(self):
        """Re-render conversation if the app is mounted."""
        if self.is_running:
            self.query_one(ConversationView).rerender(self.active_filters)

    def watch_show_headers(self, value):
        self._rerender_if_mounted()

    def watch_show_tools(self, value):
        self._rerender_if_mounted()

    def watch_show_system(self, value):
        self._rerender_if_mounted()

    def watch_show_expand(self, value):
        self._rerender_if_mounted()

    def watch_show_metadata(self, value):
        self._rerender_if_mounted()

    def watch_show_economics(self, value):
        pass  # visibility handled in action handler

    def watch_show_timeline(self, value):
        pass  # visibility handled in action handler

    def on_unmount(self):
        """Clean up when app exits."""
        self._closing = True
        self._router.stop()
