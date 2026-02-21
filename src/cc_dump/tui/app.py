"""Main TUI application using Textual.

// [LAW:locality-or-seam] Thin coordinator — delegates to extracted modules:
//   category_config, action_handlers, search_controller, dump_export,
//   theme_controller, hot_reload_controller.
// [LAW:one-source-of-truth] View store (SnarfX) is the sole state for visibility.
//   active_filters is a Computed on the view store.
"""

import importlib
import os
import queue
import sys
import threading
import time
import traceback
from typing import Optional, TypedDict

import textual
from textual.app import App, ComposeResult, SystemCommand
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Header


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

# Extracted controller modules (module-object imports — safe for hot-reload)
from cc_dump.tui import action_handlers as _actions
from cc_dump.tui.panel_registry import PANEL_REGISTRY, PANEL_ORDER, PANEL_CSS_IDS
from cc_dump.tui import search_controller as _search
from cc_dump.tui import dump_export as _dump
from cc_dump.tui import theme_controller as _theme
from cc_dump.tui import hot_reload_controller as _hot_reload

# Additional module-level imports
import cc_dump.palette
import cc_dump.launch_config
import cc_dump.tmux_controller
import cc_dump.tui.error_indicator
import cc_dump.tui.settings_panel
import cc_dump.tui.launch_config_panel
import cc_dump.tui.side_channel_panel
import cc_dump.har_replayer
import cc_dump.sessions

from cc_dump.stderr_tee import get_tee as _get_tee
import snarfx
from snarfx import transaction
from snarfx import textual as stx


def _resolve_factory(dotted_path: str):
    """Resolve a dotted factory path like 'cc_dump.tui.widget_factory.create_stats_panel'.

    Uses importlib to resolve the module, then getattr for the function.
    This allows the registry to reference functions across modules.
    """
    parts = dotted_path.rsplit(".", 1)
    module_path, func_name = parts[0], parts[1]
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


class _ProxyEvent(Message, bubble=False):
    """Thread-safe bridge: drain thread → app message pump."""

    def __init__(self, event) -> None:
        self.event = event
        super().__init__()


