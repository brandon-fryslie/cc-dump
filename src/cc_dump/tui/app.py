"""Main TUI application using Textual.

// [LAW:locality-or-seam] Thin coordinator — delegates to extracted modules:
//   category_config, action_handlers, search_controller, dump_export,
//   theme_controller, hot_reload_controller.
// [LAW:one-source-of-truth] Reactive dicts (_is_visible, _is_full, _is_expanded)
//   are the sole state for visibility. active_filters is derived.
"""

import os
import queue
import threading
from typing import Optional, TypedDict

from textual.app import App, ComposeResult, SystemCommand
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Header

from cc_dump.tui.category_config import CATEGORY_CONFIG

# Module-level imports for hot-reload (never use `from` for these)
import cc_dump.formatting
import cc_dump.settings
import cc_dump.tui.rendering
import cc_dump.tui.widget_factory
import cc_dump.tui.event_handlers
import cc_dump.tui.search
import cc_dump.tui.input_modes
import cc_dump.tui.info_panel
import cc_dump.tui.custom_footer
import cc_dump.tui.session_panel

# Extracted controller modules (not hot-reloadable, safe for `from` imports)
from cc_dump.tui import action_handlers as _actions
from cc_dump.tui.panel_registry import PANEL_REGISTRY, PANEL_ORDER, PANEL_CSS_IDS
from cc_dump.tui import search_controller as _search
from cc_dump.tui import dump_export as _dump
from cc_dump.tui import theme_controller as _theme
from cc_dump.tui import hot_reload_controller as _hot_reload


def _resolve_factory(dotted_path: str):
    """Resolve a dotted factory path like 'cc_dump.tui.widget_factory.create_stats_panel'.

    Uses importlib to resolve the module, then getattr for the function.
    This allows the registry to reference functions across modules.
    """
    parts = dotted_path.rsplit(".", 1)
    module_path, func_name = parts[0], parts[1]
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, func_name)


class TurnUsage(TypedDict, total=False):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int


class AppState(TypedDict, total=False):
    current_turn_usage: TurnUsage
    pending_request_headers: dict[str, str]
    new_session_id: str


