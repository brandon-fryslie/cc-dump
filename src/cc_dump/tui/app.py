"""Main TUI application using Textual."""

import queue

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Footer, Header

# Use module-level imports so hot-reload takes effect
import cc_dump.analysis
import cc_dump.formatting
import cc_dump.tui.widget_factory
import cc_dump.tui.event_handlers


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

        # App-level state (preserved across hot-reloads)
        self._app_state = {
            "turn_budgets": [],
            "current_budget": None,
            "all_invocations": [],
        }

        # Widget IDs for querying (set after compose)
        self._conv_id = "conversation-view"
        self._stats_id = "stats-panel"
        self._economics_id = "economics-panel"
        self._timeline_id = "timeline-panel"

    def compose(self) -> ComposeResult:
        yield Header()
        # Create widgets from factory with IDs for later lookup
        conv = cc_dump.tui.widget_factory.create_conversation_view()
        conv.id = self._conv_id
        yield conv

        economics = cc_dump.tui.widget_factory.create_economics_panel()
        economics.id = self._economics_id
        yield economics

        timeline = cc_dump.tui.widget_factory.create_timeline_panel()
        timeline.id = self._timeline_id
        yield timeline

        stats = cc_dump.tui.widget_factory.create_stats_panel()
        stats.id = self._stats_id
        yield stats

        yield Footer()

    def on_mount(self):
        """Initialize app after mounting."""
        # Start worker to drain events
        self.run_worker(self._drain_events, thread=True, exclusive=False)

        # Set initial panel visibility
        self._get_stats().display = self.show_stats
        self._get_economics().display = self.show_economics
        self._get_timeline().display = self.show_timeline

    # Widget accessors - use query by ID so we can swap widgets
    def _get_conv(self):
        return self.query_one("#" + self._conv_id)

    def _get_stats(self):
        return self.query_one("#" + self._stats_id)

    def _get_economics(self):
        return self.query_one("#" + self._economics_id)

    def _get_timeline(self):
        return self.query_one("#" + self._timeline_id)

    def _drain_events(self):
        """Worker: drain event queue and post to app main thread."""
        while not self._closing:
            try:
                event = self._event_queue.get(timeout=1.0)
            except queue.Empty:
                # Check for hot reload even when idle
                self.call_from_thread(self._check_hot_reload)
                continue
            except Exception:
                if self._closing:
                    break
                continue

            # Check for hot reload before processing event
            self.call_from_thread(self._check_hot_reload)
            # Post to main thread for handling
            self.call_from_thread(self._handle_event, event)

    def _check_hot_reload(self):
        """Check for file changes and reload modules if necessary."""
        import cc_dump.hot_reload
        reloaded_modules = cc_dump.hot_reload.check_and_get_reloaded()

        if not reloaded_modules:
            return

        # Notify user
        self.notify("[hot-reload] modules reloaded", severity="information")

        # Check if widget_factory was reloaded - if so, replace widgets
        if "cc_dump.tui.widget_factory" in reloaded_modules:
            self._replace_all_widgets()
        elif self.is_running:
            # Just re-render with new code (for rendering/formatting changes)
            self._get_conv().rerender(self.active_filters)

    def _replace_all_widgets(self):
        """Replace all widgets with fresh instances from the reloaded factory."""
        if not self.is_running:
            return

        # Get current widget states
        conv_state = self._get_conv().get_state()
        stats_state = self._get_stats().get_state()
        economics_state = self._get_economics().get_state()
        timeline_state = self._get_timeline().get_state()

        # Remember visibility
        stats_visible = self._get_stats().display
        economics_visible = self._get_economics().display
        timeline_visible = self._get_timeline().display

        # Remove old widgets
        old_conv = self._get_conv()
        old_stats = self._get_stats()
        old_economics = self._get_economics()
        old_timeline = self._get_timeline()

        # Create new widgets from reloaded factory
        new_conv = cc_dump.tui.widget_factory.create_conversation_view()
        new_conv.id = self._conv_id
        new_conv.restore_state(conv_state)

        new_stats = cc_dump.tui.widget_factory.create_stats_panel()
        new_stats.id = self._stats_id
        new_stats.restore_state(stats_state)
        new_stats.display = stats_visible

        new_economics = cc_dump.tui.widget_factory.create_economics_panel()
        new_economics.id = self._economics_id
        new_economics.restore_state(economics_state)
        new_economics.display = economics_visible

        new_timeline = cc_dump.tui.widget_factory.create_timeline_panel()
        new_timeline.id = self._timeline_id
        new_timeline.restore_state(timeline_state)
        new_timeline.display = timeline_visible

        # Swap widgets - mount new before removing old to maintain layout
        old_conv.remove()
        old_stats.remove()
        old_economics.remove()
        old_timeline.remove()

        # Mount in correct order after header
        header = self.query_one(Header)
        self.mount(new_conv, after=header)
        self.mount(new_economics, after=new_conv)
        self.mount(new_timeline, after=new_economics)
        self.mount(new_stats, after=new_timeline)

        # Re-render the conversation with current filters
        new_conv.rerender(self.active_filters)

        self.notify("[hot-reload] widgets replaced", severity="information")

    def _handle_event(self, event):
        """Process event on main thread using reloadable handlers."""
        kind = event[0]

        # Build widget dict for handlers
        widgets = {
            "conv": self._get_conv(),
            "stats": self._get_stats(),
            "filters": self.active_filters,
            "show_expand": self.show_expand,
        }

        # Build refresh callbacks
        refresh_callbacks = {
            "refresh_economics": self._refresh_economics,
            "refresh_timeline": self._refresh_timeline,
        }

        if kind == "request":
            self._app_state = cc_dump.tui.event_handlers.handle_request(
                event, self._state, widgets, self._app_state
            )

        elif kind == "response_start":
            # Response starts are implicit in streaming events
            pass

        elif kind == "response_event":
            self._app_state = cc_dump.tui.event_handlers.handle_response_event(
                event, self._state, widgets, self._app_state
            )

        elif kind == "response_done":
            self._app_state = cc_dump.tui.event_handlers.handle_response_done(
                event, self._state, widgets, self._app_state, refresh_callbacks
            )

        elif kind == "error":
            self._app_state = cc_dump.tui.event_handlers.handle_error(
                event, self._state, widgets, self._app_state
            )

        elif kind == "proxy_error":
            self._app_state = cc_dump.tui.event_handlers.handle_proxy_error(
                event, self._state, widgets, self._app_state
            )

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
        self._get_stats().display = self.show_stats

    def action_toggle_economics(self):
        self.show_economics = not self.show_economics
        self._get_economics().display = self.show_economics
        if self.show_economics:
            self._refresh_economics()

    def action_toggle_timeline(self):
        self.show_timeline = not self.show_timeline
        self._get_timeline().display = self.show_timeline
        if self.show_timeline:
            self._refresh_timeline()

    def _refresh_economics(self):
        """Update tool economics panel with current data."""
        if not self.is_running:
            return
        panel = self._get_economics()
        aggregates = cc_dump.analysis.aggregate_tools(self._app_state["all_invocations"])
        panel.update_data(aggregates)

    def _refresh_timeline(self):
        """Update timeline panel with current turn budgets."""
        if not self.is_running:
            return
        panel = self._get_timeline()
        panel.update_data(self._app_state["turn_budgets"])

    # Reactive watchers - trigger re-render when filters change

    def _rerender_if_mounted(self):
        """Re-render conversation if the app is mounted."""
        if self.is_running:
            self._get_conv().rerender(self.active_filters)

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