class CcDumpApp(App):
    """TUI application for cc-dump."""

    CSS_PATH = "styles.css"

    # Panel visibility
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
        settings_store=None,
        view_store=None,
        store_context=None,
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
        self._settings_store = settings_store
        self._view_store = view_store
        self._store_context = store_context
        self._closing = False
        self._quit_requested_at: float | None = None
        self._markdown_theme_pushed = False

        self.sub_title = f"[{cc_dump.palette.PALETTE.info}]session: {session_name}[/]"

        self._replay_complete = threading.Event()
        if not replay_data:
            self._replay_complete.set()

        self._app_state: AppState = {"current_turn_usage": {}}

        self._search_state = cc_dump.tui.search.SearchState()

        # Buffered error log — dumped to stderr after TUI exits
        self._error_log: list[str] = []

        self._conv_id = "conversation-view"
        self._search_bar_id = "search-bar"
        # [LAW:one-source-of-truth] Panel IDs derived from registry
        self._panel_ids = dict(PANEL_CSS_IDS)
        self._logs_id = "logs-panel"
        self._info_id = "info-panel"

    # ─── Derived state ─────────────────────────────────────────────────

    # [LAW:one-source-of-truth] active_panel from view store, not Textual reactive
    @property
    def active_panel(self):
        return self._view_store.get("panel:active")

    @active_panel.setter
    def active_panel(self, value):
        self._view_store.set("panel:active", value)

    @property
    def _input_mode(self):
        """// [LAW:one-source-of-truth] InputMode derived from search state only.

        Panel modes eliminated — Textual's focus-based Key event bubbling
        handles panel key dispatch naturally. Panels with focused widgets
        consume keys via their own on_key; unfocused panels let keys reach app.
        """
        InputMode = cc_dump.tui.input_modes.InputMode
        SearchPhase = cc_dump.tui.search.SearchPhase
        phase = self._search_state.phase
        if phase == SearchPhase.EDITING:
            return InputMode.SEARCH_EDIT
        if phase == SearchPhase.NAVIGATING:
            return InputMode.SEARCH_NAV
        return InputMode.NORMAL

    @property
    def active_filters(self):
        """// [LAW:one-source-of-truth] Reads from view store Computed."""
        return self._view_store.active_filters.get()

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

        conv = cc_dump.tui.widget_factory.create_conversation_view(view_store=self._view_store)
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
        saved = self._settings_store.get("theme") if self._settings_store else None
        if saved and saved in self.available_themes:
            self.theme = saved
        cc_dump.tui.rendering.set_theme(self.current_theme)
        self._apply_markdown_theme()

        # Connect stderr tee to LogsPanel (flushes buffered pre-TUI messages)
        # stderr_tee is a stable boundary — safe to use `from` import
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

        # Hot-reload file watcher (requires watchfiles dev dep)
        self.run_worker(self._start_file_watcher)

        # Set initial panel visibility — cycle panels via active_panel
        self._sync_panel_display(self.active_panel)
        logs = self._get_logs()
        if logs is not None:
            logs.display = self.show_logs
        info = self._get_info()
        if info is not None:
            info.display = self.show_info
            info.update_info(self._build_server_info())

        # Wire snarfx auto-marshal now that call_from_thread is available
        snarfx.set_scheduler(self.call_from_thread)

        # React to tmux pane exit — sync store when Claude dies
        if self._tmux_controller is not None:
            stx.reaction(self,
                lambda: self._tmux_controller.pane_alive.get(),
                lambda _: self._sync_tmux_to_store(),
            )

        # Seed external state into view store for reactive footer
        self._sync_tmux_to_store()
        self._view_store.set("active_launch_config_name", cc_dump.launch_config.load_active_name())
        # Footer hydration — reactions are now active
        footer = self._get_footer()
        if footer:
            footer.update_display(self._view_store.footer_state.get())

        if self._replay_data:
            self._process_replay_data()

    def action_quit(self) -> None:
        now = time.monotonic()
        if self._quit_requested_at is not None and (now - self._quit_requested_at) < 1.0:
            self.exit()
            return
        self._quit_requested_at = now
        self.notify("Press Ctrl+C again to quit", timeout=1)

    def on_unmount(self):
        # Disconnect stderr tee before teardown
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
        # Get normal Python traceback (not Textual's verbose one)
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))

        # Buffer for post-exit dump
        self._error_log.append(f"EXCEPTION: {error}")
        self._error_log.append(tb)

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
        self._view_store.exception_items.append(exc_item)

        # DON'T call super() - keep running, hot reload will fix it

    # ─── Helpers ───────────────────────────────────────────────────────

    def _app_log(self, level: str, message: str):
        if level == "ERROR":
            self._error_log.append(f"[{level}] {message}")
        if self.is_running:
            logs = self._get_logs()
            if logs is not None:
                logs.app_log(level, message)

    def _sync_tmux_to_store(self):
        """Mirror tmux controller state to view store for reactive footer updates."""
        tmux = self._tmux_controller
        _TMUX_ACTIVE = {cc_dump.tmux_controller.TmuxState.READY, cc_dump.tmux_controller.TmuxState.CLAUDE_RUNNING}
        self._view_store.update({
            "tmux:available": tmux is not None and tmux.state in _TMUX_ACTIVE,
            "tmux:auto_zoom": tmux.auto_zoom if tmux is not None else False,
            "tmux:zoomed": tmux._is_zoomed if tmux is not None else False,
        })

    def _build_server_info(self) -> dict:
        """// [LAW:one-source-of-truth] All server info derived from constructor params."""
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

        if stx.is_safe(self):
            conv = self._get_conv()
            if conv is not None:
                conv.rerender(self.active_filters)

    # ─── Event pipeline ────────────────────────────────────────────────

    def _process_replay_data(self):
        if not self._replay_data:
            return

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
        """Bridge thread: queue.get → post_message into Textual's message pump.

        Uses post_message (thread-safe, non-blocking) instead of call_from_thread
        so events flow through the normal message pump and don't interfere with
        _wait_for_screen settling in pilot tests.
        """
        self._replay_complete.wait()
        while not self._closing:
            try:
                event = self._event_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            except Exception as e:
                if self._closing:
                    break
                print(f"Event queue error: {e}", file=sys.__stderr__)
                continue

            self.post_message(_ProxyEvent(event))

    def on__proxy_event(self, message: _ProxyEvent):
        self._handle_event(message.event)

    def _handle_event(self, event):
        try:
            self._handle_event_inner(event)
        except Exception as e:
            tb = traceback.format_exc()
            self._error_log.append(f"CRASH in _handle_event: {e}")
            self._error_log.append(tb)
            self._app_log("ERROR", f"Uncaught exception handling event: {e}")
            for line in tb.split("\n"):
                if line:
                    self._app_log("ERROR", f"  {line}")

    def _handle_event_inner(self, event):

        if not stx.is_safe(self):
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
    async def _start_file_watcher(self):
        await _hot_reload.start_file_watcher(self)

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
        config = cc_dump.launch_config.get_active_config()
        session_id = self._session_id if config.auto_resume else ""
        command = cc_dump.launch_config.build_full_command(config, session_id)
        tmux.set_claude_command(config.claude_command)
        result = tmux.launch_claude(command=command)
        self._app_log("INFO", "launch_claude: {}".format(result))
        if result.success:
            self.notify("{}: {}".format(result.action.value, result.detail))
            self._sync_tmux_to_store()
        else:
            self.notify("Launch failed: {}".format(result.detail), severity="error")

    def action_toggle_tmux_zoom(self):
        tmux = self._tmux_controller
        if tmux is None:
            self.notify("Tmux not available", severity="warning")
            return
        tmux.toggle_zoom()
        self._sync_tmux_to_store()

    def action_toggle_auto_zoom(self):
        tmux = self._tmux_controller
        if tmux is None:
            self.notify("Tmux not available", severity="warning")
            return
        tmux.toggle_auto_zoom()
        label = "on" if tmux.auto_zoom else "off"
        self.notify("Auto-zoom: {}".format(label))
        self._sync_tmux_to_store()

    # Settings
    def action_toggle_settings(self):
        _actions.toggle_settings(self)

    def _open_settings(self):
        """Open settings panel, populating from settings store."""
        initial_values = {}
        for field_def in cc_dump.tui.settings_panel.SETTINGS_FIELDS:
            val = self._settings_store.get(field_def.key) if self._settings_store else None
            initial_values[field_def.key] = val if val is not None else field_def.default

        self._view_store.set("panel:settings", True)
        panel = cc_dump.tui.settings_panel.create_settings_panel(initial_values)
        self.screen.mount(panel)

    def _close_settings(self) -> None:
        """Close settings panel and restore focus to conversation."""
        for panel in self.screen.query(cc_dump.tui.settings_panel.SettingsPanel):
            panel.remove()
        self._view_store.set("panel:settings", False)
        conv = self._get_conv()
        if conv is not None:
            conv.focus()

    def on_settings_panel_saved(self, msg) -> None:
        """Handle SettingsPanel.Saved — update store (reactions handle persistence + side effects)."""
        if self._settings_store is not None:
            self._settings_store.update(msg.values)
        self._close_settings()
        self.notify("Settings saved")

    def on_settings_panel_cancelled(self, msg) -> None:
        """Handle SettingsPanel.Cancelled — close without saving."""
        self._close_settings()

    # Launch configs
    def action_toggle_launch_config(self):
        _actions.toggle_launch_config(self)

    def _open_launch_config(self):
        """Open launch config panel, populating state from saved configs."""
        configs = cc_dump.launch_config.load_configs()
        active_name = cc_dump.launch_config.load_active_name()

        self._view_store.set("panel:launch_config", True)
        panel = cc_dump.tui.launch_config_panel.create_launch_config_panel(
            configs, active_name
        )
        self.screen.mount(panel)

    def _close_launch_config(self) -> None:
        """Close launch config panel and restore focus to conversation."""
        for panel in self.screen.query(cc_dump.tui.launch_config_panel.LaunchConfigPanel):
            panel.remove()
        self._view_store.set("panel:launch_config", False)
        conv = self._get_conv()
        if conv is not None:
            conv.focus()

    def _launch_with_config(self, config) -> None:
        """Build args from config + session_id, launch via tmux."""
        tmux = self._tmux_controller
        if tmux is None:
            self.notify("Tmux not available", severity="warning")
            return

        session_id = self._session_id if config.auto_resume else ""
        command = cc_dump.launch_config.build_full_command(config, session_id)
        tmux.set_claude_command(config.claude_command)
        result = tmux.launch_claude(command=command)
        self._app_log("INFO", "launch_with_config: {}".format(result))
        if result.success:
            self.notify("{}: {}".format(result.action.value, result.detail))
        else:
            self.notify("Launch failed: {}".format(result.detail), severity="error")
        self._sync_tmux_to_store()

    def on_launch_config_panel_saved(self, msg) -> None:
        """Handle LaunchConfigPanel.Saved — persist configs."""
        cc_dump.launch_config.save_configs(msg.configs)
        cc_dump.launch_config.save_active_name(msg.active_name)
        self._close_launch_config()
        self.notify("Launch configs saved")

    def on_launch_config_panel_cancelled(self, msg) -> None:
        """Handle LaunchConfigPanel.Cancelled — close without saving."""
        self._close_launch_config()

    def on_launch_config_panel_quick_launch(self, msg) -> None:
        """Handle LaunchConfigPanel.QuickLaunch — save, close, launch."""
        cc_dump.launch_config.save_configs(msg.configs)
        cc_dump.launch_config.save_active_name(msg.active_name)
        self._close_launch_config()
        self._launch_with_config(msg.config)

    def on_launch_config_panel_activated(self, msg) -> None:
        """Handle LaunchConfigPanel.Activated — save active name, notify."""
        cc_dump.launch_config.save_configs(msg.configs)
        cc_dump.launch_config.save_active_name(msg.name)
        self._view_store.set("active_launch_config_name", msg.name)
        self.notify("Active: {}".format(msg.name))

    # Side channel
    def action_toggle_side_channel(self):
        _actions.toggle_side_channel(self)

    def _open_side_channel(self):
        """Open side-channel AI panel."""
        self._view_store.set("panel:side_channel", True)
        panel = cc_dump.tui.side_channel_panel.create_side_channel_panel()
        self.screen.mount(panel)
        # Reset sc state — reaction pushes to panel
        with transaction():
            self._view_store.set("sc:loading", False)
            self._view_store.set("sc:result_text", "")
            self._view_store.set("sc:result_source", "")
            self._view_store.set("sc:result_elapsed_ms", 0)
        # Initial hydration — reaction may not fire if values unchanged from defaults
        panel.update_display(self._view_store.sc_panel_state.get())

    def _close_side_channel(self):
        """Close side-channel AI panel and restore focus to conversation."""
        for panel in self.screen.query(cc_dump.tui.side_channel_panel.SideChannelPanel):
            panel.remove()
        self._view_store.set("panel:side_channel", False)
        conv = self._get_conv()
        if conv is not None:
            conv.focus()

    def _side_channel_summarize(self):
        """Request AI summary of recent messages. Runs in worker thread."""
        if self._view_store.get("sc:loading") or self._data_dispatcher is None:
            return

        messages = self._collect_recent_messages(10)
        if not messages:
            self._view_store.set("sc:result_text", "No messages to summarize.")
            self._view_store.set("sc:result_source", "fallback")
            return

        self._view_store.set("sc:loading", True)

        dispatcher = self._data_dispatcher

        def _do_summarize():
            result = dispatcher.summarize_messages(messages)
            self.call_from_thread(self._on_side_channel_result, result)

        self.run_worker(_do_summarize, thread=True, exclusive=False)

    def _on_side_channel_result(self, result):
        """Callback from worker thread with AI result."""
        with transaction():
            self._view_store.set("sc:loading", False)
            self._view_store.set("sc:result_text", result.text)
            self._view_store.set("sc:result_source", result.source)
            self._view_store.set("sc:result_elapsed_ms", result.elapsed_ms)

    def _collect_recent_messages(self, count: int) -> list[dict]:
        """Extract last N messages from captured API traffic."""
        return self._app_state.get("recent_messages", [])[-count:]

    def _side_channel_toggle_enabled(self):
        """Toggle side-channel AI on/off via settings store."""
        if self._settings_store is None:
            return
        current = self._settings_store.get("side_channel_enabled")
        self._settings_store.set("side_channel_enabled", not current)
        # sc_panel_state Computed reads settings_store → reaction fires automatically

    def action_sc_summarize(self) -> None:
        """Action target for side-channel Summarize chip."""
        self._side_channel_summarize()

    def action_sc_toggle(self) -> None:
        """Action target for side-channel Toggle chip."""
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
        gen = self._view_store.get("theme_generation")
        self._view_store.set("theme_generation", gen + 1)
        conv = self._get_conv()
        if conv is not None:
            conv._block_strip_cache.clear()
            conv._line_cache.clear()
            conv.rerender(self.active_filters, force=True)

    def watch_app_focus(self, focused: bool) -> None:
        self.screen.set_class(not focused, "-app-unfocused")

    # ─── Key dispatch ──────────────────────────────────────────────────

    def _close_topmost_panel(self) -> bool:
        """Close the topmost open panel. Returns True if a panel was closed.

        Checks store booleans in priority order (side_channel → launch_config → settings).
        """
        if self._view_store.get("panel:side_channel"):
            self._close_side_channel()
            return True
        if self._view_store.get("panel:launch_config"):
            self._close_launch_config()
            return True
        if self._view_store.get("panel:settings"):
            self._close_settings()
            return True
        return False

    async def on_key(self, event) -> None:
        """// [LAW:single-enforcer] on_key is the sole key dispatcher.

        Search modes consume keys first (including Escape to exit search).
        Then Escape closes topmost panel. Panel-specific keys are handled by
        each panel's own on_key via Textual's event bubbling — when focus is
        within a panel, the panel sees the Key event first.
        """
        mode = self._input_mode
        MODE_KEYMAP = cc_dump.tui.input_modes.MODE_KEYMAP
        InputMode = cc_dump.tui.input_modes.InputMode

        # Search modes consume keys first (Escape exits search before closing panels)
        if mode == InputMode.SEARCH_EDIT:
            event.prevent_default()
            self._handle_search_editing_key(event)
            return
        if mode == InputMode.SEARCH_NAV:
            if self._handle_search_nav_special_keys(event):
                event.prevent_default()
                return

        # Generic Escape: close topmost panel (when focus is outside the panel)
        if event.key == "escape" and self._close_topmost_panel():
            event.prevent_default()
            return

        if mode == InputMode.NORMAL:
            if event.character == "/":
                event.prevent_default()
                self._start_search()
                return

        keymap = MODE_KEYMAP.get(mode, MODE_KEYMAP[InputMode.NORMAL])
        action_name = keymap.get(event.key)
        if action_name:
            event.prevent_default()
            await self.run_action(action_name)
