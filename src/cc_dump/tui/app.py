"""Main TUI application using Textual."""

import os
import platform
import queue
import subprocess
import tempfile
import threading
from typing import Optional

from textual.app import App, ComposeResult, SystemCommand
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Header

# Use custom footer with Rich markup support
from cc_dump.tui.custom_footer import StatusFooter

# Use module-level imports so hot-reload takes effect
import cc_dump.analysis
import cc_dump.formatting
import cc_dump.tui.rendering
import cc_dump.tui.widget_factory
import cc_dump.tui.event_handlers
import cc_dump.tui.search
import cc_dump.tui.input_modes

# Convenience aliases for VisState (accessed via module name below)
# Note: Can't use 'from' imports in stable modules due to hot-reload


# [LAW:one-source-of-truth] [LAW:one-type-per-behavior]
# (key, category, description, default_visstate)
_CATEGORY_CONFIG = [
    ("1", "headers", "headers", cc_dump.formatting.VisState(False, False, False)),  # hidden
    ("2", "user", "user", cc_dump.formatting.VisState(True, True, True)),           # full-expanded
    ("3", "assistant", "assistant", cc_dump.formatting.VisState(True, True, True)), # full-expanded
    ("4", "tools", "tools", cc_dump.formatting.VisState(True, False, False)),       # summary-collapsed
    ("5", "system", "system", cc_dump.formatting.VisState(True, False, False)),     # summary-collapsed
    ("6", "budget", "budget", cc_dump.formatting.VisState(False, False, False)),    # hidden
    ("7", "metadata", "metadata", cc_dump.formatting.VisState(False, False, False)),# hidden
]

# Lookup dicts from config removed - using reactive dicts instead


