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
import cc_dump.tui.rendering
import cc_dump.tui.widget_factory
import cc_dump.tui.event_handlers


# [LAW:one-source-of-truth] [LAW:one-type-per-behavior]
# (key, category, description, default_level, default_detail)
_CATEGORY_CONFIG = [
    ("h", "headers", "h|eaders", 1, 2),
    ("u", "user", "u|ser", 3, 3),
    ("a", "assistant", "a|ssistant", 3, 3),
    ("t", "tools", "t|ools", 2, 2),
    ("s", "system", "s|ystem", 2, 2),
    ("e", "budget", "budg|e|t", 1, 2),
    ("m", "metadata", "m|etadata", 1, 2),
]

# Build lookup dicts from config
_VIS_ATTR = {name: f"vis_{name}" for _, name, _, _, _ in _CATEGORY_CONFIG}
_DEFAULT_DETAIL = {name: detail for _, name, _, _, detail in _CATEGORY_CONFIG}


class CcDumpApp(App):
    """TUI application for cc-dump."""

    CSS_PATH = "styles.css"

    # Generate BINDINGS from config
    BINDINGS = []
    for key, name, desc, _, _ in _CATEGORY_CONFIG:
        BINDINGS.append(Binding(key, f"toggle_vis('{name}')", desc, show=True))
        BINDINGS.append(Binding(key.upper(), f"toggle_detail('{name}')", show=False))
        BINDINGS.append(
            Binding(f"ctrl+shift+{key}", f"toggle_expand('{name}')", show=False)
        )
    # Non-category bindings stay explicit
    BINDINGS.extend(
        [
            Binding("c", "toggle_economics", "c|ost", show=True),
            Binding("l", "toggle_timeline", "time|l|ine", show=True),
            Binding("ctrl+l", "toggle_logs", "Logs", show=False),
            Binding("C", "toggle_economics_breakdown", "Model breakdown", show=False),
            Binding("f", "toggle_follow", "f|ollow", show=True),
        ]
    )

    # Category visibility levels (3-state cycle: EXISTENCE → SUMMARY → FULL → EXISTENCE)
    vis_headers = reactive(1)  # Level.EXISTENCE
    vis_user = reactive(3)  # Level.FULL
    vis_assistant = reactive(3)  # Level.FULL
    vis_tools = reactive(2)  # Level.SUMMARY
    vis_system = reactive(2)  # Level.SUMMARY
    vis_metadata = reactive(1)  # Level.EXISTENCE
    vis_budget = reactive(1)  # Level.EXISTENCE
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

        # Remember detail level when toggling visibility
        self._remembered_detail = dict(_DEFAULT_DETAIL)

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

    def _get_footer(self):
        try:
            return self.query_one(StyledFooter)
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

                # Add request turn
                conv.add_turn(request_blocks)

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

                # Add response turn
                conv.add_turn(response_blocks)

                # Update stats
                if stats:
                    stats.update_stats(requests=self._state["request_counter"])

            except Exception as e:
                self._log("ERROR", f"Error processing replay pair: {e}")

        self._log(
            "INFO",
            f"Replay complete: {self._state['request_counter']} requests processed",
        )

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
        """Current filter state as a dict (category name -> Level int)."""
        Level = cc_dump.formatting.Level

        return {
            "headers": Level(self.vis_headers),
            "tools": Level(self.vis_tools),
            "system": Level(self.vis_system),
            "budget": Level(self.vis_budget),
            "metadata": Level(self.vis_metadata),
            "user": Level(self.vis_user),
            "assistant": Level(self.vis_assistant),
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
        """Toggle hidden (1) ↔ visible (remembered detail level)."""
        attr = _VIS_ATTR[category]
        current = getattr(self, attr)
        if current > 1:
            self._remembered_detail[category] = current
            setattr(self, attr, 1)
        else:
            setattr(self, attr, self._remembered_detail[category])
        self._clear_overrides(category)

    def action_toggle_detail(self, category: str):
        """Toggle SUMMARY (2) ↔ FULL (3). If hidden, show at opposite of remembered."""
        attr = _VIS_ATTR[category]
        current = getattr(self, attr)
        if current <= 1:
            # Hidden → show at OPPOSITE of remembered (toggle while showing)
            remembered = self._remembered_detail[category]
            new_level = 2 if remembered == 3 else 3
            setattr(self, attr, new_level)
            self._remembered_detail[category] = new_level
        elif current == 2:
            setattr(self, attr, 3)
            self._remembered_detail[category] = 3
        else:
            setattr(self, attr, 2)
            self._remembered_detail[category] = 2
        self._clear_overrides(category)

    def action_toggle_expand(self, category: str):
        """Toggle all blocks in category between expanded and collapsed."""
        cat = cc_dump.formatting.Category(category)
        level = cc_dump.formatting.Level(getattr(self, _VIS_ATTR[category]))
        default_exp = cc_dump.tui.rendering.DEFAULT_EXPANDED[level]
        conv = self._get_conv()
        if conv is None:
            return
        # If any block is at default → set all to opposite. Else reset all to default.
        target = not default_exp  # toggle direction
        for td in conv._turns:
            for block in td.blocks:
                if cc_dump.tui.rendering.get_category(block) == cat:
                    current = (
                        block.expanded if block.expanded is not None else default_exp
                    )
                    if current == default_exp:
                        # Found one at default → confirm toggle to opposite
                        break
            else:
                continue
            break
        else:
            target = default_exp  # all already toggled → reset to default (None)
        for td in conv._turns:
            for block in td.blocks:
                if cc_dump.tui.rendering.get_category(block) == cat:
                    block.expanded = None if target == default_exp else target
        conv.rerender(self.active_filters)
        self._update_footer_state()

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

    def watch_vis_headers(self, value):
        self._rerender_if_mounted()

    def watch_vis_user(self, value):
        self._rerender_if_mounted()

    def watch_vis_assistant(self, value):
        self._rerender_if_mounted()

    def watch_vis_tools(self, value):
        self._rerender_if_mounted()

    def watch_vis_system(self, value):
        self._rerender_if_mounted()

    def watch_vis_budget(self, value):
        self._rerender_if_mounted()

    def watch_vis_metadata(self, value):
        self._rerender_if_mounted()

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
