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
import tracemalloc
import traceback
from functools import lru_cache
from typing import Callable, Optional, TypedDict, cast

import textual
import textual.filter as _textual_filter
import textual.widgets._tabs as _textual_tabs
from textual.app import App, ComposeResult, SystemCommand
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Header, TabbedContent, TabPane
from rich.style import Style
from rich.text import Text


# Module-level imports for hot-reload (never use `from` for these)
import cc_dump.core.formatting
import cc_dump.io.settings
import cc_dump.tui.rendering
import cc_dump.tui.widget_factory
import cc_dump.tui.event_handlers
import cc_dump.tui.search
import cc_dump.tui.input_modes
import cc_dump.tui.info_panel
import cc_dump.tui.custom_footer
import cc_dump.tui.session_panel
import cc_dump.tui.workbench_results_view

# Extracted controller modules (module-object imports — safe for hot-reload)
from cc_dump.tui import action_handlers as _actions
import cc_dump.tui.category_config
import cc_dump.tui.panel_registry
from cc_dump.tui import search_controller as _search
from cc_dump.tui import dump_export as _dump
from cc_dump.tui import theme_controller as _theme
from cc_dump.tui import hot_reload_controller as _hot_reload

# Additional module-level imports
import cc_dump.core.palette
import cc_dump.app.launch_config
import cc_dump.app.tmux_controller
import cc_dump.tui.error_indicator
import cc_dump.tui.settings_panel
import cc_dump.tui.launch_config_panel
import cc_dump.tui.side_channel_panel
import cc_dump.tui.view_store_bridge
import cc_dump.pipeline.har_replayer
import cc_dump.io.sessions
import cc_dump.app.memory_stats
import cc_dump.pipeline.event_types
import cc_dump.app.view_store
import cc_dump.app.session_store
import cc_dump.ai.conversation_qa
import cc_dump.ai.side_channel_marker

from cc_dump.io.stderr_tee import get_tee as _get_tee
import cc_dump.app.domain_store
import snarfx
from snarfx import transaction
from snarfx import textual as stx


def _patch_textual_monochrome_style() -> None:
    """Patch Textual monochrome filter to tolerate None segment styles.

    // [LAW:single-enforcer] Third-party compatibility patch applied once at app boundary.
    """
    if getattr(_textual_filter, "_cc_dump_monochrome_patch", False):
        return

    original = cast(Callable[[Style], Style], _textual_filter.monochrome_style)

    @lru_cache(1024)
    def _safe_monochrome_style(style: Style | None) -> Style:
        return original(style or Style.null())

    setattr(_textual_filter, "monochrome_style", _safe_monochrome_style)
    setattr(_textual_filter, "_cc_dump_monochrome_patch", True)


def _patch_textual_underline_endcaps() -> None:
    """Patch Textual tab underline rendering with explicit corner endcaps.

    // [LAW:single-enforcer] Third-party compatibility patch applied once at app boundary.
    """
    if getattr(_textual_tabs, "_cc_dump_underline_caps_patch", False):
        return

    _LINE = "─"
    _START_CAP = "╶"
    _END_CAP = "╴"

    def _flat_render(self):
        # [LAW:dataflow-not-control-flow] Always render the same stages:
        # base bar -> highlighted segment with endcap policy by span position.
        bar_style = self.get_component_rich_style("underline--bar")
        highlight_style = Style.from_color(bar_style.color)
        background_style = Style.from_color(bar_style.bgcolor)
        width = max(0, int(self.size.width))
        if width <= 0:
            return Text("", end="")

        start_f, end_f = self._highlight_range
        start = max(0, min(width, int(round(start_f))))
        # [LAW:dataflow-not-control-flow] Span widening is encoded in values;
        # render path is unchanged.
        end = max(start, min(width, int(round(end_f)) + 1))

        if end <= start:
            return Text(_LINE * width, style=background_style, end="")

        segment = end - start
        highlight_chars = [_LINE] * segment
        highlight_chars[0] = _START_CAP
        highlight_chars[-1] = _END_CAP if end >= width else _LINE

        output = Text("", end="")
        if start > 0:
            output.append(_LINE * start, style=background_style)
        output.append("".join(highlight_chars), style=highlight_style)
        if end < width:
            output.append(_LINE * (width - end), style=background_style)
        return output

    setattr(_textual_tabs.Underline, "render", _flat_render)
    setattr(_textual_tabs, "_cc_dump_underline_caps_patch", True)