class NewSession(Message):
    """Message posted when a new Claude Code session is detected."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__()


class CcDumpApp(App):
    """TUI application for cc-dump."""

    CSS_PATH = "styles.css"

    # [LAW:one-source-of-truth] Three orthogonal reactive dicts for visibility state
    _is_visible: reactive[dict[str, bool]] = reactive({})
    _is_full: reactive[dict[str, bool]] = reactive({})
    _is_expanded: reactive[dict[str, bool]] = reactive({})

    # Panel visibility
    # [LAW:one-source-of-truth] active_panel cycles through PANEL_ORDER
    active_panel = reactive("session")
    show_logs = reactive(False)
    show_info = reactive(False)

    def __init__(
        self,
        event_queue,
        state,
        router,
        analytics_store=None,
        session_name: str = "unnamed-session",
        host: str = "127.0.0.1",
        port: int = 3344,
        target: Optional[str] = None,
        replay_data: Optional[list] = None,
        recording_path: Optional[str] = None,
        replay_file: Optional[str] = None,
        tmux_controller=None,
    ):
        super().__init__()
        self._event_queue = event_queue
        self._state = state
        self._router = router
        self._analytics_store = analytics_store
        self._session_id: str | None = None
        self._session_name = session_name
        self._host = host
        self._port = port
        self._target = target
        self._replay_data = replay_data
        self._recording_path = recording_path
        self._replay_file = replay_file
        self._tmux_controller = tmux_controller
        self._closing = False
        self._quit_requested_at: float | None = None
        self._replacing_widgets = False
        self._markdown_theme_pushed = False
        import cc_dump.palette

        self.sub_title = f"[{cc_dump.palette.PALETTE.info}]session: {session_name}[/]"

        self._replay_complete = threading.Event()
        if not replay_data:
            self._replay_complete.set()

        self._app_state: AppState = {"current_turn_usage": {}}

        # [LAW:one-source-of-truth] Initialize from CATEGORY_CONFIG
        self._is_visible = {name: d.visible for _, name, _, d in CATEGORY_CONFIG}
        self._is_full = {name: d.full for _, name, _, d in CATEGORY_CONFIG}
        self._is_expanded = {name: d.expanded for _, name, _, d in CATEGORY_CONFIG}

        self._search_state = cc_dump.tui.search.SearchState()
        self._active_filterset_slot = None

        # Settings panel state
        self._settings_panel_open: bool = False
        self._settings_fields: list = []  # list[FieldState] from settings_panel
        self._settings_active_field: int = 0

        # Exception tracking for error indicator
        self._exception_items: list = []

        self._conv_id = "conversation-view"
        self._search_bar_id = "search-bar"
        # [LAW:one-source-of-truth] Panel IDs derived from registry
        self._panel_ids = dict(PANEL_CSS_IDS)
        self._logs_id = "logs-panel"
        self._info_id = "info-panel"

    # ─── Derived state ─────────────────────────────────────────────────

    @property
    def _input_mode(self):
        """// [LAW:one-source-of-truth] InputMode derived from app state."""
        InputMode = cc_dump.tui.input_modes.InputMode
        if self._settings_panel_open:
            return InputMode.SETTINGS
        SearchPhase = cc_dump.tui.search.SearchPhase
        phase = self._search_state.phase
        if phase == SearchPhase.EDITING:
            return InputMode.SEARCH_EDIT
        if phase == SearchPhase.NAVIGATING:
            return InputMode.SEARCH_NAV
        return InputMode.NORMAL

    @property
    def active_filters(self):
        """// [LAW:one-source-of-truth] Assembled from three reactive dicts."""
        return {
            name: cc_dump.formatting.VisState(
                self._is_visible[name], self._is_full[name], self._is_expanded[name]
            )
            for _, name, _, _ in CATEGORY_CONFIG
        }

    # ─── Widget accessors ──────────────────────────────────────────────

    def _query_safe(self, selector):
        try:
            return self.query_one(selector)
        except NoMatches:
            return None

    def _get_conv(self):
        return self._query_safe("#" + self._conv_id)

    def _get_panel(self, name: str):
        """// [LAW:one-source-of-truth] Generic panel accessor using registry IDs."""
        css_id = self._panel_ids.get(name)
        if css_id is None:
            return None
        return self._query_safe("#" + css_id)

    def _get_stats(self):
        return self._get_panel("stats")

    def _get_economics(self):
        return self._get_panel("economics")

    def _get_timeline(self):
        return self._get_panel("timeline")

    def _get_logs(self):
        return self._query_safe("#" + self._logs_id)

    def _get_info(self):
        return self._query_safe("#" + self._info_id)

    def _get_search_bar(self):
        return self._query_safe("#" + self._search_bar_id)

    def _get_footer(self):
        try:
            return self.query_one(cc_dump.tui.custom_footer.StatusFooter)
        except NoMatches:
            return None

    # ─── Lifecycle ─────────────────────────────────────────────────────

    def get_system_commands(self, screen):
        for cmd in super().get_system_commands(screen):
            if cmd.title == "Keys":
                continue  # Replace with our version
            yield cmd
        yield SystemCommand(
            "Keys", "Show keyboard shortcuts", self.action_toggle_keys
        )
        yield SystemCommand(
            "Cycle panel", "Cycle stats/economics/timeline", self.action_cycle_panel
        )
        yield SystemCommand("Toggle logs", "Debug logs", self.action_toggle_logs)
        yield SystemCommand("Toggle info", "Server info panel", self.action_toggle_info)
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

        # [LAW:one-source-of-truth] Cycling panels from registry
        for spec in PANEL_REGISTRY:
            widget = _resolve_factory(spec.factory)()
            widget.id = self._panel_ids[spec.name]
            yield widget

        conv = cc_dump.tui.widget_factory.create_conversation_view()
        conv.id = self._conv_id
        yield conv

        logs = cc_dump.tui.widget_factory.create_logs_panel()
        logs.id = self._logs_id
        yield logs

        info = cc_dump.tui.info_panel.create_info_panel()
        info.id = self._info_id
        yield info

        search_bar = cc_dump.tui.search.SearchBar()
        search_bar.id = self._search_bar_id
        yield search_bar

        yield cc_dump.tui.custom_footer.StatusFooter()

    def on_mount(self):
        # [LAW:one-source-of-truth] Restore persisted theme choice
        saved = cc_dump.settings.load_theme()
        if saved and saved in self.available_themes:
            self.theme = saved
        cc_dump.tui.rendering.set_theme(self.current_theme)
        self._apply_markdown_theme()

        # Connect stderr tee to LogsPanel (flushes buffered pre-TUI messages)
        # stderr_tee is a stable boundary — safe to use `from` import
        from cc_dump.stderr_tee import get_tee as _get_tee
        tee = _get_tee()
        if tee is not None:
            def _drain(level, source, message):
                formatted = f"[{source}] {message}" if source != "stderr" else message
                self.call_from_thread(self._app_log, level, formatted)
            tee.connect(_drain)

        self._app_log("INFO", "🚀 cc-dump proxy started")
        self._app_log("INFO", f"Listening on: http://{self._host}:{self._port}")

        if self._target:
            self._app_log("INFO", f"Reverse proxy mode: {self._target}")
            self._app_log(
                "INFO",
                f"Usage: ANTHROPIC_BASE_URL=http://{self._host}:{self._port} claude",
            )
        else:
            self._app_log("INFO", "Forward proxy mode (dynamic targets)")
            self._app_log(
                "INFO",
                f"Usage: HTTP_PROXY=http://{self._host}:{self._port} ANTHROPIC_BASE_URL=http://api.minimax.com claude",
            )

        self.run_worker(self._drain_events, thread=True, exclusive=False)

        # Set initial panel visibility — cycle panels via active_panel
        self._sync_panel_display(self.active_panel)
        logs = self._get_logs()
        if logs is not None:
            logs.display = self.show_logs
        info = self._get_info()
        if info is not None:
            info.display = self.show_info
            info.update_info(self._build_server_info())

        self._update_footer_state()

        if self._replay_data:
            self._process_replay_data()

    def action_quit(self) -> None:
        import time
        now = time.monotonic()
        if self._quit_requested_at is not None and (now - self._quit_requested_at) < 1.0:
            self.exit()
            return
        self._quit_requested_at = now
        self.notify("Press Ctrl+C again to quit", timeout=1)

    def on_unmount(self):
        # Disconnect stderr tee before teardown
        from cc_dump.stderr_tee import get_tee as _get_tee
        tee = _get_tee()
        if tee is not None:
            tee.disconnect()

        self._app_log("INFO", "cc-dump TUI shutting down")
        self._closing = True
        self._router.stop()

    def _handle_exception(self, error: Exception) -> None:
        """// [LAW:single-enforcer] Top-level exception handler - keeps proxy running.

        Logs unhandled exceptions with normal Python traceback. Adds exception
        to error indicator. Does NOT crash to keep proxy server running.
        """
        import traceback
        import cc_dump.tui.error_indicator

        # Get normal Python traceback (not Textual's verbose one)
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))

        # Log to LogsPanel
        self._app_log("ERROR", f"Unhandled exception: {error}")
        for line in tb.split("\n"):
            if line:
                self._app_log("ERROR", line)

        # Add to error indicator (top-right overlay)
        exc_item = cc_dump.tui.error_indicator.ErrorItem(
            id=f"exc-{id(error)}",
            icon="💥",
            summary=f"{type(error).__name__}: {error}"
        )
        self._exception_items.append(exc_item)
        self._update_error_indicator()

        # DON'T call super() - keep running, hot reload will fix it

    # ─── Helpers ───────────────────────────────────────────────────────

    def _app_log(self, level: str, message: str):
        if self.is_running:
            logs = self._get_logs()
            if logs is not None:
                logs.app_log(level, message)

    def _update_footer_state(self):
        if self.is_running:
            footer = self._get_footer()
            if footer is not None:
                conv = self._get_conv()
                tmux = self._tmux_controller
                import cc_dump.tmux_controller
                _TMUX_ACTIVE = {
                    cc_dump.tmux_controller.TmuxState.READY,
                    cc_dump.tmux_controller.TmuxState.CLAUDE_RUNNING,
                }
                state = {
                    **self.active_filters,
                    "active_panel": self.active_panel,
                    "follow_state": conv._follow_state if conv is not None else cc_dump.tui.widget_factory.FollowState.ACTIVE,
                    "active_filterset": self._active_filterset_slot,
                    "tmux_available": tmux is not None and tmux.state in _TMUX_ACTIVE,
                    "tmux_auto_zoom": tmux.auto_zoom if tmux is not None else False,
                    "tmux_zoomed": tmux._is_zoomed if tmux is not None else False,
                }
                footer.update_display(state)
            self._update_error_indicator()

    def _update_error_indicator(self):
        """Push stale-file and exception errors to ConversationView's overlay indicator."""
        conv = self._get_conv()
        if conv is None:
            return
        stale = getattr(self, "_stale_files", [])
        import cc_dump.tui.error_indicator
        ErrorItem = cc_dump.tui.error_indicator.ErrorItem
        # // [LAW:dataflow-not-control-flow] Always build items list; empty list = no indicator.
        items = [
            ErrorItem("stale", "\u274c", s.split("/")[-1])
            for s in stale
        ]
        # Add caught exceptions
        items.extend(self._exception_items)
        conv.update_error_items(items)

    def _build_server_info(self) -> dict:
        """// [LAW:one-source-of-truth] All server info derived from constructor params."""
        import sys
        import textual
        import cc_dump.sessions

        proxy_url = "http://{}:{}".format(self._host, self._port)
        proxy_mode = "forward" if not self._target else "reverse"

        return {
            "proxy_url": proxy_url,
            "proxy_mode": proxy_mode,
            "target": self._target,
            "session_name": self._session_name,
            "session_id": self._session_id,
            "recording_path": self._recording_path,
            "recording_dir": cc_dump.sessions.get_recordings_dir(),
            "replay_file": self._replay_file,
            "python_version": sys.version.split()[0],
            "textual_version": textual.__version__,
            "pid": os.getpid(),
        }

    def _rerender_if_mounted(self):
        if self.is_running and not self._replacing_widgets:
            conv = self._get_conv()
            if conv is not None:
                conv.rerender(self.active_filters)
            self._update_footer_state()

    # ─── Event pipeline ────────────────────────────────────────────────

    def _process_replay_data(self):
        if not self._replay_data:
            return

        self._app_log("INFO", f"Processing {len(self._replay_data)} request/response pairs")
        conv = self._get_conv()
        stats = self._get_stats()
        if conv is None:
            self._app_log("ERROR", "Cannot process replay: conversation widget not found")
            return

        for (
            req_headers,
            req_body,
            resp_status,
            resp_headers,
            complete_message,
        ) in self._replay_data:
            try:
                request_blocks = cc_dump.formatting.format_request(
                    req_body, self._state, request_headers=req_headers
                )
                conv.add_turn(request_blocks, self.active_filters)

                # [LAW:dataflow-not-control-flow] Always emit response header blocks;
                # format_response_headers handles empty headers via empty dict
                response_blocks = list(
                    cc_dump.formatting.format_response_headers(
                        resp_status, resp_headers or {}
                    )
                )
                response_blocks.extend(
                    cc_dump.formatting.format_complete_response(complete_message)
                )
                # // [LAW:one-source-of-truth] Stamp response blocks with current session
                current_session = self._state.get("current_session", "")
                for block in response_blocks:
                    block.session_id = current_session
                conv.add_turn(response_blocks, self.active_filters)

                if stats:
                    stats.update_stats(requests=self._state["request_counter"])
            except Exception as e:
                self._app_log("ERROR", f"Error processing replay pair: {e}")

        if stats and self._analytics_store:
            stats.refresh_from_store(self._analytics_store)

        self._app_log(
            "INFO",
            f"Replay complete: {self._state['request_counter']} requests processed",
        )
        self._replay_complete.set()

    def _drain_events(self):
        self._replay_complete.wait()
        while not self._closing:
            try:
                event = self._event_queue.get(timeout=1.0)
            except queue.Empty:
                self.call_from_thread(self._check_hot_reload)
                continue
            except Exception as e:
                if self._closing:
                    break
                self.call_from_thread(self._app_log, "ERROR", f"Event queue error: {e}")
                continue
            self.call_from_thread(self._check_hot_reload)
            self.call_from_thread(self._handle_event, event)

    def _handle_event(self, event):
        try:
            self._handle_event_inner(event)
        except Exception as e:
            self._app_log("ERROR", f"Uncaught exception handling event: {e}")
            import traceback

            tb = traceback.format_exc()
            for line in tb.split("\n"):
                if line:
                    self._app_log("ERROR", f"  {line}")

    def _handle_event_inner(self, event):
        if self._replacing_widgets:
            return

        kind = event.kind
        conv = self._get_conv()
        stats = self._get_stats()
        if conv is None or stats is None:
            return

        # [LAW:dataflow-not-control-flow] Unified context dict
        widgets = {
            "conv": conv,
            "stats": stats,
            "filters": self.active_filters,
            "refresh_callbacks": {
                "refresh_economics": self._refresh_economics,
                "refresh_timeline": self._refresh_timeline,
                "refresh_session": self._refresh_session,
            },
            "analytics_store": self._analytics_store,
        }

        # [LAW:dataflow-not-control-flow] Always call handler, use no-op for unknown
        handler = cc_dump.tui.event_handlers.EVENT_HANDLERS.get(
            kind, cc_dump.tui.event_handlers._noop
        )
        self._app_state = handler(
            event, self._state, widgets, self._app_state, self._app_log
        )

        # Check for new session signal from handler
        new_session_id = self._app_state.pop("new_session_id", None)
        if new_session_id:
            self._session_id = new_session_id
            self.post_message(NewSession(new_session_id))
            self.notify(f"New session: {new_session_id[:8]}...")

    # ─── Delegates to extracted modules ────────────────────────────────
    # Textual requires action_* and watch_* as methods on the App class.

    # Hot-reload
    async def _check_hot_reload(self):
        await _hot_reload.check_hot_reload(self)

    # Theme
    def _apply_markdown_theme(self):
        _theme.apply_markdown_theme(self)

    def action_next_theme(self):
        _theme.cycle_theme(self, 1)

    def action_prev_theme(self):
        _theme.cycle_theme(self, -1)

    # Dump/export
    def action_dump_conversation(self):
        _dump.dump_conversation(self)

    def _write_block_text(self, f, block, block_idx: int):
        _dump.write_block_text(f, block, block_idx, log_fn=self._app_log)

    # Visibility actions
    def action_toggle_vis(self, category: str):
        _actions.toggle_vis(self, category)

    def action_toggle_detail(self, category: str):
        _actions.toggle_detail(self, category)

    def action_toggle_expand(self, category: str):
        _actions.toggle_expand(self, category)

    def action_cycle_vis(self, category: str):
        _actions.cycle_vis(self, category)

    def _clear_overrides(self, category_name: str):
        _actions.clear_overrides(self, category_name)

    # Filterset actions
    def action_save_filterset(self, slot: str):
        _actions.save_filterset(self, slot)

    def action_apply_filterset(self, slot: str):
        _actions.apply_filterset(self, slot)

    def action_next_filterset(self):
        _actions.next_filterset(self)

    def action_prev_filterset(self):
        _actions.prev_filterset(self)

    # Panel cycling
    def action_cycle_panel(self):
        _actions.cycle_panel(self)

    def action_cycle_panel_mode(self):
        _actions.cycle_panel_mode(self)

    def action_toggle_logs(self):
        _actions.toggle_logs(self)

    def action_toggle_info(self):
        _actions.toggle_info(self)

    def action_toggle_keys(self):
        _actions.toggle_keys(self)

    # Override Textual's built-in help panel to use ours
    def action_show_help_panel(self):
        _actions.toggle_keys(self)

    def action_hide_help_panel(self):
        _actions.toggle_keys(self)

    # Tmux integration
    def action_launch_claude(self):
        tmux = self._tmux_controller
        if tmux is None:
            self.notify("Tmux not available", severity="warning")
            return
        import cc_dump.tmux_controller
        if tmux.state == cc_dump.tmux_controller.TmuxState.CLAUDE_RUNNING:
            if tmux.focus_claude():
                self.notify("Focused claude pane")
            else:
                self.notify("Failed to focus claude pane", severity="error")
        elif tmux.state == cc_dump.tmux_controller.TmuxState.READY:
            if tmux.launch_claude():
                self.notify("Launched claude in tmux pane")
                self._update_footer_state()
            else:
                self.notify("Failed to launch claude", severity="error")
        else:
            self.notify("Tmux not available", severity="warning")

    def action_toggle_tmux_zoom(self):
        tmux = self._tmux_controller
        if tmux is None:
            self.notify("Tmux not available", severity="warning")
            return
        tmux.toggle_zoom()
        self._update_footer_state()

    def action_toggle_auto_zoom(self):
        tmux = self._tmux_controller
        if tmux is None:
            self.notify("Tmux not available", severity="warning")
            return
        tmux.toggle_auto_zoom()
        label = "on" if tmux.auto_zoom else "off"
        self.notify("Auto-zoom: {}".format(label))
        self._update_footer_state()

    # Settings
    def action_toggle_settings(self):
        _actions.toggle_settings(self)

    def _open_settings(self):
        """Open settings panel, populating editing state from saved settings."""
        import cc_dump.tui.settings_panel

        fields = []
        for field_def in cc_dump.tui.settings_panel.SETTINGS_FIELDS:
            value = cc_dump.settings.load_setting(field_def.key, field_def.default)
            fields.append(field_def.make_state(value))
        self._settings_fields = fields
        self._settings_active_field = 0
        self._settings_panel_open = True

        panel = cc_dump.tui.settings_panel.create_settings_panel()
        self.screen.mount(panel)
        self._update_settings_panel_display()
        self._update_footer_state()

    def _close_settings(self, save: bool) -> None:
        """Close settings panel, optionally saving changes."""
        import cc_dump.tui.settings_panel

        if save:
            for field_state in self._settings_fields:
                cc_dump.settings.save_setting(field_state.key, field_state.save_value)
            # Apply side effects for specific settings
            tmux = self._tmux_controller
            if tmux is not None:
                for field_state in self._settings_fields:
                    if field_state.key == "claude_command":
                        tmux.set_claude_command(field_state.save_value)
                    elif field_state.key == "auto_zoom_default":
                        tmux.auto_zoom = field_state.save_value

        # Remove panel widget
        for panel in self.screen.query(cc_dump.tui.settings_panel.SettingsPanel):
            panel.remove()
        self._settings_panel_open = False
        self._settings_fields = []
        self._update_footer_state()

    def _handle_settings_key(self, event) -> None:
        """Handle key events in SETTINGS mode."""
        key = event.key
        fields = self._settings_fields
        idx = self._settings_active_field

        # Navigation between fields
        if key == "tab":
            self._settings_active_field = (idx + 1) % len(fields)
            self._update_settings_panel_display()
            return
        if key == "shift+tab":
            self._settings_active_field = (idx - 1) % len(fields)
            self._update_settings_panel_display()
            return

        # Save and close
        if key == "enter":
            self._close_settings(save=True)
            self.notify("Settings saved")
            return

        # Cancel and close
        if key == "escape":
            self._close_settings(save=False)
            return

        # Delegate to the active field's handle_key
        fields[idx].handle_key(key, event.character)
        self._update_settings_panel_display()

    def _update_settings_panel_display(self) -> None:
        """Push current editing state to the settings panel widget."""
        import cc_dump.tui.settings_panel

        panels = self.screen.query(cc_dump.tui.settings_panel.SettingsPanel)
        if panels:
            panels.first().update_display(
                self._settings_fields, self._settings_active_field
            )

    # Navigation
    def action_toggle_follow(self):
        _actions.toggle_follow(self)

    def action_go_top(self):
        _actions.go_top(self)

    def action_go_bottom(self):
        _actions.go_bottom(self)

    def action_scroll_down_line(self):
        _actions.scroll_down_line(self)

    def action_scroll_up_line(self):
        _actions.scroll_up_line(self)

    def action_scroll_left_col(self):
        _actions.scroll_left_col(self)

    def action_scroll_right_col(self):
        _actions.scroll_right_col(self)

    def action_page_down(self):
        _actions.page_down(self)

    def action_page_up(self):
        _actions.page_up(self)

    def action_half_page_down(self):
        _actions.half_page_down(self)

    def action_half_page_up(self):
        _actions.half_page_up(self)

    def _refresh_economics(self):
        _actions.refresh_economics(self)

    def _refresh_timeline(self):
        _actions.refresh_timeline(self)

    def _refresh_session(self):
        _actions.refresh_session(self)

    # Search
    def _start_search(self):
        _search.start_search(self)

    def _handle_search_editing_key(self, event):
        _search.handle_search_editing_key(self, event)

    def _handle_search_nav_special_keys(self, event) -> bool:
        return _search.handle_search_nav_special_keys(self, event)

    def _update_search_bar(self):
        _search.update_search_bar(self)

    # ─── Reactive watchers ─────────────────────────────────────────────

    def _on_vis_state_changed(self):
        self._rerender_if_mounted()

    def watch__is_visible(self, value):
        self._on_vis_state_changed()

    def watch__is_full(self, value):
        self._on_vis_state_changed()

    def watch__is_expanded(self, value):
        self._on_vis_state_changed()

    def watch_active_panel(self, value):
        self._sync_panel_display(value)
        _actions.refresh_active_panel(self, value)
        self._update_footer_state()

    def _sync_panel_display(self, active: str):
        """// [LAW:one-source-of-truth] Panel visibility driven by PANEL_ORDER from registry."""
        for name in PANEL_ORDER:
            widget = self._get_panel(name)
            if widget is not None:
                widget.display = (name == active)

    def watch_show_logs(self, value):
        pass

    def watch_show_info(self, value):
        pass

    def watch_theme(self, theme_name: str) -> None:
        if not self.is_running:
            return
        cc_dump.tui.rendering.set_theme(self.current_theme)
        self._apply_markdown_theme()
        self._update_footer_state()
        conv = self._get_conv()
        if conv is not None:
            conv._block_strip_cache.clear()
            conv._line_cache.clear()
            conv.rerender(self.active_filters, force=True)

    def watch_app_focus(self, focused: bool) -> None:
        self.screen.set_class(not focused, "-app-unfocused")

    # ─── Key dispatch ──────────────────────────────────────────────────

    async def on_key(self, event) -> None:
        """// [LAW:single-enforcer] on_key is the sole key dispatcher."""
        mode = self._input_mode
        MODE_KEYMAP = cc_dump.tui.input_modes.MODE_KEYMAP
        InputMode = cc_dump.tui.input_modes.InputMode

        if mode == InputMode.SETTINGS:
            event.prevent_default()
            self._handle_settings_key(event)
            return
        elif mode == InputMode.NORMAL:
            if event.character == "/":
                event.prevent_default()
                self._start_search()
                return
        elif mode == InputMode.SEARCH_EDIT:
            event.prevent_default()
            self._handle_search_editing_key(event)
            return
        elif mode == InputMode.SEARCH_NAV:
            if self._handle_search_nav_special_keys(event):
                event.prevent_default()
                return

        keymap = MODE_KEYMAP.get(mode, {})
        action_name = keymap.get(event.key)
        if action_name:
            event.prevent_default()
            await self.run_action(action_name)