class CcDumpApp(App):
    """TUI application for cc-dump."""

    CSS_PATH = "styles.css"

    # Pure mode system: all key dispatch through on_key using MODE_KEYMAP.
    # No Textual BINDINGS - we always prevent_default to block binding resolution.

    # [LAW:one-source-of-truth] Three orthogonal reactive dicts for visibility state
    # Each toggled by exactly one action. No cross-contamination.
    _is_visible = reactive({})   # True = visible, False = hidden (EXISTENCE)
    _is_full = reactive({})      # True = FULL level, False = SUMMARY level
    _is_expanded = reactive({})  # True = expanded, False = collapsed

    # Panel visibility (bool toggles)
    show_economics = reactive(False)
    show_timeline = reactive(False)
    show_logs = reactive(False)

    def __init__(
        self,
        event_queue,
        state,
        router,
        db_path: Optional[str] = None,
        session_id: Optional[str] = None,
        session_name: str = "unnamed-session",
        host: str = "127.0.0.1",
        port: int = 3344,
        target: Optional[str] = None,
        replay_data: Optional[list] = None,
    ):
        super().__init__()
        self._event_queue = event_queue
        self._state = state
        self._router = router
        self._db_path = db_path
        self._session_id = session_id
        self._session_name = session_name
        self._host = host
        self._port = port
        self._target = target
        self._replay_data = replay_data
        self._closing = False
        self._replacing_widgets = False

        # Set sub_title with session name using theme-aware color
        # [LAW:one-source-of-truth] Use palette.info for session label
        import cc_dump.palette
        self.sub_title = f"[{cc_dump.palette.PALETTE.info}]session: {session_name}[/]"

        # Gate for drain worker: block until replay is complete
        self._replay_complete = threading.Event()
        if not replay_data:
            self._replay_complete.set()

        # App-level state (preserved across hot-reloads)
        # Only track minimal in-progress turn data for real-time streaming feedback
        self._app_state = {
            "current_turn_usage": {},  # Token counts for incomplete turn
        }

        # [LAW:one-source-of-truth] Three orthogonal booleans per category.
        # Each action toggles EXACTLY ONE dict. No cross-contamination.
        self._is_visible = {
            name: default.visible
            for _, name, _, default in _CATEGORY_CONFIG
        }
        self._is_full = {
            name: default.full
            for _, name, _, default in _CATEGORY_CONFIG
        }
        self._is_expanded = {
            name: default.expanded
            for _, name, _, default in _CATEGORY_CONFIG
        }

        # Search state
        self._search_state = cc_dump.tui.search.SearchState()

        # Widget IDs for querying (set after compose)
        self._conv_id = "conversation-view"
        self._search_bar_id = "search-bar"
        self._stats_id = "stats-panel"
        self._economics_id = "economics-panel"
        self._timeline_id = "timeline-panel"
        self._logs_id = "logs-panel"

    @property
    def _input_mode(self):
        """Current input mode derived from search state.

        // [LAW:one-source-of-truth] InputMode is derived, not parallel state.
        """
        InputMode = cc_dump.tui.input_modes.InputMode
        SearchPhase = cc_dump.tui.search.SearchPhase
        phase = self._search_state.phase

        if phase == SearchPhase.EDITING:
            return InputMode.SEARCH_EDIT
        if phase == SearchPhase.NAVIGATING:
            return InputMode.SEARCH_NAV
        return InputMode.NORMAL

    def get_system_commands(self, screen):
        """Add category filter and panel commands to command palette."""
        yield from super().get_system_commands(screen)
        for _key, name, _desc, _ in _CATEGORY_CONFIG:
            yield SystemCommand(
                f"Toggle {name}",
                f"Show/hide {name}",
                lambda n=name: self.action_toggle_vis(n),
            )
            yield SystemCommand(
                f"Cycle {name} detail",
                "SUMMARY <-> FULL",
                lambda n=name: self.action_toggle_detail(n),
            )
        yield SystemCommand(
            "Toggle cost panel", "Economics panel", self.action_toggle_economics
        )
        yield SystemCommand(
            "Toggle timeline", "Timeline panel", self.action_toggle_timeline
        )
        yield SystemCommand("Toggle logs", "Debug logs", self.action_toggle_logs)
        yield SystemCommand("Go to top", "Scroll to start", self.action_go_top)
        yield SystemCommand("Go to bottom", "Scroll to end", self.action_go_bottom)
        yield SystemCommand(
            "Toggle follow mode", "Auto-scroll", self.action_toggle_follow
        )
        yield SystemCommand(
            "Next theme", "Cycle to next theme (])", self.action_next_theme
        )
        yield SystemCommand(
            "Previous theme", "Cycle to previous theme ([)", self.action_prev_theme
        )
        yield SystemCommand(
            "Dump conversation",
            "Export conversation to text file",
            self.action_dump_conversation,
        )

    def compose(self) -> ComposeResult:
        yield Header()

        # Stats panel docked to top (below header)
        stats = cc_dump.tui.widget_factory.create_stats_panel()
        stats.id = self._stats_id
        yield stats

        # Main conversation view
        conv = cc_dump.tui.widget_factory.create_conversation_view()
        conv.id = self._conv_id
        yield conv

        # [LAW:dataflow-not-control-flow] Bottom panels stack bottom-to-top
        # Mount order (first→last): farthest from bottom edge → closest to bottom edge
        # Economics and Timeline appear above SearchBar
        economics = cc_dump.tui.widget_factory.create_economics_panel()
        economics.id = self._economics_id
        yield economics

        timeline = cc_dump.tui.widget_factory.create_timeline_panel()
        timeline.id = self._timeline_id
        yield timeline

        logs = cc_dump.tui.widget_factory.create_logs_panel()
        logs.id = self._logs_id
        yield logs

        # SearchBar mounted near footer so it's always visible at bottom when active
        search_bar = cc_dump.tui.search.SearchBar()
        search_bar.id = self._search_bar_id
        yield search_bar

        yield StatusFooter()

    def on_mount(self):
        """Initialize app after mounting."""
        # Initialize theme colors before any rendering
        cc_dump.tui.rendering.set_theme(self.current_theme)
        self._apply_markdown_theme()

        # Log startup messages (mirror what was printed to console)
        self._log("INFO", "🚀 cc-dump proxy started")
        self._log("INFO", f"Listening on: http://{self._host}:{self._port}")

        if self._target:
            self._log("INFO", f"Reverse proxy mode: {self._target}")
            self._log(
                "INFO",
                f"Usage: ANTHROPIC_BASE_URL=http://{self._host}:{self._port} claude",
            )
        else:
            self._log("INFO", "Forward proxy mode (dynamic targets)")
            self._log(
                "INFO",
                f"Usage: HTTP_PROXY=http://{self._host}:{self._port} ANTHROPIC_BASE_URL=http://api.minimax.com claude",
            )

        if self._db_path and self._session_id:
            self._log("INFO", f"Database: {self._db_path}")
            self._log("INFO", f"Session: {self._session_id}")
        else:
            self._log("WARNING", "Database disabled (--no-db)")

        # Start worker to drain events
        self.run_worker(self._drain_events, thread=True, exclusive=False)

        # Set initial panel visibility (stats always visible)
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

        # Process replay data if in replay mode
        if self._replay_data:
            self._process_replay_data()

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

    def _get_search_bar(self):
        return self._query_safe("#" + self._search_bar_id)

    def _get_footer(self):
        try:
            return self.query_one(StatusFooter)
        except NoMatches:
            return None

    def _process_replay_data(self):
        """Process HAR replay data and populate widgets directly (no events)."""
        if not self._replay_data:
            return

        self._log("INFO", f"Processing {len(self._replay_data)} request/response pairs")

        conv = self._get_conv()
        stats = self._get_stats()

        if conv is None:
            self._log("ERROR", "Cannot process replay: conversation widget not found")
            return

        for (
            req_headers,
            req_body,
            resp_status,
            resp_headers,
            complete_message,
        ) in self._replay_data:
            try:
                # [LAW:one-source-of-truth] Header injection moved into format_request
                request_blocks = cc_dump.formatting.format_request(
                    req_body, self._state, request_headers=req_headers
                )

                # Add request turn with current filters
                conv.add_turn(request_blocks, self.active_filters)

                # Format response blocks
                response_blocks = []

                # Add response headers if present
                if resp_headers:
                    response_blocks.extend(
                        cc_dump.formatting.format_response_headers(
                            resp_status, resp_headers
                        )
                    )

                # Add complete message blocks (NO streaming events)
                response_blocks.extend(
                    cc_dump.formatting.format_complete_response(complete_message)
                )

                # Add response turn with current filters
                conv.add_turn(response_blocks, self.active_filters)

                # Update stats
                if stats:
                    stats.update_stats(requests=self._state["request_counter"])

            except Exception as e:
                self._log("ERROR", f"Error processing replay pair: {e}")

        self._log(
            "INFO",
            f"Replay complete: {self._state['request_counter']} requests processed",
        )

        # Signal that replay is complete, allowing drain worker to process live events
        self._replay_complete.set()

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
                conv = self._get_conv()
                state = {
                    **self.active_filters,
                    "economics": self.show_economics,
                    "timeline": self.show_timeline,
                    "follow": conv._follow_mode if conv is not None else True,
                }
                footer.update_display(state)

    def _drain_events(self):
        """Worker: drain event queue and post to app main thread."""
        # Wait for replay to complete before processing live events
        self._replay_complete.wait()

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

        # Cancel any active search on reload (state references may be stale)
        SearchPhase = cc_dump.tui.search.SearchPhase
        if self._search_state.phase != SearchPhase.INACTIVE:
            self._search_state = cc_dump.tui.search.SearchState()
            bar = self._get_search_bar()
            if bar is not None:
                bar.display = False

        # Rebuild theme state after modules reload (before any rendering)
        cc_dump.tui.rendering.set_theme(self.current_theme)
        self._apply_markdown_theme()

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

        stats_visible = True  # stats always visible
        economics_visible = (
            old_economics.display if old_economics else self.show_economics
        )
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
        await self.mount(new_stats, after=header)
        await self.mount(new_conv, after=new_stats)
        await self.mount(new_economics, after=new_conv)
        await self.mount(new_timeline, after=new_economics)
        await self.mount(new_logs, after=new_timeline)
        # Note: SearchBar is not replaced during hot-reload (only panels are)

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
            for line in tb.split("\n"):
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

        # [LAW:dataflow-not-control-flow] Unified context dict — all handlers get same args
        widgets = {
            "conv": conv,
            "stats": stats,
            "filters": self.active_filters,
            "refresh_callbacks": {
                "refresh_economics": self._refresh_economics,
                "refresh_timeline": self._refresh_timeline,
            },
            "db_context": {
                "db_path": self._db_path,
                "session_id": self._session_id,
            },
        }

        # Build log callback
        log_callback = self._log

        # [LAW:dataflow-not-control-flow] Dispatch via table lookup — uniform signature
        handler = cc_dump.tui.event_handlers.EVENT_HANDLERS.get(kind)
        if handler:
            self._app_state = handler(
                event, self._state, widgets, self._app_state, log_callback
            )

    @property
    def active_filters(self):
        """Current filter state: category name -> VisState.

        // [LAW:one-source-of-truth] Pure data assembly. No Level, no DEFAULT_EXPANDED.
        // [LAW:dataflow-not-control-flow] VisState values flow to rendering AND footer.
        """
        return {
            name: cc_dump.formatting.VisState(self._is_visible[name], self._is_full[name], self._is_expanded[name])
            for _, name, _, _ in _CATEGORY_CONFIG
        }

    # Action handlers — category visibility and detail

    def _clear_overrides(self, category_name: str):
        """Reset per-block expanded overrides for a category."""
        cat = cc_dump.formatting.Category(category_name)
        conv = self._get_conv()
        if conv is None:
            return
        for td in conv._turns:
            for block in td.blocks:
                block_cat = cc_dump.tui.rendering.get_category(block)
                if block_cat == cat:
                    block.expanded = None  # reset to level default

    def action_toggle_vis(self, category: str):
        """Toggle hidden ↔ visible. ONLY changes _is_visible."""
        # Create new dict to trigger reactive watcher
        new_dict = dict(self._is_visible)
        new_dict[category] = not new_dict[category]
        self._is_visible = new_dict
        self._clear_overrides(category)

    def action_toggle_detail(self, category: str):
        """Toggle SUMMARY ↔ FULL. Sets visibility=True and toggles _is_full."""
        # Create new dicts to trigger reactive watchers
        new_visible = dict(self._is_visible)
        new_visible[category] = True
        self._is_visible = new_visible

        new_full = dict(self._is_full)
        new_full[category] = not new_full[category]
        self._is_full = new_full

        self._clear_overrides(category)

    def action_toggle_expand(self, category: str):
        """Toggle collapsed ↔ expanded. Sets visibility=True and toggles _is_expanded."""
        # Create new dicts to trigger reactive watchers
        new_visible = dict(self._is_visible)
        new_visible[category] = True
        self._is_visible = new_visible

        new_expanded = dict(self._is_expanded)
        new_expanded[category] = not new_expanded[category]
        self._is_expanded = new_expanded

        self._clear_overrides(category)

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
        self._update_footer_state()

    def action_go_top(self):
        """Scroll to top and disable follow mode."""
        conv = self._get_conv()
        if conv is not None:
            conv._follow_mode = False
            conv.scroll_home(animate=False)
        self._update_footer_state()

    def action_go_bottom(self):
        """Scroll to bottom and enable follow mode."""
        conv = self._get_conv()
        if conv is not None:
            conv.scroll_to_bottom()
        self._update_footer_state()

    def action_scroll_down_line(self):
        """Scroll down one line."""
        conv = self._get_conv()
        if conv is not None:
            conv.scroll_relative(y=1)

    def action_scroll_up_line(self):
        """Scroll up one line."""
        conv = self._get_conv()
        if conv is not None:
            conv.scroll_relative(y=-1)

    def action_scroll_left_col(self):
        """Scroll left one column."""
        conv = self._get_conv()
        if conv is not None:
            conv.scroll_relative(x=-1)

    def action_scroll_right_col(self):
        """Scroll right one column."""
        conv = self._get_conv()
        if conv is not None:
            conv.scroll_relative(x=1)

    def action_page_down(self):
        """Scroll down one page."""
        conv = self._get_conv()
        if conv is not None:
            conv.action_page_down()

    def action_page_up(self):
        """Scroll up one page."""
        conv = self._get_conv()
        if conv is not None:
            conv.action_page_up()

    def action_half_page_down(self):
        """Scroll down half a page."""
        conv = self._get_conv()
        if conv is not None:
            height = conv.scrollable_content_region.height
            conv.scroll_relative(y=height // 2)

    def action_half_page_up(self):
        """Scroll up half a page."""
        conv = self._get_conv()
        if conv is not None:
            height = conv.scrollable_content_region.height
            conv.scroll_relative(y=-(height // 2))

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

    # Reactive watchers - trigger re-render when category levels change

    def _rerender_if_mounted(self):
        """Re-render conversation if the app is mounted."""
        if self.is_running and not self._replacing_widgets:
            conv = self._get_conv()
            if conv is not None:
                conv.rerender(self.active_filters)
            self._update_footer_state()

    def _on_vis_state_changed(self):
        """Common handler for any visibility state change."""
        self._rerender_if_mounted()

    def watch__is_visible(self, value):
        self._on_vis_state_changed()

    def watch__is_full(self, value):
        self._on_vis_state_changed()

    def watch__is_expanded(self, value):
        self._on_vis_state_changed()

    def watch_show_economics(self, value):
        self._update_footer_state()

    def watch_show_timeline(self, value):
        self._update_footer_state()

    def watch_show_logs(self, value):
        pass  # visibility handled in action handler

    def watch_theme(self, theme_name: str) -> None:
        """Respond to Textual theme changes — rebuild all theme-derived state."""
        if not self.is_running:
            return
        cc_dump.tui.rendering.set_theme(self.current_theme)
        self._apply_markdown_theme()
        # Invalidate caches and rerender all content
        conv = self._get_conv()
        if conv is not None:
            conv._block_strip_cache.clear()
            conv._line_cache.clear()
            conv.rerender(self.active_filters)

    def _cycle_theme(self, direction: int) -> None:
        """Cycle to the next (+1) or previous (-1) theme.

        // [LAW:dataflow-not-control-flow] Always computes sorted list and
        // sets self.theme; watch_theme() handles all downstream effects.
        // [LAW:one-type-per-behavior] One method for both directions.
        """
        names = sorted(self.available_themes.keys())
        current_index = names.index(self.theme)
        new_index = (current_index + direction) % len(names)
        new_name = names[new_index]
        self.theme = new_name
        self.notify(f"Theme: {new_name}")

    def action_next_theme(self) -> None:
        """Cycle to the next theme alphabetically."""
        self._cycle_theme(1)

    def action_prev_theme(self) -> None:
        """Cycle to the previous theme alphabetically."""
        self._cycle_theme(-1)

    def action_dump_conversation(self) -> None:
        """Dump entire conversation to a temp file and optionally open in $VISUAL."""
        conv = self._get_conv()
        if conv is None or not conv._turns:
            self._log("WARNING", "No conversation data to dump")
            self.notify("No conversation to dump", severity="warning")
            return

        # [LAW:dataflow-not-control-flow] Always create file; vary behavior based on platform/env
        try:
            # Create temp file with .txt extension
            fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="cc-dump-")

            # Write conversation data
            with os.fdopen(fd, "w") as f:
                f.write("=" * 80 + "\n")
                f.write("CC-DUMP CONVERSATION EXPORT\n")
                f.write("=" * 80 + "\n\n")

                for turn_idx, turn_data in enumerate(conv._turns):
                    f.write(f"\n{'─' * 80}\n")
                    f.write(f"TURN {turn_idx + 1}\n")
                    f.write(f"{'─' * 80}\n\n")

                    for block_idx, block in enumerate(turn_data.blocks):
                        self._write_block_text(f, block, block_idx)
                        f.write("\n")

            self._log("INFO", f"Conversation dumped to: {tmp_path}")
            self.notify(f"Exported to: {tmp_path}")

            # On macOS with $VISUAL, open the file
            if platform.system() == "Darwin" and os.environ.get("VISUAL"):
                editor = os.environ["VISUAL"]
                self._log("INFO", f"Opening in $VISUAL ({editor})...")
                self.notify(f"Opening in {editor}...")

                try:
                    # Run editor with 20s timeout
                    result = subprocess.run(
                        [editor, tmp_path], timeout=20, capture_output=True, text=True
                    )
                    if result.returncode == 0:
                        self._log("INFO", "Editor opened successfully")
                    else:
                        self._log(
                            "WARNING", f"Editor exited with code {result.returncode}"
                        )
                except subprocess.TimeoutExpired:
                    self._log(
                        "WARNING",
                        "Editor timeout after 20s (still running in background)",
                    )
                    self.notify("Editor timeout (still open)", severity="warning")
                except Exception as e:
                    self._log("ERROR", f"Failed to open editor: {e}")
                    self.notify(f"Editor error: {e}", severity="error")

        except Exception as e:
            self._log("ERROR", f"Failed to dump conversation: {e}")
            self.notify(f"Dump failed: {e}", severity="error")

    def _write_block_text(self, f, block, block_idx: int) -> None:
        """Write a single block as text to file.

        // [LAW:one-type-per-behavior] Every block type has explicit handler
        // No generic fallback - unhandled types should raise, not silently lose data
        """
        block_type = type(block).__name__
        f.write(f"  [{block_idx}] {block_type}\n")
        f.write(f"  {'-' * 76}\n")

        # Handle different block types
        if isinstance(block, cc_dump.formatting.HeaderBlock):
            f.write(f"  {block.label}\n")
            if block.timestamp:
                f.write(f"  Timestamp: {block.timestamp}\n")

        elif isinstance(block, cc_dump.formatting.HttpHeadersBlock):
            f.write(f"  {block.header_type.upper()} Headers\n")
            if block.status_code:
                f.write(f"  Status: {block.status_code}\n")
            for key, value in block.headers.items():
                f.write(f"  {key}: {value}\n")

        elif isinstance(block, cc_dump.formatting.MetadataBlock):
            if block.model:
                f.write(f"  Model: {block.model}\n")
            if block.max_tokens:
                f.write(f"  Max tokens: {block.max_tokens}\n")
            f.write(f"  Stream: {block.stream}\n")
            if block.tool_count:
                f.write(f"  Tool count: {block.tool_count}\n")

        elif isinstance(block, cc_dump.formatting.SystemLabelBlock):
            f.write("  SYSTEM:\n")

        elif isinstance(block, cc_dump.formatting.TrackedContentBlock):
            f.write(f"  Status: {block.status}\n")
            if block.tag_id:
                f.write(f"  Tag ID: {block.tag_id}\n")
            if block.content:
                f.write(f"  Content: {block.content}\n")
            if block.old_content:
                f.write(f"  Old: {block.old_content}\n")
            if block.new_content:
                f.write(f"  New: {block.new_content}\n")

        elif isinstance(block, cc_dump.formatting.RoleBlock):
            f.write(f"  Role: {block.role}\n")
            if block.timestamp:
                f.write(f"  Timestamp: {block.timestamp}\n")

        elif isinstance(block, cc_dump.formatting.TextContentBlock):
            if block.text:
                f.write(f"  {block.text}\n")

        elif isinstance(block, cc_dump.formatting.ToolUseBlock):
            f.write(f"  Tool: {block.name}\n")
            f.write(f"  ID: {block.tool_use_id}\n")
            if block.detail:
                f.write(f"  Detail: {block.detail}\n")
            if block.input_size:
                f.write(f"  Input size: {block.input_size} bytes\n")

        elif isinstance(block, cc_dump.formatting.ToolResultBlock):
            f.write(f"  Tool: {block.tool_name}\n")
            f.write(f"  ID: {block.tool_use_id}\n")
            if block.detail:
                f.write(f"  Detail: {block.detail}\n")
            if block.is_error:
                f.write(f"  ERROR (size: {block.size} bytes)\n")
            else:
                f.write(f"  Result size: {block.size} bytes\n")

        elif isinstance(block, cc_dump.formatting.ToolUseSummaryBlock):
            f.write("  Tool counts:\n")
            for tool_name, count in block.tool_counts.items():
                f.write(f"    {tool_name}: {count}\n")
            f.write(f"  Total: {block.total}\n")

        elif isinstance(block, cc_dump.formatting.ImageBlock):
            f.write(f"  Media type: {block.media_type}\n")

        elif isinstance(block, cc_dump.formatting.UnknownTypeBlock):
            f.write(f"  Unknown block type: {block.block_type}\n")

        elif isinstance(block, cc_dump.formatting.StreamInfoBlock):
            f.write(f"  Model: {block.model}\n")

        elif isinstance(block, cc_dump.formatting.StreamToolUseBlock):
            f.write(f"  Tool: {block.name}\n")

        elif isinstance(block, cc_dump.formatting.TextDeltaBlock):
            if block.text:
                f.write(f"  {block.text}\n")

        elif isinstance(block, cc_dump.formatting.StopReasonBlock):
            f.write(f"  Stop reason: {block.reason}\n")

        elif isinstance(block, cc_dump.formatting.ErrorBlock):
            f.write(f"  Error: {block.code}\n")
            if block.reason:
                f.write(f"  Reason: {block.reason}\n")

        elif isinstance(block, cc_dump.formatting.ProxyErrorBlock):
            f.write(f"  Error: {block.error}\n")

        elif isinstance(block, cc_dump.formatting.TurnBudgetBlock):
            # Estimated tokens
            if block.budget.total_est:
                f.write(f"  total_est: {block.budget.total_est}\n")
            # Actual tokens (if available)
            if block.budget.actual_input_tokens:
                f.write(f"  Input tokens: {block.budget.actual_input_tokens}\n")
            if block.budget.actual_output_tokens:
                f.write(f"  Output tokens: {block.budget.actual_output_tokens}\n")
            if block.budget.actual_cache_creation_tokens:
                f.write(
                    f"  Cache creation: {block.budget.actual_cache_creation_tokens}\n"
                )
            if block.budget.actual_cache_read_tokens:
                f.write(f"  Cache read: {block.budget.actual_cache_read_tokens}\n")

        elif isinstance(block, cc_dump.formatting.SeparatorBlock):
            f.write(f"  (separator: {block.style})\n")

        elif isinstance(block, cc_dump.formatting.NewlineBlock):
            f.write("  (newline)\n")

        else:
            # Unhandled block type - should never happen if we keep this updated
            f.write(f"  (unhandled block type: {block_type})\n")
            self._log("WARNING", f"Unhandled block type in dump: {block_type}")

    def _apply_markdown_theme(self) -> None:
        """Push/replace markdown Rich theme on the console.

        Pops the old theme (if any) and pushes a fresh one from ThemeColors.
        Skips ANSI themes which use color names Rich can't parse.
        """
        # Skip markdown theme for ANSI-based Textual themes (Rich can't parse ansi_default etc.)
        if "ansi" in self.theme.lower():
            if hasattr(self, "_markdown_theme_pushed") and self._markdown_theme_pushed:
                try:
                    self.console.pop_theme()
                except Exception:
                    pass
                self._markdown_theme_pushed = False
            return

        tc = cc_dump.tui.rendering.get_theme_colors()
        from rich.theme import Theme as RichTheme

        # Pop old markdown theme if we pushed one before
        if hasattr(self, "_markdown_theme_pushed") and self._markdown_theme_pushed:
            try:
                self.console.pop_theme()
            except Exception:
                pass  # No theme to pop on first call
        self.console.push_theme(RichTheme(tc.markdown_theme_dict))
        self._markdown_theme_pushed = True

    # ─── Search ────────────────────────────────────────────────────────────

    async def on_key(self, event) -> None:
        """Mode-based key dispatcher.

        // [LAW:single-enforcer] on_key dispatches mode-mapped keys.
        // Keys not in our keymap pass through to Textual's binding resolution.
        """
        mode = self._input_mode
        MODE_KEYMAP = cc_dump.tui.input_modes.MODE_KEYMAP
        InputMode = cc_dump.tui.input_modes.InputMode

        # Mode-specific special key handling
        if mode == InputMode.NORMAL:
            if event.character == "/":
                event.prevent_default()
                self._start_search()
                return

        elif mode == InputMode.SEARCH_EDIT:
            # Text input mode: consume all keys
            event.prevent_default()
            self._handle_search_editing_key(event)
            return

        elif mode == InputMode.SEARCH_NAV:
            if self._handle_search_nav_special_keys(event):
                event.prevent_default()
                return

        # Generic keymap dispatch
        keymap = MODE_KEYMAP.get(mode, {})
        action_name = keymap.get(event.key)

        if action_name:
            event.prevent_default()
            await self.run_action(action_name)
            return

        # Unmapped key — let Textual handle it (tab, ctrl+c, etc.)

    def _handle_search_editing_key(self, event) -> None:
        """Handle keystrokes while editing the search query."""
        SearchMode = cc_dump.tui.search.SearchMode
        state = self._search_state
        key = event.key

        # Mode toggles (alt+key)
        _MODE_TOGGLES = {
            "alt+c": SearchMode.CASE_INSENSITIVE,
            "alt+w": SearchMode.WORD_BOUNDARY,
            "alt+r": SearchMode.REGEX,
            "alt+i": SearchMode.INCREMENTAL,
        }
        if key in _MODE_TOGGLES:
            state.modes ^= _MODE_TOGGLES[key]
            self._update_search_bar()
            if state.modes & SearchMode.INCREMENTAL:
                self._schedule_incremental_search()
            return

        # Submit
        if key == "enter":
            self._commit_search()
            return

        # Exit search - keep current position
        if key == "escape":
            self._exit_search_keep_position()
            return

        # Exit search - restore original position
        if key == "q":
            self._exit_search_restore_position()
            return

        # Backspace
        if key == "backspace":
            if state.cursor_pos > 0:
                state.query = (
                    state.query[: state.cursor_pos - 1]
                    + state.query[state.cursor_pos :]
                )
                state.cursor_pos -= 1
                self._update_search_bar()
                if state.modes & SearchMode.INCREMENTAL:
                    self._schedule_incremental_search()
            return

        # Delete
        if key == "delete":
            if state.cursor_pos < len(state.query):
                state.query = (
                    state.query[: state.cursor_pos]
                    + state.query[state.cursor_pos + 1 :]
                )
                self._update_search_bar()
                if state.modes & SearchMode.INCREMENTAL:
                    self._schedule_incremental_search()
            return

        # Cursor movement
        if key == "left":
            if state.cursor_pos > 0:
                state.cursor_pos -= 1
                self._update_search_bar()
            return

        if key == "right":
            if state.cursor_pos < len(state.query):
                state.cursor_pos += 1
                self._update_search_bar()
            return

        if key == "home":
            state.cursor_pos = 0
            self._update_search_bar()
            return

        if key == "end":
            state.cursor_pos = len(state.query)
            self._update_search_bar()
            return

        # Printable character
        if (
            event.character
            and len(event.character) == 1
            and event.character.isprintable()
        ):
            state.query = (
                state.query[: state.cursor_pos]
                + event.character
                + state.query[state.cursor_pos :]
            )
            state.cursor_pos += 1
            self._update_search_bar()
            if state.modes & SearchMode.INCREMENTAL:
                self._schedule_incremental_search()
            return

    def _handle_search_nav_special_keys(self, event) -> bool:
        """Handle search-specific keys in NAVIGATING mode.

        Returns True if key was handled, False if it should fall through to keymap.
        """
        SearchPhase = cc_dump.tui.search.SearchPhase
        key = event.key

        # Navigate next/prev
        if key == "n" or key == "enter":
            self._navigate_next()
            return True

        if key == "N":
            self._navigate_prev()
            return True

        # Re-edit query
        if event.character == "/":
            self._search_state.phase = SearchPhase.EDITING
            self._search_state.cursor_pos = len(self._search_state.query)
            self._update_search_bar()
            return True

        # Exit search - keep current position
        if key == "escape":
            self._exit_search_keep_position()
            return True

        # Exit search - restore original position
        if key == "q":
            self._exit_search_restore_position()
            return True

        return False

    def _start_search(self) -> None:
        """Transition: INACTIVE → EDITING. Save filter state and scroll position."""
        SearchPhase = cc_dump.tui.search.SearchPhase
        state = self._search_state
        state.phase = SearchPhase.EDITING
        state.query = ""
        state.cursor_pos = 0
        state.matches = []
        state.current_index = 0
        state.expanded_blocks = []
        state.raised_categories = set()
        # Save current filter state for restore on cancel
        state.saved_filters = {
            name: (
                self._is_visible[name],
                self._is_full[name],
                self._is_expanded[name],
            )
            for _, name, _, _ in _CATEGORY_CONFIG
        }
        # Save current scroll position
        conv = self._get_conv()
        if conv is not None:
            state.saved_scroll_y = conv.scroll_offset.y
        else:
            state.saved_scroll_y = None
        self._update_search_bar()

    def _exit_search_common(self) -> None:
        """Common cleanup when exiting search (any mode)."""
        SearchPhase = cc_dump.tui.search.SearchPhase
        state = self._search_state

        # Clear block expansion overrides we set
        self._clear_search_expand()

        # Restore saved filter levels (all three dicts) - create new dicts to trigger watchers
        new_visible = {}
        new_full = {}
        new_expanded = {}
        for name, (is_visible, is_full, is_expanded) in state.saved_filters.items():
            new_visible[name] = is_visible
            new_full[name] = is_full
            new_expanded[name] = is_expanded
        self._is_visible = new_visible
        self._is_full = new_full
        self._is_expanded = new_expanded

        # Reset state
        state.phase = SearchPhase.INACTIVE
        state.query = ""
        state.matches = []
        state.current_index = 0
        state.expanded_blocks = []
        state.raised_categories = set()

        # Cancel debounce timer
        if state.debounce_timer is not None:
            state.debounce_timer.stop()
            state.debounce_timer = None

        self._update_search_bar()
        # Re-render without search context (highlights removed)
        conv = self._get_conv()
        if conv is not None:
            conv.rerender(self.active_filters)

    def _exit_search_keep_position(self) -> None:
        """Exit search and stay at current scroll position (Esc)."""
        self._exit_search_common()
        # Don't restore scroll — stay where we are

    def _exit_search_restore_position(self) -> None:
        """Exit search and restore original scroll position (q)."""
        self._exit_search_common()
        # Restore scroll position to where we were before search
        state = self._search_state
        if state.saved_scroll_y is not None:
            conv = self._get_conv()
            if conv is not None:
                conv.scroll_to(y=state.saved_scroll_y, animate=False)
        state.saved_scroll_y = None

    def _commit_search(self) -> None:
        """Transition: EDITING → NAVIGATING. Run final search, navigate to first result."""
        SearchPhase = cc_dump.tui.search.SearchPhase
        state = self._search_state

        # Cancel debounce timer
        if state.debounce_timer is not None:
            state.debounce_timer.stop()
            state.debounce_timer = None

        # Run search
        self._run_search()

        if state.matches:
            state.phase = SearchPhase.NAVIGATING
            state.current_index = 0
            self._navigate_to_current()
        else:
            state.phase = SearchPhase.NAVIGATING

        self._update_search_bar()

    def _schedule_incremental_search(self) -> None:
        """Schedule a debounced incremental search (150ms)."""
        state = self._search_state
        if state.debounce_timer is not None:
            state.debounce_timer.stop()
        state.debounce_timer = self.set_timer(0.15, self._run_incremental_search)

    def _run_incremental_search(self) -> None:
        """Execute incremental search during editing."""
        state = self._search_state
        state.debounce_timer = None
        self._run_search()
        # Re-render with search highlights
        self._search_rerender()
        self._update_search_bar()

    def _run_search(self) -> None:
        """Compile pattern and find all matches."""
        state = self._search_state
        pattern = cc_dump.tui.search.compile_search_pattern(state.query, state.modes)
        if pattern is None:
            state.matches = []
            state.current_index = 0
            return

        conv = self._get_conv()
        if conv is None:
            state.matches = []
            return

        state.matches = cc_dump.tui.search.find_all_matches(conv._turns, pattern)
        # Clamp current_index
        if state.current_index >= len(state.matches):
            state.current_index = 0

    def _navigate_next(self) -> None:
        """Move to next match (wraps around)."""
        state = self._search_state
        if not state.matches:
            return
        state.current_index = (state.current_index + 1) % len(state.matches)
        self._navigate_to_current()

    def _navigate_prev(self) -> None:
        """Move to previous match (wraps around)."""
        state = self._search_state
        if not state.matches:
            return
        state.current_index = (state.current_index - 1) % len(state.matches)
        self._navigate_to_current()

    def _navigate_to_current(self) -> None:
        """Navigate to the current match: raise category, expand block, scroll."""
        state = self._search_state
        if not state.matches:
            return

        match = state.matches[state.current_index]
        conv = self._get_conv()
        if conv is None:
            return

        # Clear previous expansion
        self._clear_search_expand()

        # Get the block
        if match.turn_index >= len(conv._turns):
            return
        td = conv._turns[match.turn_index]
        if match.block_index >= len(td.blocks):
            return
        block = td.blocks[match.block_index]

        # Raise category visibility to FULL if needed
        cat = cc_dump.tui.rendering.get_category(block)
        if cat is not None:
            cat_name = cat.value
            # Check if currently at FULL level (visible=True, full=True)
            current_is_full = self._is_visible[cat_name] and self._is_full[cat_name]
            if not current_is_full:
                # Raise to FULL - create new dicts to trigger watchers
                new_visible = dict(self._is_visible)
                new_visible[cat_name] = True
                self._is_visible = new_visible

                new_full = dict(self._is_full)
                new_full[cat_name] = True
                self._is_full = new_full

                state.raised_categories.add(cat_name)

        # Expand the specific block
        block.expanded = True
        state.expanded_blocks.append((match.turn_index, match.block_index))

        # Re-render with search context and scroll
        self._search_rerender()
        conv.scroll_to_block(match.turn_index, match.block_index)
        self._update_search_bar()

    def _clear_search_expand(self) -> None:
        """Reset block.expanded on blocks we expanded during search."""
        conv = self._get_conv()
        if conv is None:
            return
        state = self._search_state
        for turn_idx, block_idx in state.expanded_blocks:
            if turn_idx < len(conv._turns):
                td = conv._turns[turn_idx]
                if block_idx < len(td.blocks):
                    td.blocks[block_idx].expanded = None
        state.expanded_blocks.clear()

    def _search_rerender(self) -> None:
        """Re-render conversation with search highlights."""
        state = self._search_state
        conv = self._get_conv()
        if conv is None:
            return

        pattern = cc_dump.tui.search.compile_search_pattern(state.query, state.modes)
        search_ctx = None
        if pattern is not None:
            current_match = (
                state.matches[state.current_index] if state.matches else None
            )
            search_ctx = cc_dump.tui.search.SearchContext(
                pattern=pattern,
                pattern_str=state.query,
                current_match=current_match,
                all_matches=state.matches,
            )

        conv.rerender(self.active_filters, search_ctx=search_ctx)

    def _update_search_bar(self) -> None:
        """Update the search bar widget display and toggle Footer visibility."""
        SearchPhase = cc_dump.tui.search.SearchPhase
        bar = self._get_search_bar()
        footer = self._get_footer()

        if bar is not None:
            bar.update_display(self._search_state)

        # Footer hidden when search is active, visible when inactive
        search_active = self._search_state.phase != SearchPhase.INACTIVE
        if footer is not None:
            footer.display = not search_active

    def on_unmount(self):
        """Clean up when app exits."""
        self._log("INFO", "cc-dump TUI shutting down")
        self._closing = True
        self._router.stop()
