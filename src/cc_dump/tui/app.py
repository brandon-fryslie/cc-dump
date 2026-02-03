"""Main TUI application using Textual."""

import queue
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Header

# Use custom footer with Rich markup support
from cc_dump.tui.custom_footer import StyledFooter

# Use module-level imports so hot-reload takes effect
import cc_dump.analysis
import cc_dump.formatting
import cc_dump.tui.widget_factory
import cc_dump.tui.event_handlers


class CcDumpApp(App):
    """TUI application for cc-dump."""

    CSS_PATH = "styles.css"

    BINDINGS = [
        Binding("h", "toggle_headers", "h|eaders", show=True),
        Binding("t", "toggle_tools", "t|ools", show=True),
        Binding("s", "toggle_system", "s|ystem", show=True),
        Binding("e", "toggle_expand", "cont|e|xt", show=True),
        Binding("m", "toggle_metadata", "m|etadata", show=True),
        Binding("a", "toggle_stats", "st|a|ts", show=True),
        Binding("c", "toggle_economics", "c|ost", show=True),
        Binding("l", "toggle_timeline", "time|l|ine", show=True),
        Binding("u", "toggle_user_messages", "u|ser msg", show=True),
        Binding("d", "toggle_assistant_messages", "|d|etail asst", show=True),
        Binding("ctrl+l", "toggle_logs", "Logs", show=False),
        Binding("ctrl+m", "toggle_economics_breakdown", "Model breakdown", show=False),
        # Sprint 2: Follow mode and navigation
        Binding("f", "toggle_follow", "f|ollow", show=True),
        Binding("j", "next_turn", "next", show=False),
        Binding("k", "prev_turn", "prev", show=False),
        Binding("n", "next_tool_turn", "next tool", show=False),
        Binding("N", "prev_tool_turn", "prev tool", show=False),
        Binding("g", "first_turn", "top", show=False),
        Binding("G", "last_turn", "bottom", show=False),
    ]

    show_headers = reactive(False)
    show_tools = reactive(True)
    show_system = reactive(True)
    show_expand = reactive(False)
    show_metadata = reactive(True)
    show_stats = reactive(True)
    show_economics = reactive(False)
    show_timeline = reactive(False)
    show_logs = reactive(False)
    show_user_messages = reactive(False)
    show_assistant_messages = reactive(False)

    def __init__(self, event_queue, state, router, db_path: Optional[str] = None, session_id: Optional[str] = None, host: str = "127.0.0.1", port: int = 3344, target: Optional[str] = None, replay_data: Optional[list] = None):
        super().__init__()
        self._event_queue = event_queue
        self._state = state
        self._router = router
        self._db_path = db_path
        self._session_id = session_id
        self._host = host
        self._port = port
        self._target = target
        self._replay_data = replay_data
        self._closing = False
        self._replacing_widgets = False

        # App-level state (preserved across hot-reloads)
        # Only track minimal in-progress turn data for real-time streaming feedback
        self._app_state = {
            "current_turn_usage": {},  # Token counts for incomplete turn
        }

        # Widget IDs for querying (set after compose)
        self._conv_id = "conversation-view"
        self._stats_id = "stats-panel"
        self._economics_id = "economics-panel"
        self._timeline_id = "timeline-panel"
        self._logs_id = "logs-panel"

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

        logs = cc_dump.tui.widget_factory.create_logs_panel()
        logs.id = self._logs_id
        yield logs

        stats = cc_dump.tui.widget_factory.create_stats_panel()
        stats.id = self._stats_id
        yield stats

        yield StyledFooter()

    def on_mount(self):
        """Initialize app after mounting."""
        # Log startup messages (mirror what was printed to console)
        self._log("INFO", "🚀 cc-dump proxy started")
        self._log("INFO", f"Listening on: http://{self._host}:{self._port}")

        if self._target:
            self._log("INFO", f"Reverse proxy mode: {self._target}")
            self._log("INFO", f"Usage: ANTHROPIC_BASE_URL=http://{self._host}:{self._port} claude")
        else:
            self._log("INFO", "Forward proxy mode (dynamic targets)")
            self._log("INFO", f"Usage: HTTP_PROXY=http://{self._host}:{self._port} ANTHROPIC_BASE_URL=http://api.minimax.com claude")

        if self._db_path and self._session_id:
            self._log("INFO", f"Database: {self._db_path}")
            self._log("INFO", f"Session: {self._session_id}")
        else:
            self._log("WARNING", "Database disabled (--no-db)")

        # Start worker to drain events
        self.run_worker(
            self._drain_events(), exclusive=True, name="event-drain", thread=True
        )

        # Start replay worker if replay data provided
        if self._replay_data:
            self.run_worker(
                self._replay_events(), exclusive=True, name="replay-events", thread=True
            )

        # Initial footer state update
        self._update_footer_state()

    async def _drain_events(self):
        """Background worker that drains the event queue."""
        while not self._closing:
            try:
                events = []
                try:
                    # Block for up to 100ms to reduce busy-wait
                    events.append(self._event_queue.get(timeout=0.1))
                except queue.Empty:
                    continue

                # Drain any additional queued events
                while True:
                    try:
                        events.append(self._event_queue.get_nowait())
                    except queue.Empty:
                        break

                # Get widget references
                widgets = {
                    "conv": self._get_conv(),
                    "stats": self._get_stats(),
                    "economics": self._get_economics(),
                    "timeline": self._get_timeline(),
                }

                def log_callback(level, message):
                    """Callback for event handlers to log messages."""
                    self._log(level, message)

                # Process batch of events
                for event in events:
                    cc_dump.tui.event_handlers.handle_event(
                        event, self._state, widgets, self._app_state, log_callback
                    )

            except Exception as e:
                self._log("ERROR", f"Event drain error: {e}")
                import traceback
                self._log("ERROR", traceback.format_exc())

    async def _replay_events(self):
        """Background worker that replays events from HAR."""
        from cc_dump.har_replayer import replay_har_events

        try:
            self._log("INFO", "Starting HAR replay...")
            count = 0
            for event in replay_har_events(self._replay_data):
                self._event_queue.put(event)
                count += 1
                # Small delay to avoid overwhelming the UI
                await self.sleep(0.001)

            self._log("INFO", f"Replay complete: {count} events")
        except Exception as e:
            self._log("ERROR", f"Replay error: {e}")
            import traceback
            self._log("ERROR", traceback.format_exc())

    def _get_conv(self):
        """Get conversation widget."""
        try:
            return self.query_one(f"#{self._conv_id}")
        except NoMatches:
            return None

    def _get_stats(self):
        """Get stats panel widget."""
        try:
            return self.query_one(f"#{self._stats_id}")
        except NoMatches:
            return None

    def _get_economics(self):
        """Get economics panel widget."""
        try:
            return self.query_one(f"#{self._economics_id}")
        except NoMatches:
            return None

    def _get_timeline(self):
        """Get timeline panel widget."""
        try:
            return self.query_one(f"#{self._timeline_id}")
        except NoMatches:
            return None

    def _get_logs(self):
        """Get logs panel widget."""
        try:
            return self.query_one(f"#{self._logs_id}")
        except NoMatches:
            return None

    def _update_footer_state(self):
        """Update footer with current filter states."""
        try:
            footer = self.query_one(StyledFooter)
            footer.update_filter_states(self.active_filters)
        except NoMatches:
            pass

    def _refresh_economics(self):
        """Refresh economics panel with current session data."""
        economics = self._get_economics()
        if economics is not None and self._db_path and self._session_id:
            try:
                import cc_dump.db_queries
                economics_data = cc_dump.db_queries.compute_economics(
                    self._db_path, self._session_id
                )
                if economics_data:
                    economics.update_data(economics_data)
            except Exception as e:
                self._log("ERROR", f"Failed to refresh economics: {e}")

    def _refresh_timeline(self):
        """Refresh timeline panel with current session data."""
        timeline = self._get_timeline()
        if timeline is not None and self._db_path and self._session_id:
            try:
                import cc_dump.db_queries
                timeline_data = cc_dump.db_queries.get_timeline_data(
                    self._db_path, self._session_id
                )
                if timeline_data:
                    timeline.update_data(timeline_data)
            except Exception as e:
                self._log("ERROR", f"Failed to refresh timeline: {e}")

    def _log(self, level: str, message: str):
        """Log a message to the logs panel."""
        logs = self._get_logs()
        if logs is not None:
            logs.add_log(level, message)

    @property
    def active_filters(self):
        """Current filter state as a dict."""
        return {
            "headers": self.show_headers,
            "tools": self.show_tools,
            "system": self.show_system,
            "expand": self.show_expand,
            "metadata": self.show_metadata,
            "stats": self.show_stats,
            "economics": self.show_economics,
            "timeline": self.show_timeline,
            "user": self.show_user_messages,
            "assistant": self.show_assistant_messages,
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
        stats = self._get_stats()
        if stats is not None:
            stats.display = self.show_stats

    def action_toggle_economics(self):
        self.show_economics = not self.show_economics
        economics = self._get_economics()
        if economics is not None:
            economics.display = self.show_economics
        if self.show_economics:
            self._refresh_economics()

    def action_toggle_timeline(self):
        self.show_timeline = not self.show_timeline
        timeline = self._get_timeline()
        if timeline is not None:
            timeline.display = self.show_timeline
        if self.show_timeline:
            self._refresh_timeline()

    def action_toggle_logs(self):
        self.show_logs = not self.show_logs
        logs = self._get_logs()
        if logs is not None:
            logs.display = self.show_logs

    def action_toggle_economics_breakdown(self):
        """Toggle between aggregate and per-model breakdown in economics panel."""
        economics = self._get_economics()
        if economics is not None:
            economics.toggle_breakdown()

    def action_toggle_user_messages(self):
        self.show_user_messages = not self.show_user_messages

    def action_toggle_assistant_messages(self):
        self.show_assistant_messages = not self.show_assistant_messages

    # Sprint 2: Follow mode and navigation action handlers

    def action_toggle_follow(self):
        conv = self._get_conv()
        if conv is not None:
            conv.toggle_follow()

    def action_next_turn(self):
        conv = self._get_conv()
        if conv is not None:
            conv.select_next_turn(forward=True)

    def action_prev_turn(self):
        conv = self._get_conv()
        if conv is not None:
            conv.select_next_turn(forward=False)

    def action_next_tool_turn(self):
        conv = self._get_conv()
        if conv is not None:
            conv.next_tool_turn(forward=True)

    def action_prev_tool_turn(self):
        conv = self._get_conv()
        if conv is not None:
            conv.next_tool_turn(forward=False)

    def action_first_turn(self):
        conv = self._get_conv()
        if conv is not None:
            conv.jump_to_first()

    def action_last_turn(self):
        conv = self._get_conv()
        if conv is not None:
            conv.jump_to_last()

    # Reactive watchers - trigger re-render when filters change

    def _rerender_if_mounted(self):
        """Re-render conversation if the app is mounted."""
        if self.is_running and not self._replacing_widgets:
            conv = self._get_conv()
            if conv is not None:
                conv.rerender(self.active_filters)
            self._update_footer_state()

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

    def watch_show_stats(self, value):
        self._update_footer_state()

    def watch_show_economics(self, value):
        self._update_footer_state()

    def watch_show_timeline(self, value):
        self._update_footer_state()

    def watch_show_logs(self, value):
        pass  # visibility handled in action handler

    def watch_show_user_messages(self, value):
        self._rerender_if_mounted()

    def watch_show_assistant_messages(self, value):
        self._rerender_if_mounted()

    def on_unmount(self):
        """Clean up when app exits."""
        self._log("INFO", "cc-dump TUI shutting down")
        self._closing = True
        self._router.stop()
