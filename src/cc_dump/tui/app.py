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

    def __init__(self, event_queue, state, router, db_path: Optional[str] = None, session_id: Optional[str] = None, host: str = "127.0.0.1", port: int = 3344, target: Optional[str] = None):
        super().__init__()
        self._event_queue = event_queue
        self._state = state
        self._router = router
        self._db_path = db_path
        self._session_id = session_id
        self._host = host
        self._port = port
        self._target = target
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
        self.run_worker(self._drain_events, thread=True, exclusive=False)

        # Set initial panel visibility
        stats = self._get_stats()
        if stats is not None:
            stats.display = self.show_stats
        economics = self._get_economics()
        if economics is not None:
            economics.display = self.show_economics
        timeline = self._get_timeline()
        if timeline is not None:
            timeline.display = self.show_timeline
        logs = self._get_logs()
        if logs is not None:
            logs.display = self.show_logs

        # Initialize footer with current filter state
        self._update_footer_state()


    # Widget accessors - use query by ID so we can swap widgets
    # Return None when widget is temporarily missing (e.g., during hot-reload swap)
    def _query_safe(self, selector):
        """Query a widget, returning None if not found."""
        try:
            return self.query_one(selector)
        except NoMatches:
            return None

    def _get_conv(self):
        return self._query_safe("#" + self._conv_id)

    def _get_stats(self):
        return self._query_safe("#" + self._stats_id)

    def _get_economics(self):
        return self._query_safe("#" + self._economics_id)

    def _get_timeline(self):
        return self._query_safe("#" + self._timeline_id)

    def _get_logs(self):
        return self._query_safe("#" + self._logs_id)

    def _get_footer(self):
        try:
            return self.query_one(StyledFooter)
        except NoMatches:
            return None

    def _log(self, level: str, message: str):
        """Log a message to the application logs panel."""
        if self.is_running:
            logs = self._get_logs()
            if logs is not None:
                logs.log(level, message)

    def _update_footer_state(self):
        """Update the footer to show active filter/panel states."""
        if self.is_running:
            footer = self._get_footer()
            if footer is not None:
                footer.update_active_state(self.active_filters)

    def _drain_events(self):
        """Worker: drain event queue and post to app main thread."""
        while not self._closing:
            try:
                event = self._event_queue.get(timeout=1.0)
            except queue.Empty:
                # Check for hot reload even when idle
                self.call_from_thread(self._check_hot_reload)
                continue
            except Exception as e:
                if self._closing:
                    break
                self.call_from_thread(self._log, "ERROR", f"Event queue error: {e}")
                continue

            # Check for hot reload before processing event
            self.call_from_thread(self._check_hot_reload)
            # Post to main thread for handling
            self.call_from_thread(self._handle_event, event)

    async def _check_hot_reload(self):
        """Check for file changes and reload modules if necessary."""
        import cc_dump.hot_reload

        try:
            reloaded_modules = cc_dump.hot_reload.check_and_get_reloaded()
        except Exception as e:
            self.notify(f"[hot-reload] error checking: {e}", severity="error")
            self._log("ERROR", f"Hot-reload error checking: {e}")
            return

        if not reloaded_modules:
            return

        # Notify user
        self.notify("[hot-reload] modules reloaded", severity="information")
        self._log("INFO", f"Hot-reload: {', '.join(reloaded_modules)}")

        # Check if widget_factory was reloaded - if so, replace widgets
        try:
            if "cc_dump.tui.widget_factory" in reloaded_modules:
                await self._replace_all_widgets()
            elif self.is_running:
                # Just re-render with new code (for rendering/formatting changes)
                conv = self._get_conv()
                if conv is not None:
                    conv.rerender(self.active_filters)
        except Exception as e:
            self.notify(f"[hot-reload] error applying: {e}", severity="error")
            self._log("ERROR", f"Hot-reload error applying: {e}")

    async def _replace_all_widgets(self):
        """Replace all widgets with fresh instances from the reloaded factory.

        Uses create-before-remove pattern: all new widgets are created and
        state-restored before any old widgets are touched. If creation fails,
        old widgets remain in the DOM and the app continues working.
        """
        if not self.is_running:
            return

        self._replacing_widgets = True
        try:
            await self._replace_all_widgets_inner()
        finally:
            self._replacing_widgets = False

    async def _replace_all_widgets_inner(self):
        """Inner implementation of widget replacement.

        Strategy: Create all new widgets first (without IDs), then remove old
        widgets, then mount new ones with the correct IDs. The _replacing_widgets
        flag prevents any code from querying widgets during the gap.

        Textual widget IDs are immutable once set, so we must remove old widgets
        before mounting new ones with the same IDs.
        """
        # 1. Capture state from old widgets
        old_conv = self._get_conv()
        old_stats = self._get_stats()
        old_economics = self._get_economics()
        old_timeline = self._get_timeline()
        old_logs = self._get_logs()

        if old_conv is None:
            return  # Widgets already missing — nothing to replace

        conv_state = old_conv.get_state()
        stats_state = old_stats.get_state() if old_stats else {}
        economics_state = old_economics.get_state() if old_economics else {}
        timeline_state = old_timeline.get_state() if old_timeline else {}
        logs_state = old_logs.get_state() if old_logs else {}

        stats_visible = old_stats.display if old_stats else self.show_stats
        economics_visible = old_economics.display if old_economics else self.show_economics
        timeline_visible = old_timeline.display if old_timeline else self.show_timeline
        logs_visible = old_logs.display if old_logs else self.show_logs

        # 2. Create ALL new widgets (without IDs yet — set after mounting).
        #    If any creation or restore_state fails, old widgets remain untouched.
        new_conv = cc_dump.tui.widget_factory.create_conversation_view()
        new_conv.restore_state(conv_state)

        new_stats = cc_dump.tui.widget_factory.create_stats_panel()
        new_stats.restore_state(stats_state)

        new_economics = cc_dump.tui.widget_factory.create_economics_panel()
        new_economics.restore_state(economics_state)

        new_timeline = cc_dump.tui.widget_factory.create_timeline_panel()
        new_timeline.restore_state(timeline_state)

        new_logs = cc_dump.tui.widget_factory.create_logs_panel()
        new_logs.restore_state(logs_state)

        # 3. Remove old widgets (DOM gap starts — _replacing_widgets flag protects us)
        #    Must await removal so Textual deregisters IDs before we reuse them.
        await old_conv.remove()
        if old_stats is not None:
            await old_stats.remove()
        if old_economics is not None:
            await old_economics.remove()
        if old_timeline is not None:
            await old_timeline.remove()
        if old_logs is not None:
            await old_logs.remove()

        # 4. Assign IDs and mount new widgets (IDs must be set before mount)
        new_conv.id = self._conv_id
        new_stats.id = self._stats_id
        new_economics.id = self._economics_id
        new_timeline.id = self._timeline_id
        new_logs.id = self._logs_id

        new_stats.display = stats_visible
        new_economics.display = economics_visible
        new_timeline.display = timeline_visible
        new_logs.display = logs_visible

        header = self.query_one(Header)
        await self.mount(new_conv, after=header)
        await self.mount(new_economics, after=new_conv)
        await self.mount(new_timeline, after=new_economics)
        await self.mount(new_logs, after=new_timeline)
        await self.mount(new_stats, after=new_logs)

        # 5. Re-render with current filters
        new_conv.rerender(self.active_filters)

        self.notify("[hot-reload] widgets replaced", severity="information")

    def _handle_event(self, event):
        """Process event on main thread using reloadable handlers."""
        try:
            self._handle_event_inner(event)
        except Exception as e:
            self._log("ERROR", f"Uncaught exception handling event: {e}")
            import traceback
            tb = traceback.format_exc()
            for line in tb.split('\n'):
                if line:
                    self._log("ERROR", f"  {line}")

    def _handle_event_inner(self, event):
        """Inner event handler with exception boundary."""
        if self._replacing_widgets:
            return  # Skip events during widget swap

        kind = event[0]

        # Build widget dict for handlers
        conv = self._get_conv()
        stats = self._get_stats()
        if conv is None or stats is None:
            return  # Widgets not ready
        widgets = {
            "conv": conv,
            "stats": stats,
            "filters": self.active_filters,
            "show_expand": self.show_expand,
        }

        # Build database context for handlers
        db_context = {
            "db_path": self._db_path,
            "session_id": self._session_id,
        }

        # Build refresh callbacks
        refresh_callbacks = {
            "refresh_economics": self._refresh_economics,
            "refresh_timeline": self._refresh_timeline,
        }

        # Build log callback
        log_callback = self._log

        if kind == "request_headers":
            self._app_state = cc_dump.tui.event_handlers.handle_request_headers(
                event, self._state, widgets, self._app_state, log_callback
            )

        elif kind == "request":
            self._app_state = cc_dump.tui.event_handlers.handle_request(
                event, self._state, widgets, self._app_state, log_callback
            )

        elif kind == "response_headers":
            self._app_state = cc_dump.tui.event_handlers.handle_response_headers(
                event, self._state, widgets, self._app_state, log_callback
            )

        elif kind == "response_start":
            # Response starts are now handled by response_headers event
            pass

        elif kind == "response_event":
            self._app_state = cc_dump.tui.event_handlers.handle_response_event(
                event, self._state, widgets, self._app_state, log_callback
            )

        elif kind == "response_done":
            self._app_state = cc_dump.tui.event_handlers.handle_response_done(
                event, self._state, widgets, self._app_state, refresh_callbacks, db_context, log_callback
            )

        elif kind == "error":
            self._app_state = cc_dump.tui.event_handlers.handle_error(
                event, self._state, widgets, self._app_state, log_callback
            )

        elif kind == "proxy_error":
            self._app_state = cc_dump.tui.event_handlers.handle_proxy_error(
                event, self._state, widgets, self._app_state, log_callback
            )

        elif kind == "log":
            # HTTP proxy logs - log them to app logs
            _, method, path, status = event
            self._log("DEBUG", f"HTTP {method} {path} -> {status}")

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

    def _refresh_economics(self):
        """Update tool economics panel with current data from database."""
        if not self.is_running or not self._db_path or not self._session_id:
            return
        panel = self._get_economics()
        if panel is not None:
            panel.refresh_from_db(self._db_path, self._session_id)

    def _refresh_timeline(self):
        """Update timeline panel with current data from database."""
        if not self.is_running or not self._db_path or not self._session_id:
            return
        panel = self._get_timeline()
        if panel is not None:
            panel.refresh_from_db(self._db_path, self._session_id)

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

    def on_unmount(self):
        """Clean up when app exits."""
        self._log("INFO", "cc-dump TUI shutting down")
        self._closing = True
        self._router.stop()