_patch_textual_monochrome_style()
_patch_textual_underline_endcaps()


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
    current_turn_usage_by_request: dict[str, TurnUsage]
    pending_request_headers: dict[str, dict[str, str]]
    recent_messages: list[dict]
    last_message_time: float
    last_message_time_by_session: dict[str, float]
    stream_registry: object


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
        resume_ui_state: Optional[dict] = None,
        tmux_controller=None,
        side_channel_manager=None,
        data_dispatcher=None,
        settings_store=None,
        session_store=None,
        view_store=None,
        domain_store=None,
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
        self._resume_ui_state = resume_ui_state if isinstance(resume_ui_state, dict) else None
        self._tmux_controller = tmux_controller
        self._side_channel_manager = side_channel_manager
        self._data_dispatcher = data_dispatcher
        self._settings_store = settings_store
        self._session_store = (
            session_store
            if session_store is not None
            else cc_dump.app.session_store.create()
        )
        self._view_store = view_store
        self._domain_store = domain_store if domain_store is not None else cc_dump.app.domain_store.DomainStore()
        self._store_context = store_context
        self._closing = False
        self._quit_requested_at: float | None = None
        self._markdown_theme_pushed = False
        self._memory_snapshot_enabled = (
            str(os.environ.get("CC_DUMP_MEMORY_SNAPSHOT", "0")).strip().lower()
            in {"1", "true", "yes", "on"}
        )
        if self._memory_snapshot_enabled and not tracemalloc.is_tracing():
            tracemalloc.start(25)

        self.sub_title = f"[{cc_dump.core.palette.PALETTE.info}]session: {session_name}[/]"

        self._replay_complete = threading.Event()
        if not replay_data:
            self._replay_complete.set()

        self._app_state: AppState = {
            "current_turn_usage": {},
            "current_turn_usage_by_request": {},
            "pending_request_headers": {},
            "last_message_time_by_session": {},
        }

        self._search_state = cc_dump.tui.search.SearchState(self._view_store)

        # Buffered error log — dumped to stderr after TUI exits
        self._error_log: list[str] = []

        self._conv_id = "conversation-view"
        self._conv_tabs_id = "conversation-tabs"
        self._conv_tab_main_id = "conversation-tab-main"
        self._workbench_tab_id = "conversation-tab-workbench"
        self._workbench_view_id = "workbench-results-view"
        self._workbench_session_key = "workbench-session"
        self._search_bar_id = "search-bar"
        # // [LAW:one-source-of-truth] Default session key and routing shape are owned by session_store.
        self._default_session_key = cc_dump.app.session_store.DEFAULT_SESSION_KEY
        cc_dump.app.session_store.ensure_routing_state(
            self._session_store, self._default_session_key
        )
        self._session_domain_stores: dict[str, cc_dump.app.domain_store.DomainStore] = {
            self._default_session_key: self._domain_store
        }
        self._session_conv_ids: dict[str, str] = {
            self._default_session_key: self._conv_id
        }
        self._session_tab_ids: dict[str, str] = {
            self._default_session_key: self._conv_tab_main_id
        }
        # [LAW:one-source-of-truth] Panel IDs derived from registry
        self._panel_ids = dict(cc_dump.tui.panel_registry.PANEL_CSS_IDS)
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

    # Back-compat aliases for tests and legacy callsites.
    @property
    def _active_session_key(self) -> str:
        return cc_dump.app.session_store.get_active_key(
            self._session_store, self._default_session_key
        )

    @_active_session_key.setter
    def _active_session_key(self, session_key: str) -> None:
        cc_dump.app.session_store.set_active_key(
            self._session_store, session_key, self._default_session_key
        )

    @property
    def _last_primary_session_key(self) -> str:
        return cc_dump.app.session_store.get_last_primary_key(
            self._session_store, self._default_session_key
        )

    @_last_primary_session_key.setter
    def _last_primary_session_key(self, session_key: str) -> None:
        cc_dump.app.session_store.set_last_primary_key(
            self._session_store, session_key, self._default_session_key
        )

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

    def _get_conv_tabs(self):
        return self._query_safe("#" + self._conv_tabs_id)

    def _get_sc_action_batch_id(self) -> str:
        value = self._view_store.get("sc:action_batch_id")
        return str(value or "")

    def _set_sc_action_batch_id(self, batch_id: str) -> None:
        self._view_store.set("sc:action_batch_id", str(batch_id or ""))

    def _get_sc_action_items(self) -> list[object]:
        items = self._view_store.get("sc:action_items")
        if isinstance(items, list):
            return list(items)
        if isinstance(items, tuple):
            return list(items)
        return []

    def _set_sc_action_items(self, items: list[object]) -> None:
        self._view_store.set("sc:action_items", list(items))

    def _reset_sc_action_review_state(self) -> None:
        self._set_sc_action_batch_id("")
        self._set_sc_action_items([])

    def _normalize_session_key(self, session_id: str) -> str:
        return cc_dump.app.session_store.normalize_session_key(
            session_id, self._default_session_key
        )

    def _is_side_channel_session_key(self, session_key: str) -> bool:
        return session_key == self._workbench_session_key or session_key.startswith("side-channel:")

    def _context_session_key(self, session_key: str) -> str:
        """Resolve canonical conversation context for derived session tabs.

        // [LAW:one-source-of-truth] Context/session linkage is normalized here.
        """
        key = self._normalize_session_key(session_key)
        if key == self._workbench_session_key:
            return self._normalize_session_key(self._last_primary_session_key)
        if self._is_side_channel_session_key(key):
            parts = key.split(":", 2)
            if len(parts) == 3 and parts[2]:
                return self._normalize_session_key(parts[2])
            return self._default_session_key
        return key

    def _active_context_session_key(self) -> str:
        """Return the active conversation context key, even on derived tabs."""
        return self._context_session_key(self._active_session_key_from_tabs())

    def _active_session_key_from_tabs(self) -> str:
        tabs = self._get_conv_tabs()
        if tabs is None:
            return self._active_session_key
        active_tab_id = str(getattr(tabs, "active", "") or "")
        for session_key, tab_id in self._session_tab_ids.items():
            if tab_id == active_tab_id:
                self._active_session_key = session_key
                if not self._is_side_channel_session_key(session_key):
                    self._last_primary_session_key = session_key
                break
        return self._active_session_key

    def _get_domain_store(self, session_key: str | None = None):
        key = session_key if session_key is not None else self._active_session_key_from_tabs()
        return self._session_domain_stores.get(key, self._domain_store)

    def _get_active_domain_store(self):
        return self._get_domain_store(self._active_session_key_from_tabs())

    def _iter_domain_stores(self):
        return tuple(self._session_domain_stores.values())

    def _session_tab_title(self, session_key: str) -> str:
        if session_key == self._default_session_key:
            return "Session"
        if session_key == self._workbench_session_key:
            return "Workbench Session"
        if self._is_side_channel_session_key(session_key):
            parts = session_key.split(":", 2)
            suffix = parts[2] if len(parts) > 2 else session_key
            return "SC " + suffix[:8]
        return session_key[:8]

    def _ensure_session_surface(self, session_key: str) -> None:
        """Ensure one DomainStore + TabPane + ConversationView exists for session key.

        // [LAW:one-source-of-truth] session_key owns DomainStore + ConversationView identity.
        // [LAW:locality-or-seam] Dynamic tab/session creation is isolated here.
        """
        key = self._normalize_session_key(session_key)
        if key in self._session_conv_ids and key in self._session_domain_stores:
            return

        tab_index = len(self._session_tab_ids)
        conv_id = f"{self._conv_id}-{tab_index}"
        tab_id = f"{self._conv_tab_main_id}-{tab_index}"
        domain_store = cc_dump.app.domain_store.DomainStore()
        conv = cc_dump.tui.widget_factory.create_conversation_view(
            view_store=self._view_store,
            domain_store=domain_store,
        )
        conv.id = conv_id

        self._session_domain_stores[key] = domain_store
        self._session_conv_ids[key] = conv_id
        self._session_tab_ids[key] = tab_id

        tabs = self._get_conv_tabs()
        if tabs is None:
            return

        pane = TabPane(self._session_tab_title(key), conv, id=tab_id)
        # [LAW:single-enforcer] Session-pane insertion order is centralized here:
        # every dynamic session is inserted before Workbench results so results stay rightmost.
        tabs.add_pane(pane, before=self._workbench_tab_id)

        # // [LAW:dataflow-not-control-flow] Default tab always exists; first real
        # session auto-focuses only when default has no data.
        default_store = self._session_domain_stores[self._default_session_key]
        if (
            self._active_session_key == self._default_session_key
            and key != self._default_session_key
            and not self._is_side_channel_session_key(key)
            and default_store.completed_count == 0
            and not default_store.get_active_stream_ids()
        ):
            tabs.active = tab_id

    def _extract_session_id_from_body(self, body: object) -> str:
        """Extract session_id from request body metadata.user_id."""
        if not isinstance(body, dict):
            return ""
        metadata = body.get("metadata", {})
        if not isinstance(metadata, dict):
            return ""
        user_id = metadata.get("user_id", "")
        if not isinstance(user_id, str) or not user_id:
            return ""
        parsed = cc_dump.core.formatting.parse_user_id(user_id)
        if not parsed:
            return ""
        session_id = parsed.get("session_id", "")
        return session_id if isinstance(session_id, str) else ""

    def _bind_request_session(self, request_id: str, session_key: str) -> None:
        if not request_id:
            return
        cc_dump.app.session_store.set_request_key(
            self._session_store,
            request_id,
            session_key,
            self._default_session_key,
        )

    def _session_key_for_request_id(self, request_id: str) -> str:
        key = cc_dump.app.session_store.get_request_keys(self._session_store).get(request_id)
        if key:
            return key
        stream_registry = self._app_state.get("stream_registry")
        if stream_registry is None:
            return self._default_session_key
        ctx = stream_registry.get(request_id)
        if ctx is None:
            return self._default_session_key
        key = self._normalize_session_key(str(ctx.session_id or ""))
        self._bind_request_session(request_id, key)
        return key

    def _resolve_event_session_key(self, event) -> str:
        """Resolve session key for event routing.

        // [LAW:one-source-of-truth] request_id -> session routing is resolved once here.
        """
        request_id = str(getattr(event, "request_id", "") or "")
        key = self._default_session_key
        if event.kind == cc_dump.pipeline.event_types.PipelineEventKind.REQUEST:
            body = getattr(event, "body", {})
            marker = (
                cc_dump.ai.side_channel_marker.extract_marker(body)
                if isinstance(body, dict)
                else None
            )
            if marker is not None:
                # [LAW:one-type-per-behavior] Workbench AI traffic is one inspectable lane.
                key = self._workbench_session_key
            else:
                key = self._normalize_session_key(self._extract_session_id_from_body(body))
            self._bind_request_session(request_id, key)
            self._ensure_session_surface(key)
            return key
        if request_id:
            key = self._session_key_for_request_id(request_id)
        self._ensure_session_surface(key)
        return key

    def _sync_active_stream_footer(self) -> None:
        """Mirror active session stream chips/focus into the view store."""
        ds = self._get_active_domain_store()
        self._view_store.set("streams:active", ds.get_active_stream_chips())
        self._view_store.set("streams:focused", ds.get_focused_stream_id() or "")

    def _get_active_session_panel_state(self) -> tuple[str | None, float | None]:
        """Return session panel identity + last activity for active tab context."""
        active_key = self._active_session_key_from_tabs()
        per_session = self._app_state.get("last_message_time_by_session", {})
        last_message_time = None
        if isinstance(per_session, dict):
            raw_time = per_session.get(active_key)
            if isinstance(raw_time, (int, float)):
                last_message_time = float(raw_time)
        if last_message_time is None:
            raw_fallback = self._app_state.get("last_message_time")
            if isinstance(raw_fallback, (int, float)):
                last_message_time = float(raw_fallback)
        if active_key != self._default_session_key:
            return active_key, last_message_time
        return self._session_id, last_message_time

    def _active_resume_session_id(self) -> str:
        """Resolve session_id used for launch auto-resume from active tab context."""
        active_key = self._active_context_session_key()
        if active_key and active_key != self._default_session_key:
            return active_key
        return str(self._session_id or "")

    def _get_conv(self, session_key: str | None = None):
        key = session_key if session_key is not None else self._active_session_key_from_tabs()
        conv_id = self._session_conv_ids.get(key, self._conv_id)
        return self._query_safe("#" + conv_id)

    def _get_workbench_results_view(self):
        return self._query_safe("#" + self._workbench_view_id)

    def _show_workbench_results_tab(self) -> None:
        tabs = self._get_conv_tabs()
        if tabs is None:
            return
        tabs.active = self._workbench_tab_id

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
            "Cycle panel", "Cycle session/analytics", self.action_cycle_panel
        )
        yield SystemCommand("Toggle logs", "Debug logs", self.action_toggle_logs)
        yield SystemCommand("Toggle info", "Server info panel", self.action_toggle_info)
        yield SystemCommand("Go to top", "Scroll to start", self.action_go_top)
        yield SystemCommand("Go to bottom", "Scroll to end", self.action_go_bottom)
        yield SystemCommand(
            "Toggle follow mode", "Auto-scroll", self.action_toggle_follow
        )
        yield SystemCommand(
            "Next special section",
            "Jump to next special request marker (alt+n)",
            self.action_next_special,
        )
        yield SystemCommand(
            "Previous special section",
            "Jump to previous special request marker (alt+p)",
            self.action_prev_special,
        )
        yield SystemCommand(
            "Next CLAUDE.md section",
            "Jump to next CLAUDE.md-derived section",
            lambda: self.action_next_special("claude_md"),
        )
        yield SystemCommand(
            "Next hook section",
            "Jump to next hook insertion section",
            lambda: self.action_next_special("hook"),
        )
        yield SystemCommand(
            "Next skill consideration",
            "Jump to next skill consideration section",
            lambda: self.action_next_special("skill_consideration"),
        )
        yield SystemCommand(
            "Next skill send",
            "Jump to next Skill tool-use section",
            lambda: self.action_next_special("skill_send"),
        )
        yield SystemCommand(
            "Next tool list",
            "Jump to next tool-list section",
            lambda: self.action_next_special("tool_use_list"),
        )
        yield SystemCommand(
            "Next region tag",
            "Jump to next tagged content region",
            self.action_next_region_tag,
        )
        yield SystemCommand(
            "Previous region tag",
            "Jump to previous tagged content region",
            self.action_prev_region_tag,
        )
        yield SystemCommand(
            "Next thinking region",
            "Jump to next <thinking> content region",
            lambda: self.action_next_region_tag("thinking"),
        )
        yield SystemCommand(
            "Next CLAUDE.md region",
            "Jump to next region tagged from CLAUDE.md content",
            lambda: self.action_next_region_tag("claude_md"),
        )
        yield SystemCommand(
            "Next Bash region",
            "Jump to next region tagged with bash",
            lambda: self.action_next_region_tag("bash"),
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
        for spec in cc_dump.tui.panel_registry.PANEL_REGISTRY:
            widget = _resolve_factory(spec.factory)()
            widget.id = self._panel_ids[spec.name]
            yield widget

        with TabbedContent(id=self._conv_tabs_id):
            with TabPane("Session", id=self._conv_tab_main_id):
                conv = cc_dump.tui.widget_factory.create_conversation_view(
                    view_store=self._view_store,
                    domain_store=self._domain_store,
                )
                conv.id = self._conv_id
                yield conv
            with TabPane("Workbench", id=self._workbench_tab_id):
                results = cc_dump.tui.workbench_results_view.create_workbench_results_view()
                results.id = self._workbench_view_id
                yield results

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
        self._bind_view_store_reactions()

        # [LAW:one-source-of-truth] Restore persisted theme choice
        saved = self._settings_store.get("theme") if self._settings_store else None
        if saved and saved in self.available_themes:
            self.theme = saved
        cc_dump.tui.rendering.set_theme(self.current_theme)
        self._sync_theme_subtitle()
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
                f"Usage: HTTP_PROXY=http://{self._host}:{self._port} ANTHROPIC_BASE_URL=https://api.anthropic.com claude",
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
        self._view_store.set("launch:active_name", cc_dump.app.launch_config.load_active_name())
        if self._resume_ui_state is not None:
            self._apply_resume_ui_state_preload()
        # Footer hydration — reactions are now active
        footer = self._get_footer()
        if footer:
            footer.update_display(
                cc_dump.tui.view_store_bridge.enrich_footer_state(
                    self._view_store.footer_state.get()
                )
            )
        self._sync_active_stream_footer()
        self._log_memory_snapshot("startup")

        if self._replay_data:
            self._process_replay_data()
        if self._resume_ui_state is not None:
            self._apply_resume_ui_state_postload()

    def _bind_view_store_reactions(self) -> None:
        """(Re)bind view-store reactions after app mount.

        // [LAW:single-enforcer] View-store reaction lifecycle is owned here.
        // [LAW:one-source-of-truth] _store_context is canonical reaction context.
        """
        if self._view_store is None:
            return
        ctx = self._store_context if isinstance(self._store_context, dict) else {}
        self._store_context = ctx
        ctx["app"] = self
        ctx.update(cc_dump.tui.view_store_bridge.build_reaction_context(self))

        old_disposers = getattr(self._view_store, "_reaction_disposers", None)
        if isinstance(old_disposers, list):
            for dispose in old_disposers:
                if callable(dispose):
                    try:
                        dispose()
                    except Exception:
                        pass

        self._view_store._reaction_disposers = cc_dump.app.view_store.setup_reactions(
            self._view_store, ctx
        )

    async def action_quit(self) -> None:
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
        self._log_memory_snapshot("shutdown")
        self._closing = True
        self._router.stop()
        _hot_reload.stop_file_watcher()

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
        _TMUX_ACTIVE = {cc_dump.app.tmux_controller.TmuxState.READY, cc_dump.app.tmux_controller.TmuxState.CLAUDE_RUNNING}
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
            "recording_dir": cc_dump.io.sessions.get_recordings_dir(),
            "replay_file": self._replay_file,
            "python_version": sys.version.split()[0],
            "textual_version": textual.__version__,
            "pid": os.getpid(),
        }

    def _log_memory_snapshot(self, phase: str) -> None:
        """Emit a structured memory snapshot to the logs panel when enabled."""
        if not self._memory_snapshot_enabled:
            return
        snapshot = cc_dump.app.memory_stats.capture_snapshot(self)
        ordered_keys = [
            "domain_completed_turns",
            "domain_active_streams",
            "analytics_turns",
            "rendered_turns",
            "line_cache_entries",
            "line_cache_index_keys",
            "block_cache_entries",
            "python_alloc_current_bytes",
            "python_alloc_peak_bytes",
            "python_alloc_tracing",
        ]
        pairs = [f"{key}={snapshot.get(key, 0)}" for key in ordered_keys]
        self._app_log("INFO", f"[memory:{phase}] " + " ".join(pairs))

    def export_ui_state(self) -> dict:
        """Capture durable UI state for sidecar persistence.

        // [LAW:one-source-of-truth] Sidecar export shape is defined here.
        """
        view_state = {}
        for key in (
            "panel:active",
            "panel:side_channel",
            "panel:settings",
            "panel:launch_config",
            "nav:follow",
            "filter:active",
            "streams:view",
            "search:phase",
            "search:query",
            "search:modes",
            "search:cursor_pos",
        ):
            view_state[key] = self._view_store.get(key)

        for _, name, _, _ in cc_dump.tui.category_config.CATEGORY_CONFIG:
            view_state[f"vis:{name}"] = self._view_store.get(f"vis:{name}")
            view_state[f"full:{name}"] = self._view_store.get(f"full:{name}")
            view_state[f"exp:{name}"] = self._view_store.get(f"exp:{name}")

        conversation_states: dict[str, dict] = {}
        for session_key in self._session_conv_ids:
            conv = self._get_conv(session_key=session_key)
            if conv is None:
                continue
            conversation_states[session_key] = conv.get_state()
        active_session_key = self._active_session_key_from_tabs()
        conv_state = conversation_states.get(active_session_key, {})
        if not conv_state:
            conv = self._get_conv()
            if conv is not None:
                conv_state = conv.get_state()

        return {
            "view_store": view_state,
            "conv": conv_state,
            "conversations": {
                "states": conversation_states,
                "active_session_key": active_session_key,
            },
            "app": {
                "show_logs": bool(self.show_logs),
                "show_info": bool(self.show_info),
            },
        }

    def _apply_resume_ui_state_preload(self) -> None:
        """Apply store + app state before replay processing."""
        state = self._resume_ui_state or {}
        view_state = state.get("view_store", {})
        if isinstance(view_state, dict):
            updates = {
                key: value
                for key, value in view_state.items()
                if isinstance(key, str)
            }
            if updates:
                self._view_store.update(updates)

        app_state = state.get("app", {})
        if isinstance(app_state, dict):
            self.show_logs = bool(app_state.get("show_logs", self.show_logs))
            self.show_info = bool(app_state.get("show_info", self.show_info))

    def _apply_resume_ui_state_postload(self) -> None:
        """Apply conversation-view state after replay/live initial hydration."""
        state = self._resume_ui_state or {}
        conversations = state.get("conversations", {})
        if isinstance(conversations, dict):
            states = conversations.get("states", {})
            active_session_key = conversations.get("active_session_key", "")
            restored_any = False
            if isinstance(states, dict):
                for session_key, conv_state in states.items():
                    if not isinstance(session_key, str):
                        continue
                    if not isinstance(conv_state, dict) or not conv_state:
                        continue
                    self._ensure_session_surface(session_key)
                    conv = self._get_conv(session_key=session_key)
                    if conv is None:
                        continue
                    conv.restore_state(conv_state)
                    conv.rerender(self.active_filters)
                    restored_any = True
            if isinstance(active_session_key, str) and active_session_key in self._session_tab_ids:
                tabs = self._get_conv_tabs()
                if tabs is not None:
                    tabs.active = self._session_tab_ids[active_session_key]
                self._active_session_key = active_session_key
                self._domain_store = self._get_active_domain_store()
            if restored_any:
                self._sync_active_stream_footer()
                return

        conv_state = state.get("conv", {})
        conv = self._get_conv()
        if conv is not None and isinstance(conv_state, dict) and conv_state:
            conv.restore_state(conv_state)
            conv.rerender(self.active_filters)

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
                events = cc_dump.pipeline.har_replayer.convert_to_events(
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
        session_key = self._resolve_event_session_key(event)
        conv = self._get_conv(session_key=session_key)
        stats = self._get_stats()
        if stats is None:
            return
        if conv is None:
            conv = self._query_safe("#" + self._conv_id)
        if conv is None:
            return
        domain_store = self._get_domain_store(session_key)
        active_session_key = self._active_session_key_from_tabs()
        is_active_session = session_key == active_session_key

        # [LAW:dataflow-not-control-flow] Unified context dict
        widgets = {
            "conv": conv,
            "stats": stats,
            "filters": self.active_filters,
            "view_store": self._view_store if is_active_session else None,
            "domain_store": domain_store,
            "stats_domain_store": self._get_active_domain_store(),
            "all_domain_stores": self._iter_domain_stores(),
            "refresh_callbacks": {
                "refresh_session": self._refresh_session,
            },
            "analytics_store": self._analytics_store,
        }

        # [LAW:dataflow-not-control-flow] Always call handler, use no-op for unknown
        handler = cast(
            cc_dump.tui.event_handlers.EventHandler,
            cc_dump.tui.event_handlers.EVENT_HANDLERS.get(
                kind, cc_dump.tui.event_handlers._noop
            ),
        )
        self._app_state = handler(
            event, self._state, widgets, self._app_state, self._app_log
        )
        request_id = str(getattr(event, "request_id", "") or "")
        if request_id:
            resolved_key = self._session_key_for_request_id(request_id)
            self._ensure_session_surface(resolved_key)
            per_session = self._app_state.get("last_message_time_by_session", {})
            if not isinstance(per_session, dict):
                per_session = {}
            per_session[resolved_key] = time.monotonic()
            self._app_state["last_message_time_by_session"] = per_session

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
        self._sync_active_stream_footer()

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        """Sync active session context when conversation tab changes."""
        if event.tabbed_content.id != self._conv_tabs_id:
            return
        pane_id = str(getattr(event.pane, "id", "") or "")
        for session_key, tab_id in self._session_tab_ids.items():
            if tab_id == pane_id:
                self._active_session_key = session_key
                break
        # // [LAW:one-source-of-truth] Back-compat alias points to active session store.
        self._domain_store = self._get_active_domain_store()
        self._sync_active_stream_footer()

    # ─── Delegates to extracted modules ────────────────────────────────
    # Textual requires action_* and watch_* as methods on the App class.

    # Hot-reload
    async def _start_file_watcher(self):
        await _hot_reload.start_file_watcher(self)

    # Theme
    def _apply_markdown_theme(self):
        _theme.apply_markdown_theme(self)

    def _sync_theme_subtitle(self) -> None:
        """Refresh title chrome color from current active theme."""
        try:
            info_color = cc_dump.tui.rendering.get_theme_colors().info
        except RuntimeError:
            info_color = cc_dump.core.palette.PALETTE.info
        self.sub_title = f"[{info_color}]session: {self._session_name}[/]"

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
        config = cc_dump.app.launch_config.get_active_config()
        session_id = self._active_resume_session_id() if config.auto_resume else ""
        command = cc_dump.app.launch_config.build_full_command(config, session_id)
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
        configs = cc_dump.app.launch_config.load_configs()
        active_name = cc_dump.app.launch_config.load_active_name()

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

        session_id = self._active_resume_session_id() if config.auto_resume else ""
        command = cc_dump.app.launch_config.build_full_command(config, session_id)
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
        cc_dump.app.launch_config.save_configs(msg.configs)
        cc_dump.app.launch_config.save_active_name(msg.active_name)
        self._close_launch_config()
        self.notify("Launch configs saved")

    def on_launch_config_panel_cancelled(self, msg) -> None:
        """Handle LaunchConfigPanel.Cancelled — close without saving."""
        self._close_launch_config()

    def on_launch_config_panel_quick_launch(self, msg) -> None:
        """Handle LaunchConfigPanel.QuickLaunch — save, close, launch."""
        cc_dump.app.launch_config.save_configs(msg.configs)
        cc_dump.app.launch_config.save_active_name(msg.active_name)
        self._close_launch_config()
        self._launch_with_config(msg.config)

    def on_launch_config_panel_activated(self, msg) -> None:
        """Handle LaunchConfigPanel.Activated — save active name, notify."""
        cc_dump.app.launch_config.save_configs(msg.configs)
        cc_dump.app.launch_config.save_active_name(msg.name)
        self._view_store.set("launch:active_name", msg.name)
        self.notify("Active: {}".format(msg.name))

    # Side channel
    def action_toggle_side_channel(self):
        _actions.toggle_side_channel(self)

    def _open_side_channel(self):
        """Open AI Workbench sidebar."""
        self._view_store.set("panel:side_channel", True)
        panel = cc_dump.tui.side_channel_panel.create_side_channel_panel()
        self.screen.mount(panel)
        # Reset sc state — reaction pushes to panel and results tab.
        self._set_side_channel_result(
            text="",
            source="",
            elapsed_ms=0,
            loading=False,
            active_action="",
        )
        self._view_store.set("sc:purpose_usage", {})
        self._reset_sc_action_review_state()
        self._refresh_side_channel_usage()
        # Initial hydration — reaction may not fire if values unchanged from defaults.
        # Run after refresh so panel children are mounted and queryable.
        self.call_after_refresh(
            lambda: panel.update_display(
                cc_dump.tui.side_channel_panel.SideChannelPanelState(
                    **self._view_store.sc_panel_state.get()
                )
            )
        )

    def _close_side_channel(self):
        """Close AI Workbench sidebar and restore focus to conversation."""
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

        context_session_key = self._active_context_session_key()
        messages = self._collect_recent_messages(10)
        if not messages:
            self._set_side_channel_result(
                text="No messages to summarize.",
                source="fallback",
                elapsed_ms=0,
                loading=False,
                active_action="",
                focus_results=True,
                context_session_key=context_session_key,
            )
            return

        with transaction():
            self._view_store.set("sc:loading", True)
            self._view_store.set("sc:active_action", "summarize_recent")

        dispatcher = self._data_dispatcher

        source_session_id = self._active_resume_session_id()

        def _do_summarize():
            result = dispatcher.summarize_messages(messages, source_session_id=source_session_id)
            self.call_from_thread(self._on_side_channel_result, result, context_session_key)

        self.run_worker(_do_summarize, thread=True, exclusive=False)

    def _on_side_channel_result(self, result, context_session_key: str):
        """Callback from worker thread with AI result."""
        self._set_side_channel_result(
            text=result.text,
            source=result.source,
            elapsed_ms=result.elapsed_ms,
            loading=False,
            active_action="",
            focus_results=True,
            context_session_key=context_session_key,
        )
        self._refresh_side_channel_usage()

    def _refresh_side_channel_usage(self) -> None:
        """Project canonical side-channel purpose usage into the panel state.

        // [LAW:one-source-of-truth] AnalyticsStore remains canonical source for usage totals.
        """
        usage = (
            self._analytics_store.get_side_channel_purpose_summary()
            if self._analytics_store is not None
            else {}
        )
        self._view_store.set("sc:purpose_usage", usage)

    def _collect_recent_messages(self, count: int) -> list[dict]:
        """Extract last N messages from captured API traffic."""
        recent_messages = cast(list[dict], self._app_state.get("recent_messages", []))
        return recent_messages[-count:]

    def _get_side_channel_panel_widget(self):
        panel = self.screen.query(cc_dump.tui.side_channel_panel.SideChannelPanel)
        return panel.first() if panel else None

    def _parse_qa_scope(self, draft, *, total_messages: int) -> tuple[cc_dump.ai.conversation_qa.QAScope, str]:
        """Build a QAScope from panel draft input.

        // [LAW:single-enforcer] Scope parsing + validation lives in one app boundary.
        """
        mode = str(draft.scope_mode or cc_dump.ai.conversation_qa.SCOPE_SELECTED_RANGE)
        if mode == cc_dump.ai.conversation_qa.SCOPE_WHOLE_SESSION:
            return (
                cc_dump.ai.conversation_qa.QAScope(
                    mode=mode,
                    explicit_whole_session=bool(draft.explicit_whole_session),
                ),
                "",
            )

        if mode == cc_dump.ai.conversation_qa.SCOPE_SELECTED_INDICES:
            indices_text = draft.indices_text.strip()
            if not indices_text:
                return (
                    cc_dump.ai.conversation_qa.QAScope(
                        mode=mode,
                        indices=(),
                    ),
                    "",
                )
            parts = [part.strip() for part in indices_text.split(",") if part.strip()]
            try:
                indices = tuple(sorted({int(part) for part in parts}))
            except ValueError:
                return (cc_dump.ai.conversation_qa.QAScope(mode=mode, indices=()), "indices must be integers")
            return (cc_dump.ai.conversation_qa.QAScope(mode=mode, indices=indices), "")

        default_start = max(0, total_messages - 10)
        default_end = max(0, total_messages - 1)
        start_text = draft.source_start_text.strip()
        end_text = draft.source_end_text.strip()
        try:
            start = int(start_text) if start_text else default_start
            end = int(end_text) if end_text else default_end
        except ValueError:
            return (
                cc_dump.ai.conversation_qa.QAScope(mode=cc_dump.ai.conversation_qa.SCOPE_SELECTED_RANGE),
                "range start/end must be integers",
            )
        return (
            cc_dump.ai.conversation_qa.QAScope(
                mode=cc_dump.ai.conversation_qa.SCOPE_SELECTED_RANGE,
                source_start=start,
                source_end=end,
            ),
            "",
        )

    def _render_qa_result_text(
        self,
        *,
        question: str,
        scope_mode: str,
        selected_indices: tuple[int, ...],
        estimate,
        body: str,
        prefix: str,
        error: str = "",
    ) -> str:
        """Render deterministic QA output shown in the panel result area."""
        lines = [
            prefix,
            cc_dump.tui.side_channel_panel.render_qa_scope_line(
                scope_mode=scope_mode,
                selected_indices=selected_indices,
            ),
            cc_dump.tui.side_channel_panel.render_qa_estimate_line(
                scope_mode=estimate.scope_mode,
                message_count=estimate.message_count,
                estimated_input_tokens=estimate.estimated_input_tokens,
                estimated_output_tokens=estimate.estimated_output_tokens,
                estimated_total_tokens=estimate.estimated_total_tokens,
            ),
            f"question: {question}",
        ]
        if error:
            lines.append(f"error: {error}")
        if body:
            lines.extend(["", body])
        return "\n".join(lines)

    def _set_side_channel_result(
        self,
        *,
        text: str,
        source: str,
        elapsed_ms: int,
        loading: bool = False,
        active_action: str = "",
        focus_results: bool = False,
        context_session_key: str | None = None,
    ) -> None:
        context_key = self._context_session_key(
            context_session_key
            if isinstance(context_session_key, str)
            else self._active_context_session_key()
        )
        with transaction():
            self._view_store.set("sc:loading", loading)
            self._view_store.set("sc:active_action", active_action)
            self._view_store.set("sc:result_text", text)
            self._view_store.set("sc:result_source", source)
            self._view_store.set("sc:result_elapsed_ms", elapsed_ms)
        workbench_results = self._get_workbench_results_view()
        if workbench_results is not None:
            workbench_results.update_result(
                text=text,
                source=source,
                elapsed_ms=elapsed_ms,
                action=active_action,
                context_session_id=context_key,
            )
        if focus_results:
            self._show_workbench_results_tab()

    def _workbench_preview(self, feature: str, owner_ticket: str) -> None:
        """Publish deterministic placeholder output for non-integrated controls.

        // [LAW:single-enforcer] Placeholder behavior is centralized here.
        """
        preview = (
            f"{feature} is planned but not wired in this panel yet.\n"
            f"Owner: {owner_ticket}\n"
            "No side effects were executed."
        )
        self._set_side_channel_result(
            text=preview,
            source="preview",
            elapsed_ms=0,
            loading=False,
            active_action="",
            focus_results=True,
        )

    def action_sc_summarize_recent(self) -> None:
        """Action target for Workbench summarize control."""
        self._side_channel_summarize()

    def action_sc_summarize(self) -> None:
        """Back-compatible alias for summarize action."""
        self.action_sc_summarize_recent()

    def action_sc_qa_estimate(self) -> None:
        panel = self._get_side_channel_panel_widget()
        if panel is None:
            return
        draft = panel.read_qa_draft()
        messages = self._collect_recent_messages(50)
        scope, parse_error = self._parse_qa_scope(draft, total_messages=len(messages))
        normalized_scope = cc_dump.ai.conversation_qa.normalize_scope(scope, total_messages=len(messages))
        selected_messages = cc_dump.ai.conversation_qa.select_messages(messages, normalized_scope)
        estimate = cc_dump.ai.conversation_qa.estimate_qa_budget(
            question=draft.question,
            selected_messages=selected_messages,
            scope_mode=normalized_scope.scope.mode,
        )
        error = parse_error or normalized_scope.error
        question = draft.question.strip()
        if not question:
            error = "question is required"
        body = "Ready to ask scoped Q&A." if not error else ""
        text = self._render_qa_result_text(
            question=question or "(empty)",
            scope_mode=normalized_scope.scope.mode,
            selected_indices=normalized_scope.selected_indices,
            estimate=estimate,
            body=body,
            prefix="pre-send estimate",
            error=error,
        )
        self._set_side_channel_result(
            text=text,
            source="preview",
            elapsed_ms=0,
            loading=False,
            active_action="",
            focus_results=True,
        )

    def action_sc_qa_submit(self) -> None:
        if self._view_store.get("sc:loading"):
            return
        panel = self._get_side_channel_panel_widget()
        if panel is None:
            return
        context_session_key = self._active_context_session_key()
        draft = panel.read_qa_draft()
        messages = self._collect_recent_messages(50)
        scope, parse_error = self._parse_qa_scope(draft, total_messages=len(messages))
        normalized_scope = cc_dump.ai.conversation_qa.normalize_scope(scope, total_messages=len(messages))
        selected_messages = cc_dump.ai.conversation_qa.select_messages(messages, normalized_scope)
        estimate = cc_dump.ai.conversation_qa.estimate_qa_budget(
            question=draft.question,
            selected_messages=selected_messages,
            scope_mode=normalized_scope.scope.mode,
        )

        question = draft.question.strip()
        error = parse_error or normalized_scope.error
        if not question:
            error = "question is required"
        if not messages:
            error = "no captured messages available"

        if error:
            text = self._render_qa_result_text(
                question=question or "(empty)",
                scope_mode=normalized_scope.scope.mode,
                selected_indices=normalized_scope.selected_indices,
                estimate=estimate,
                body="",
                prefix="scoped Q&A blocked",
                error=error,
            )
            self._set_side_channel_result(
                text=text,
                source="fallback",
                elapsed_ms=0,
                loading=False,
                active_action="",
                focus_results=True,
                context_session_key=context_session_key,
            )
            return

        if self._data_dispatcher is None:
            text = self._render_qa_result_text(
                question=question,
                scope_mode=normalized_scope.scope.mode,
                selected_indices=normalized_scope.selected_indices,
                estimate=estimate,
                body="",
                prefix="scoped Q&A blocked",
                error="dispatcher unavailable",
            )
            self._set_side_channel_result(
                text=text,
                source="fallback",
                elapsed_ms=0,
                loading=False,
                active_action="",
                focus_results=True,
                context_session_key=context_session_key,
            )
            return

        self._set_side_channel_result(
            text="Running scoped Q&A…",
            source="preview",
            elapsed_ms=0,
            loading=True,
            active_action="qa_submit",
            context_session_key=context_session_key,
        )

        dispatcher = self._data_dispatcher
        source_session_id = self._active_resume_session_id()
        request_id = f"sc-qa-{int(time.time() * 1000)}"

        def _do_qa() -> None:
            result = dispatcher.ask_conversation_question(
                messages,
                question=question,
                scope=scope,
                source_session_id=source_session_id,
                request_id=request_id,
            )
            self.call_from_thread(
                self._on_side_channel_qa_result,
                result,
                question,
                context_session_key,
            )

        self.run_worker(_do_qa, thread=True, exclusive=False)

    def _on_side_channel_qa_result(self, result, question: str, context_session_key: str) -> None:
        text = self._render_qa_result_text(
            question=question,
            scope_mode=result.artifact.scope_mode,
            selected_indices=tuple(result.artifact.selected_indices),
            estimate=result.estimate,
            body=result.markdown,
            prefix="scoped Q&A result",
            error=result.error,
        )
        self._set_side_channel_result(
            text=text,
            source=result.source,
            elapsed_ms=result.elapsed_ms,
            loading=False,
            active_action="",
            focus_results=True,
            context_session_key=context_session_key,
        )
        self._refresh_side_channel_usage()

    def _render_action_candidates_text(self, *, batch_id: str, items: list[object], source: str, error: str = "") -> str:
        lines = [
            "action extraction review",
            f"batch: {batch_id}",
            f"source: {source}",
            f"candidate_count: {len(items)}",
        ]
        if error:
            lines.append(f"error: {error}")
        if not items:
            lines.append("No action/deferred candidates found.")
            return "\n".join(lines)

        lines.append("")
        lines.append("candidates:")
        for index, item in enumerate(items):
            kind = str(getattr(item, "kind", "action"))
            text = str(getattr(item, "text", "")).strip()
            confidence = float(getattr(item, "confidence", 0.0))
            source_links = getattr(item, "source_links", []) or []
            link_parts = [
                "{}:{}".format(
                    str(getattr(link, "request_id", "")),
                    int(getattr(link, "message_index", -1)),
                )
                for link in source_links
            ]
            source_text = ", ".join(link_parts) if link_parts else "(none)"
            lines.append(
                "{}. [{}] {} (confidence={:.2f}) sources={}".format(
                    index,
                    kind,
                    text,
                    confidence,
                    source_text,
                )
            )
        lines.extend(
            [
                "",
                "review inputs:",
                "- set accept indices and reject indices in Action Review controls",
                "- click Apply Review to confirm explicit accept/reject",
            ]
        )
        return "\n".join(lines)

    def action_sc_action_extract(self) -> None:
        if self._view_store.get("sc:loading"):
            return
        context_session_key = self._active_context_session_key()
        if self._data_dispatcher is None:
            self._set_side_channel_result(
                text="action extraction blocked\nerror: dispatcher unavailable",
                source="fallback",
                elapsed_ms=0,
                loading=False,
                active_action="",
                focus_results=True,
                context_session_key=context_session_key,
            )
            return

        messages = self._collect_recent_messages(50)
        if not messages:
            self._set_side_channel_result(
                text="action extraction blocked\nerror: no captured messages available",
                source="fallback",
                elapsed_ms=0,
                loading=False,
                active_action="",
                focus_results=True,
                context_session_key=context_session_key,
            )
            return

        self._set_side_channel_result(
            text="Running action extraction…",
            source="preview",
            elapsed_ms=0,
            loading=True,
            active_action="action_extract",
            context_session_key=context_session_key,
        )
        dispatcher = self._data_dispatcher
        source_session_id = self._active_resume_session_id()
        request_id = f"sc-action-{int(time.time() * 1000)}"

        def _do_action_extract() -> None:
            result = dispatcher.extract_action_items(
                messages,
                source_session_id=source_session_id,
                request_id=request_id,
            )
            self.call_from_thread(
                self._on_side_channel_action_extract_result,
                result,
                context_session_key,
            )

        self.run_worker(_do_action_extract, thread=True, exclusive=False)

    def _on_side_channel_action_extract_result(self, result, context_session_key: str) -> None:
        self._set_sc_action_batch_id(str(result.batch_id or ""))
        self._set_sc_action_items(list(result.items or []))
        text = self._render_action_candidates_text(
            batch_id=self._get_sc_action_batch_id(),
            items=self._get_sc_action_items(),
            source=result.source,
            error=result.error,
        )
        self._set_side_channel_result(
            text=text,
            source=result.source,
            elapsed_ms=result.elapsed_ms,
            loading=False,
            active_action="",
            focus_results=True,
            context_session_key=context_session_key,
        )
        self._refresh_side_channel_usage()

    def action_sc_action_apply_review(self) -> None:
        panel = self._get_side_channel_panel_widget()
        if panel is None:
            return
        if self._data_dispatcher is None:
            self._set_side_channel_result(
                text="apply review blocked\nerror: dispatcher unavailable",
                source="fallback",
                elapsed_ms=0,
                loading=False,
                active_action="",
                focus_results=True,
            )
            return
        if not self._get_sc_action_batch_id():
            self._set_side_channel_result(
                text="apply review blocked\nerror: run Extract Actions first",
                source="fallback",
                elapsed_ms=0,
                loading=False,
                active_action="",
                focus_results=True,
            )
            return
        draft = panel.read_action_review_draft()
        accept_indices, accept_error = cc_dump.tui.side_channel_panel.parse_review_indices(
            draft.accept_indices_text
        )
        reject_indices, reject_error = cc_dump.tui.side_channel_panel.parse_review_indices(
            draft.reject_indices_text
        )
        parse_error = accept_error or reject_error
        if parse_error:
            self._set_side_channel_result(
                text=f"apply review blocked\nerror: {parse_error}",
                source="fallback",
                elapsed_ms=0,
                loading=False,
                active_action="",
                focus_results=True,
            )
            return
        if not accept_indices and not reject_indices:
            self._set_side_channel_result(
                text="apply review blocked\nerror: provide explicit accept and/or reject indices",
                source="fallback",
                elapsed_ms=0,
                loading=False,
                active_action="",
                focus_results=True,
            )
            return

        items = self._get_sc_action_items()
        max_index = len(items) - 1
        all_requested = tuple(sorted(set(accept_indices) | set(reject_indices)))
        out_of_range = [idx for idx in all_requested if idx < 0 or idx > max_index]
        if out_of_range:
            self._set_side_channel_result(
                text=(
                    "apply review blocked\n"
                    f"error: indices out of range for candidate_count={len(items)}: {out_of_range}"
                ),
                source="fallback",
                elapsed_ms=0,
                loading=False,
                active_action="",
                focus_results=True,
            )
            return
        overlap = sorted(set(accept_indices) & set(reject_indices))
        if overlap:
            self._set_side_channel_result(
                text=f"apply review blocked\nerror: indices overlap between accept/reject: {overlap}",
                source="fallback",
                elapsed_ms=0,
                loading=False,
                active_action="",
                focus_results=True,
            )
            return

        accepted_item_ids = [str(getattr(items[idx], "item_id", "")) for idx in accept_indices]
        accepted = self._data_dispatcher.accept_action_items(
            batch_id=self._get_sc_action_batch_id(),
            item_ids=accepted_item_ids,
            create_beads=draft.create_beads and bool(accepted_item_ids),
        )
        rejected_items = [items[idx] for idx in reject_indices]
        resolved_indices = set(accept_indices) | set(reject_indices)
        self._set_sc_action_items([item for idx, item in enumerate(items) if idx not in resolved_indices])

        lines = [
            "action review applied",
            f"batch: {self._get_sc_action_batch_id()}",
            f"accepted_count: {len(accepted)}",
            f"rejected_count: {len(rejected_items)}",
            f"beads_enabled: {draft.create_beads and bool(accepted_item_ids)}",
            "",
            "accepted:",
        ]
        if not accepted:
            lines.append("- (none)")
        for item in accepted:
            beads_id = str(getattr(item, "beads_issue_id", "") or "")
            beads_suffix = f" beads={beads_id}" if beads_id else ""
            lines.append(f"- [{item.kind}] {item.text}{beads_suffix}")

        lines.append("")
        lines.append("rejected:")
        if not rejected_items:
            lines.append("- (none)")
        for item in rejected_items:
            lines.append(f"- [{getattr(item, 'kind', 'action')}] {getattr(item, 'text', '')}")
        lines.append("")
        lines.append(f"remaining_candidates: {len(self._get_sc_action_items())}")

        self._set_side_channel_result(
            text="\n".join(lines),
            source="preview",
            elapsed_ms=0,
            loading=False,
            active_action="",
            focus_results=True,
        )

    def action_sc_utility_run(self) -> None:
        if self._view_store.get("sc:loading"):
            return
        panel = self._get_side_channel_panel_widget()
        if panel is None:
            return
        context_session_key = self._active_context_session_key()
        draft = panel.read_utility_draft()
        utility_id = draft.utility_id.strip()
        if not utility_id:
            self._set_side_channel_result(
                text="utility run blocked\nerror: no utility selected",
                source="fallback",
                elapsed_ms=0,
                loading=False,
                active_action="",
                focus_results=True,
                context_session_key=context_session_key,
            )
            return
        if self._data_dispatcher is None:
            self._set_side_channel_result(
                text=f"utility run blocked\nutility_id: {utility_id}\nerror: dispatcher unavailable",
                source="fallback",
                elapsed_ms=0,
                loading=False,
                active_action="",
                focus_results=True,
                context_session_key=context_session_key,
            )
            return
        messages = self._collect_recent_messages(50)
        self._set_side_channel_result(
            text=f"Running utility {utility_id}…",
            source="preview",
            elapsed_ms=0,
            loading=True,
            active_action="utility_run",
            context_session_key=context_session_key,
        )
        dispatcher = self._data_dispatcher
        source_session_id = self._active_resume_session_id()

        def _do_utility_run() -> None:
            result = dispatcher.run_utility(
                messages,
                utility_id=utility_id,
                source_session_id=source_session_id,
            )
            self.call_from_thread(self._on_side_channel_utility_result, result, context_session_key)

        self.run_worker(_do_utility_run, thread=True, exclusive=False)

    def _on_side_channel_utility_result(self, result, context_session_key: str) -> None:
        lines = [
            "utility result",
            f"utility_id: {result.utility_id}",
            f"source: {result.source}",
        ]
        if result.error:
            lines.append(f"error: {result.error}")
        lines.extend(["", result.text])
        self._set_side_channel_result(
            text="\n".join(lines),
            source=result.source,
            elapsed_ms=result.elapsed_ms,
            loading=False,
            active_action="",
            focus_results=True,
            context_session_key=context_session_key,
        )
        self._refresh_side_channel_usage()

    def action_sc_preview_qa(self) -> None:
        self.action_sc_qa_submit()

    def action_sc_preview_action_review(self) -> None:
        self.action_sc_action_extract()

    def action_sc_preview_handoff(self) -> None:
        self._workbench_preview("Handoff Draft", "cc-dump-mjb.4")

    def action_sc_preview_release_notes(self) -> None:
        self._workbench_preview("Release Notes", "cc-dump-mjb.4")

    def action_sc_preview_utilities(self) -> None:
        self.action_sc_utility_run()

    # Navigation
    def action_toggle_follow(self):
        _actions.toggle_follow(self)

    def action_focus_stream(self, request_id: str):
        _actions.focus_stream(self, request_id)

    def action_toggle_stream_view_mode(self):
        _actions.toggle_stream_view_mode(self)

    def action_next_special(self, marker_key: str = "all"):
        _actions.next_special(self, marker_key)

    def action_prev_special(self, marker_key: str = "all"):
        _actions.prev_special(self, marker_key)

    def action_next_region_tag(self, tag: str = "all"):
        _actions.next_region_tag(self, tag)

    def action_prev_region_tag(self, tag: str = "all"):
        _actions.prev_region_tag(self, tag)

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
        for name in cc_dump.tui.panel_registry.PANEL_ORDER:
            widget = self._get_panel(name)
            if widget is not None:
                widget.display = (name == active)

    def watch_show_logs(self, value):
        pass

    def watch_show_info(self, value):
        pass

    def watch_theme(self, theme_name: str) -> None:
        if not stx.is_safe(self):
            return
        cc_dump.tui.rendering.set_theme(self.current_theme)
        self._sync_theme_subtitle()
        self._apply_markdown_theme()
        gen = self._view_store.get("theme:generation")
        self._view_store.set("theme:generation", gen + 1)
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
