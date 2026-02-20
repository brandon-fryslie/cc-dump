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
        side_channel_manager=None,
        data_dispatcher=None,
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
        self._side_channel_manager = side_channel_manager
        self._data_dispatcher = data_dispatcher
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

        # Side channel panel state
        self._side_channel_panel_open: bool = False
        self._side_channel_loading: bool = False
        self._side_channel_result_text: str = ""
        self._side_channel_result_source: str = ""
        self._side_channel_result_elapsed_ms: int = 0

        # Launch config panel state
        self._launch_config_panel_open: bool = False
        self._launch_configs: list = []          # list[LaunchConfig]
        self._launch_config_selected: int = 0    # selected index in list
        self._launch_config_fields: list = []    # list[FieldState] for selected config
        self._launch_config_active_field: int = 0

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
        if self._side_channel_panel_open:
            return InputMode.SIDE_CHANNEL
        if self._launch_config_panel_open:
            return InputMode.LAUNCH_CONFIG
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
                import cc_dump.launch_config
                state = {
                    **self.active_filters,
                    "active_panel": self.active_panel,
                    "follow_state": conv._follow_state if conv is not None else cc_dump.tui.widget_factory.FollowState.ACTIVE,
                    "active_filterset": self._active_filterset_slot,
                    "tmux_available": tmux is not None and tmux.state in _TMUX_ACTIVE,
                    "tmux_auto_zoom": tmux.auto_zoom if tmux is not None else False,
                    "tmux_zoomed": tmux._is_zoomed if tmux is not None else False,
                    "active_launch_config_name": cc_dump.launch_config.load_active_name(),
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

        import cc_dump.har_replayer

        self._app_log("INFO", f"Processing {len(self._replay_data)} request/response pairs")

        for (
            req_headers,
            req_body,
            resp_status,
            resp_headers,
            complete_message,
        ) in self._replay_data:
            try:
                # // [LAW:one-source-of-truth] Replay uses the same event pipeline as live.
                events = cc_dump.har_replayer.convert_to_events(
                    req_headers, req_body, resp_status, resp_headers, complete_message
                )
                for event in events:
                    self._handle_event(event)
            except Exception as e:
                self._app_log("ERROR", f"Error processing replay pair: {e}")

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

        # // [LAW:one-source-of-truth] Session ID comes from formatting state,
        # not from blocks or app_state side-channels.
        current_session = self._state.get("current_session", "")
        if current_session and current_session != self._session_id:
            self._app_log("INFO", f"Session detected: {current_session}")
            self._session_id = current_session
            self.post_message(NewSession(current_session))
            self.notify(f"New session: {current_session[:8]}...")
            info = self._get_info()
            if info is not None:
                info.update_info(self._build_server_info())

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
        import cc_dump.launch_config
        config = cc_dump.launch_config.get_active_config()
        session_id = self._session_id if config.auto_resume else ""
        command = cc_dump.launch_config.build_full_command(config, tmux.claude_command, session_id)
        result = tmux.launch_claude(command=command)
        self._app_log("INFO", "launch_claude: {}".format(result))
        if result.success:
            self.notify("{}: {}".format(result.action.value, result.detail))
            self._update_footer_state()
        else:
            self.notify("Launch failed: {}".format(result.detail), severity="error")

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
            for field_state in self._settings_fields:
                if field_state.key == "side_channel_enabled" and self._side_channel_manager is not None:
                    self._side_channel_manager.enabled = field_state.save_value
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

    # Launch configs
    def action_toggle_launch_config(self):
        _actions.toggle_launch_config(self)

    def _open_launch_config(self):
        """Open launch config panel, populating state from saved configs."""
        import cc_dump.launch_config
        import cc_dump.tui.launch_config_panel

        self._launch_configs = cc_dump.launch_config.load_configs()
        self._launch_config_selected = 0
        self._launch_config_fields = cc_dump.tui.launch_config_panel.make_field_states(
            self._launch_configs[0]
        )
        self._launch_config_active_field = 0
        self._launch_config_panel_open = True

        panel = cc_dump.tui.launch_config_panel.create_launch_config_panel()
        self.screen.mount(panel)
        self._update_launch_config_panel_display()
        self._update_footer_state()

    def _close_launch_config(self, save: bool) -> None:
        """Close launch config panel, optionally saving changes."""
        import cc_dump.launch_config
        import cc_dump.tui.launch_config_panel

        if save:
            # Apply field edits to the selected config before saving
            selected = self._launch_config_selected
            if selected < len(self._launch_configs):
                cc_dump.tui.launch_config_panel.apply_fields_to_config(
                    self._launch_configs[selected], self._launch_config_fields
                )
            cc_dump.launch_config.save_configs(self._launch_configs)

        # Remove panel widget
        for panel in self.screen.query(cc_dump.tui.launch_config_panel.LaunchConfigPanel):
            panel.remove()
        self._launch_config_panel_open = False
        self._launch_configs = []
        self._launch_config_fields = []
        self._update_footer_state()

    def _select_launch_config(self, idx: int) -> None:
        """Switch selected config, saving edits to previous and loading new fields."""
        import cc_dump.tui.launch_config_panel

        # Save edits to current selection
        old_idx = self._launch_config_selected
        if old_idx < len(self._launch_configs):
            cc_dump.tui.launch_config_panel.apply_fields_to_config(
                self._launch_configs[old_idx], self._launch_config_fields
            )

        # Load fields for new selection
        self._launch_config_selected = idx
        self._launch_config_fields = cc_dump.tui.launch_config_panel.make_field_states(
            self._launch_configs[idx]
        )
        self._launch_config_active_field = 0

    def _launch_with_config(self, config) -> None:
        """Build args from config + session_id, launch via tmux."""
        import cc_dump.launch_config

        tmux = self._tmux_controller
        if tmux is None:
            self.notify("Tmux not available", severity="warning")
            return

        session_id = self._session_id if config.auto_resume else ""
        command = cc_dump.launch_config.build_full_command(config, tmux.claude_command, session_id)
        result = tmux.launch_claude(command=command)
        self._app_log("INFO", "launch_with_config: {}".format(result))
        if result.success:
            self.notify("{}: {}".format(result.action.value, result.detail))
        else:
            self.notify("Launch failed: {}".format(result.detail), severity="error")
        self._update_footer_state()

    def _handle_launch_config_key(self, event) -> None:
        """Handle key events in LAUNCH_CONFIG mode."""
        import cc_dump.launch_config
        import cc_dump.tui.launch_config_panel

        key = event.key
        configs = self._launch_configs
        idx = self._launch_config_selected

        # Quick-launch by number (1-9)
        if key in "123456789":
            num = int(key) - 1
            if num < len(configs):
                # Save current edits, then launch
                cc_dump.tui.launch_config_panel.apply_fields_to_config(
                    configs[idx], self._launch_config_fields
                )
                cc_dump.launch_config.save_configs(configs)
                cc_dump.launch_config.save_active_name(configs[num].name)
                self._close_launch_config(save=False)  # already saved
                self._launch_with_config(configs[num])
            return

        # Navigate config list
        if key in ("j", "down"):
            new_idx = min(idx + 1, len(configs) - 1)
            if new_idx != idx:
                self._select_launch_config(new_idx)
                self._update_launch_config_panel_display()
            return
        if key in ("k", "up"):
            new_idx = max(idx - 1, 0)
            if new_idx != idx:
                self._select_launch_config(new_idx)
                self._update_launch_config_panel_display()
            return

        # Cycle field
        if key == "tab":
            fields = self._launch_config_fields
            self._launch_config_active_field = (self._launch_config_active_field + 1) % len(fields)
            self._update_launch_config_panel_display()
            return
        if key == "shift+tab":
            fields = self._launch_config_fields
            self._launch_config_active_field = (self._launch_config_active_field - 1) % len(fields)
            self._update_launch_config_panel_display()
            return

        # Activate selected config
        if key == "a":
            cc_dump.tui.launch_config_panel.apply_fields_to_config(
                configs[idx], self._launch_config_fields
            )
            cc_dump.launch_config.save_active_name(configs[idx].name)
            cc_dump.launch_config.save_configs(configs)
            self.notify("Active: {}".format(configs[idx].name))
            self._update_launch_config_panel_display()
            self._update_footer_state()
            return

        # New config
        if key == "n":
            cc_dump.tui.launch_config_panel.apply_fields_to_config(
                configs[idx], self._launch_config_fields
            )
            new_config = cc_dump.launch_config.LaunchConfig(
                name="config-{}".format(len(configs) + 1)
            )
            configs.append(new_config)
            self._select_launch_config(len(configs) - 1)
            self._update_launch_config_panel_display()
            return

        # Delete selected (prevent deleting last)
        if key == "d":
            if len(configs) <= 1:
                self.notify("Cannot delete last config", severity="warning")
                return
            configs.pop(idx)
            new_idx = min(idx, len(configs) - 1)
            self._select_launch_config(new_idx)
            self._update_launch_config_panel_display()
            return

        # Save and close
        if key == "enter":
            self._close_launch_config(save=True)
            self.notify("Launch configs saved")
            return

        # Cancel and close
        if key == "escape":
            self._close_launch_config(save=False)
            return

        # Delegate to active field
        fields = self._launch_config_fields
        field_idx = self._launch_config_active_field
        fields[field_idx].handle_key(key, event.character)
        self._update_launch_config_panel_display()

    def _update_launch_config_panel_display(self) -> None:
        """Push current editing state to the launch config panel widget."""
        import cc_dump.launch_config
        import cc_dump.tui.launch_config_panel

        panels = self.screen.query(cc_dump.tui.launch_config_panel.LaunchConfigPanel)
        if panels:
            panels.first().update_display(
                self._launch_configs,
                self._launch_config_selected,
                self._launch_config_fields,
                self._launch_config_active_field,
                cc_dump.launch_config.load_active_name(),
            )

    # Side channel
    def action_toggle_side_channel(self):
        _actions.toggle_side_channel(self)

    def _open_side_channel(self):
        """Open side-channel AI panel."""
        import cc_dump.tui.side_channel_panel

        self._side_channel_panel_open = True
        self._side_channel_loading = False
        self._side_channel_result_text = ""
        self._side_channel_result_source = ""
        self._side_channel_result_elapsed_ms = 0

        panel = cc_dump.tui.side_channel_panel.create_side_channel_panel()
        self.screen.mount(panel)
        self._update_side_channel_panel_display()
        self._update_footer_state()

    def _close_side_channel(self):
        """Close side-channel AI panel."""
        import cc_dump.tui.side_channel_panel

        for panel in self.screen.query(cc_dump.tui.side_channel_panel.SideChannelPanel):
            panel.remove()
        self._side_channel_panel_open = False
        self._update_footer_state()

    def _update_side_channel_panel_display(self):
        """Push current state to the side-channel panel widget."""
        import cc_dump.tui.side_channel_panel

        panels = self.screen.query(cc_dump.tui.side_channel_panel.SideChannelPanel)
        if panels:
            state = cc_dump.tui.side_channel_panel.SideChannelPanelState(
                enabled=self._side_channel_manager.enabled if self._side_channel_manager else False,
                loading=self._side_channel_loading,
                result_text=self._side_channel_result_text,
                result_source=self._side_channel_result_source,
                result_elapsed_ms=self._side_channel_result_elapsed_ms,
            )
            panels.first().update_display(state)

    def _handle_side_channel_key(self, event) -> None:
        """Handle key events in SIDE_CHANNEL mode.

        Only Esc is handled here — button interactions use Textual's
        standard Button.Pressed event.
        """
        if event.key == "escape":
            self._close_side_channel()

    def _side_channel_summarize(self):
        """Request AI summary of recent messages. Runs in worker thread."""
        if self._side_channel_loading or self._data_dispatcher is None:
            return

        messages = self._collect_recent_messages(10)
        if not messages:
            self._side_channel_result_text = "No messages to summarize."
            self._side_channel_result_source = "fallback"
            self._update_side_channel_panel_display()
            return

        self._side_channel_loading = True
        self._update_side_channel_panel_display()

        dispatcher = self._data_dispatcher

        def _do_summarize():
            result = dispatcher.summarize_messages(messages)
            self.call_from_thread(self._on_side_channel_result, result)

        self.run_worker(_do_summarize, thread=True, exclusive=False)

    def _on_side_channel_result(self, result):
        """Callback from worker thread with AI result."""
        self._side_channel_loading = False
        self._side_channel_result_text = result.text
        self._side_channel_result_source = result.source
        self._side_channel_result_elapsed_ms = result.elapsed_ms
        self._update_side_channel_panel_display()

    def _collect_recent_messages(self, count: int) -> list[dict]:
        """Extract last N messages from captured API traffic."""
        return self._app_state.get("recent_messages", [])[-count:]

    def _side_channel_toggle_enabled(self):
        """Toggle side-channel AI on/off."""
        if self._side_channel_manager is None:
            return
        new_val = not self._side_channel_manager.enabled
        self._side_channel_manager.enabled = new_val
        cc_dump.settings.save_setting("side_channel_enabled", new_val)
        self._update_side_channel_panel_display()

    def on_button_pressed(self, event) -> None:
        """Handle button presses from side-channel panel."""
        button_id = event.button.id
        if button_id == "sc-summarize":
            self._side_channel_summarize()
        elif button_id == "sc-toggle":
            self._side_channel_toggle_enabled()

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

        if mode == InputMode.SIDE_CHANNEL:
            if event.key == "escape":
                event.prevent_default()
                self._close_side_channel()
            return
        elif mode == InputMode.LAUNCH_CONFIG:
            event.prevent_default()
            self._handle_launch_config_key(event)
            return
        elif mode == InputMode.SETTINGS:
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
