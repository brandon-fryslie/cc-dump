"""Main TUI application using Textual.

// [LAW:locality-or-seam] Thin coordinator — delegates to extracted modules:
//   category_config, action_handlers, search_controller, dump_export,
//   theme_controller, hot_reload_controller.
// [LAW:one-source-of-truth] View store (SnarfX) is the sole state for visibility.
//   active_filters is a Computed on the view store.
"""

import importlib
import logging
import os
import queue
import sys
import threading
import time
import tracemalloc
import traceback
from functools import lru_cache
from typing import Callable, Optional, Protocol, TypedDict, cast

import textual
import textual.filter as _textual_filter
from textual.app import App, ComposeResult, SystemCommand
from textual.css.query import NoMatches
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Header, TabbedContent, TabPane
from rich.style import Style


# Module-level imports for hot-reload (never use `from` for these)
import cc_dump.core.formatting
import cc_dump.io.settings
import cc_dump.io.logging_setup
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
import cc_dump.tui.panel_registry
from cc_dump.tui import search_controller as _search
from cc_dump.tui import dump_export as _dump
from cc_dump.tui import theme_controller as _theme
from cc_dump.tui import hot_reload_controller as _hot_reload
from cc_dump.tui import lifecycle_controller as _lifecycle
from cc_dump.tui import side_channel_controller as _side_channel
from cc_dump.tui import settings_launch_controller as _settings_launch

# Additional module-level imports
import cc_dump.core.palette
import cc_dump.app.error_models
import cc_dump.app.launch_config
import cc_dump.app.tmux_controller
import cc_dump.tui.settings_panel
import cc_dump.tui.launch_config_panel
import cc_dump.tui.side_channel_panel
import cc_dump.tui.error_indicator
import cc_dump.pipeline.har_replayer
import cc_dump.io.sessions
import cc_dump.app.memory_stats
import cc_dump.pipeline.event_types
import cc_dump.app.view_store
import cc_dump.ai.conversation_qa
import cc_dump.ai.side_channel_marker
import cc_dump.providers

from cc_dump.io.stderr_tee import get_tee as _get_tee
import cc_dump.app.domain_store
from snarfx import textual as stx

logger = logging.getLogger(__name__)


class _KeyConsumer(Protocol):
    def check_consume_key(self, key: str, character: str | None) -> bool:
        ...


class _NullKeyConsumer:
    def check_consume_key(self, key: str, character: str | None) -> bool:
        return False


_NULL_KEY_CONSUMER = _NullKeyConsumer()


def _resolve_key_consumer(widget: Widget | None) -> _KeyConsumer:
    # [LAW:single-enforcer] Widgets are the sole authority for key consumption.
    check_consume_key = getattr(widget, "check_consume_key", None)
    return cast(_KeyConsumer, widget) if callable(check_consume_key) else _NULL_KEY_CONSUMER


def _event_key_is_consumed(event, consumer: _KeyConsumer) -> bool:
    return bool(consumer.check_consume_key(event.key, event.character))


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


_patch_textual_monochrome_style()


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
    current_turn_usage_by_request: dict[str, TurnUsage]
    pending_request_headers: dict[str, dict[str, str]]
    recent_messages: list[dict]
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

    def __init__(
        self,
        event_queue,
        state,
        router,
        provider_states: dict[str, dict[str, object]] | None = None,
        analytics_store=None,
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
        domain_store=None,
        store_context=None,
        provider_endpoints: cc_dump.providers.ProviderEndpointMap | None = None,
        auto_launch_config: Optional[str] = None,
        auto_launch_extra_args: Optional[list[str]] = None,
    ):
        super().__init__()
        self._event_queue = event_queue
        # [LAW:one-source-of-truth] Default-provider state is an alias into canonical per-provider state.
        self._provider_states = dict(provider_states or {})
        self._provider_states.setdefault(cc_dump.providers.DEFAULT_PROVIDER_KEY, state)
        self._state = self._provider_states[cc_dump.providers.DEFAULT_PROVIDER_KEY]
        self._router = router
        self._analytics_store = analytics_store
        self._session_id: str | None = None
        self._host = host
        self._port = port
        self._target = target
        # // [LAW:one-source-of-truth] Active provider endpoints are owned here.
        if provider_endpoints is None:
            provider_endpoints = {
                cc_dump.providers.DEFAULT_PROVIDER_KEY: cc_dump.providers.default_provider_endpoint(
                    host,
                    port,
                    target or "",
                )
            }
        # // [LAW:single-enforcer] Provider endpoint normalization is centralized in cc_dump.providers.
        self._provider_endpoints = dict(provider_endpoints)
        self._replay_data = replay_data
        self._recording_path = recording_path
        self._replay_file = replay_file
        self._tmux_controller = tmux_controller
        self._side_channel_manager = side_channel_manager
        self._data_dispatcher = data_dispatcher
        self._settings_store = settings_store
        self._view_store = view_store
        self._domain_store = domain_store if domain_store is not None else cc_dump.app.domain_store.DomainStore()
        self._store_context = store_context
        # // [LAW:one-source-of-truth] App owns render runtime state for theme/render coupling.
        self._render_runtime = cc_dump.tui.rendering.create_render_runtime()
        self._auto_launch_config = auto_launch_config
        self._auto_launch_extra_args = list(auto_launch_extra_args) if auto_launch_extra_args else []
        self._closing = False
        self._quit_requested_at: float | None = None
        self._markdown_theme_pushed = False
        self._memory_snapshot_enabled = (
            str(os.environ.get("CC_DUMP_MEMORY_SNAPSHOT", "0")).strip().lower()
            in {"1", "true", "yes", "on"}
        )
        if self._memory_snapshot_enabled and not tracemalloc.is_tracing():
            tracemalloc.start(25)

        self._replay_complete = threading.Event()
        if not replay_data:
            self._replay_complete.set()

        self._app_state: AppState = {
            "current_turn_usage_by_request": {},
            "pending_request_headers": {},
            "last_message_time_by_session": {},
        }

        self._launch_configs_cache: list | None = None
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
        self._default_session_key = "__default__"
        # // [LAW:one-source-of-truth] Request/session routing ownership lives in app state.
        self._request_session_keys: dict[str, str] = {}
        self._session_domain_stores: dict[str, cc_dump.app.domain_store.DomainStore] = {
            self._default_session_key: self._domain_store
        }
        self._session_conv_ids: dict[str, str] = {
            self._default_session_key: self._conv_id
        }
        self._session_tab_ids: dict[str, str] = {
            self._default_session_key: self._conv_tab_main_id
        }
        self._active_session_key = self._default_session_key
        self._last_primary_session_key = self._default_session_key
        # [LAW:one-source-of-truth] Side-channel action review state is owned by app boundary.
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

    @property
    def view_store(self):
        """// [LAW:one-source-of-truth] Expose canonical view store to widgets/controllers."""
        return self._view_store

    # ─── Widget accessors ──────────────────────────────────────────────

    def _query_safe(self, selector):
        try:
            return self.query_one(selector)
        except NoMatches:
            return None

    def _get_conv_tabs(self):
        return self._query_safe("#" + self._conv_tabs_id)

    def _normalize_session_key(self, session_id: str) -> str:
        return session_id if session_id else self._default_session_key

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

    def _provider_state(self, provider: str) -> dict[str, object]:
        return self._provider_states.get(provider, self._state)

    def _total_request_count(self) -> int:
        return sum(
            count
            for count in (
                state.get("request_counter", 0)
                for state in self._provider_states.values()
                if isinstance(state, dict)
            )
            if isinstance(count, int)
        )

    def _session_tab_title(self, session_key: str) -> str:
        if session_key == self._default_session_key:
            return cc_dump.providers.get_provider_spec(
                cc_dump.providers.DEFAULT_PROVIDER_KEY
            ).tab_title
        if session_key == self._workbench_session_key:
            return "Workbench Session"
        if self._is_side_channel_session_key(session_key):
            parts = session_key.split(":", 2)
            suffix = parts[2] if len(parts) > 2 else session_key
            return "SC " + suffix[:8]
        # Provider-prefixed session keys: "<provider>:__default__" → provider tab title.
        provider = cc_dump.providers.session_provider(session_key)
        if provider != cc_dump.providers.DEFAULT_PROVIDER_KEY:
            spec = cc_dump.providers.get_provider_spec(provider)
            _, _, suffix = session_key.partition(":")
            if suffix == "__default__":
                return spec.tab_title
            return f"{spec.tab_short_prefix} {suffix[:8]}"
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
            runtime=self._render_runtime,
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
        self._request_session_keys[request_id] = self._normalize_session_key(session_key)

    def _session_key_for_request_id(self, request_id: str) -> str:
        key = self._request_session_keys.get(request_id)
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

    def _resolve_event_provider(self, event: cc_dump.pipeline.event_types.PipelineEvent) -> str:
        """Extract provider from event. Empty provider is a hard error.

        // [LAW:single-enforcer] Provider is stamped at the proxy boundary and
        // never inferred or defaulted downstream.
        """
        if not event.provider:
            raise ValueError(
                f"Event {type(event).__name__} has {'empty string' if event.provider == '' else 'missing/None'}"
                f" provider (request_id={event.request_id!r})"
            )
        return event.provider

    def _provider_tab_key(self, provider: str) -> str:
        """Map provider to its tab's session key.

        // [LAW:one-source-of-truth] Provider → tab key mapping lives here.
        """
        return cc_dump.providers.provider_session_key(
            provider,
        )

    def _resolve_default_provider_session_key(self, event) -> str:
        request_id = str(getattr(event, "request_id", "") or "")
        session_key = self._default_session_key
        if event.kind == cc_dump.pipeline.event_types.PipelineEventKind.REQUEST:
            body = getattr(event, "body", {})
            if isinstance(body, dict) and cc_dump.ai.side_channel_marker.extract_marker(body):
                # [LAW:one-type-per-behavior] Workbench AI traffic is one inspectable lane.
                session_key = self._workbench_session_key
        elif request_id:
            session_key = self._request_session_keys.get(request_id, session_key)
        self._bind_request_session(request_id, session_key)
        self._ensure_session_surface(session_key)
        return session_key

    def _track_request_activity(self, request_id: str) -> None:
        if not request_id:
            return
        resolved_key = self._session_key_for_request_id(request_id)
        self._ensure_session_surface(resolved_key)
        per_session = self._app_state.get("last_message_time_by_session", {})
        if not isinstance(per_session, dict):
            per_session = {}
        per_session[resolved_key] = time.monotonic()
        self._app_state["last_message_time_by_session"] = per_session
        self._bump_view_store_revision("session:revision")

    def _bump_view_store_revision(self, key: str) -> None:
        raw = self._view_store.get(key)
        current = int(raw) if isinstance(raw, int) else 0
        self._view_store.set(key, current + 1)

    def _sync_detected_session(self, state: dict[str, object]) -> None:
        # // [LAW:one-source-of-truth] Session ID comes from formatting state,
        # not from blocks or app_state side-channels.
        current_session = state.get("current_session", "")
        current_session = current_session if isinstance(current_session, str) else ""
        if not current_session or current_session == self._session_id:
            return
        self._app_log("INFO", f"Session detected: {current_session}")
        self._session_id = current_session
        self._bump_view_store_revision("session:revision")
        self.post_message(NewSession(current_session))
        self.notify(f"New session: {current_session[:8]}...")
        info = self._get_info()
        if info is not None:
            info.update_info(self._build_server_info())

    def _resolve_event_session_key(self, event, *, provider: str | None = None) -> str:
        """Resolve session key for event routing.

        // [LAW:one-source-of-truth] request_id -> session routing is resolved once here.
        // Provider determines the tab. One tab per provider instance.
        // Session identity preserved on blocks (block.session_id) and in
        // formatting state (state["current_session"]), not in tab routing.
        """
        resolved_provider = provider or self._resolve_event_provider(event)
        provider_key = self._provider_tab_key(resolved_provider)
        if resolved_provider != cc_dump.providers.DEFAULT_PROVIDER_KEY:
            self._bind_request_session(event.request_id, provider_key)
            self._ensure_session_surface(provider_key)
            return provider_key
        return self._resolve_default_provider_session_key(event)

    def _get_active_session_panel_state(self) -> tuple[str | None, float | None]:
        """Return session panel identity + last activity for active tab context."""
        active_key = self._active_session_key_from_tabs()
        per_session = self._app_state.get("last_message_time_by_session", {})
        last_message_time = None
        if isinstance(per_session, dict):
            raw_time = per_session.get(active_key)
            if isinstance(raw_time, (int, float)):
                last_message_time = float(raw_time)
        if active_key != self._default_session_key:
            return active_key, last_message_time
        return self._session_id, last_message_time

    def _publish_session_panel_state(self) -> None:
        """Publish canonical session panel projection to the view store.

        // [LAW:one-source-of-truth] Session panel state is derived once at app boundary.
        // [LAW:single-enforcer] Only this method writes panel:session_state.
        """
        session_id, last_message_time = self._get_active_session_panel_state()
        self._view_store.set(
            "panel:session_state",
            {
                "session_id": session_id,
                "last_message_time": last_message_time,
            },
        )

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
        if self._launch_configs_cache is None:
            self._launch_configs_cache = cc_dump.app.launch_config.load_configs()
        for config in self._launch_configs_cache:
            # [LAW:one-source-of-truth] Preset list comes from persisted launch configs.
            title = "Launch preset: {}".format(config.name)
            description = "{} via {}".format(config.launcher, config.resolved_command)
            yield SystemCommand(
                title,
                description,
                lambda c=config: self._launch_with_config(
                    c, log_label="palette_launch:{}".format(c.name)
                ),
            )

    def compose(self) -> ComposeResult:
        yield Header()

        # [LAW:one-source-of-truth] Cycling panels from registry
        for spec in cc_dump.tui.panel_registry.PANEL_REGISTRY:
            widget = _resolve_factory(spec.factory)()
            widget.id = self._panel_ids[spec.name]
            yield widget

        with TabbedContent(id=self._conv_tabs_id):
            with TabPane("Claude", id=self._conv_tab_main_id):
                conv = cc_dump.tui.widget_factory.create_conversation_view(
                    view_store=self._view_store,
                    domain_store=self._domain_store,
                    runtime=self._render_runtime,
                )
                conv.id = self._conv_id
                yield conv
            with TabPane("Workbench", id=self._workbench_tab_id):
                results = cc_dump.tui.workbench_results_view.create_workbench_results_view()
                results.id = self._workbench_view_id
                yield results

        logs = cc_dump.tui.widget_factory.create_logs_panel()
        logs.id = self._logs_id
        logs.display = bool(self._view_store.get("panel:logs"))
        yield logs

        info = cc_dump.tui.info_panel.create_info_panel()
        info.id = self._info_id
        info.display = bool(self._view_store.get("panel:info"))
        yield info

        settings_panel = cc_dump.tui.settings_panel.create_settings_panel(
            _settings_launch.initial_settings_values(self)
        )
        settings_panel.display = False
        yield settings_panel

        launch_panel = cc_dump.tui.launch_config_panel.create_launch_config_panel(
            cc_dump.app.launch_config.load_configs(),
            cc_dump.app.launch_config.load_active_name(),
        )
        launch_panel.display = False
        yield launch_panel

        side_channel_panel = cc_dump.tui.side_channel_panel.create_side_channel_panel()
        side_channel_panel.display = False
        yield side_channel_panel

        search_bar = cc_dump.tui.search.SearchBar()
        search_bar.id = self._search_bar_id
        yield search_bar

        yield cc_dump.tui.custom_footer.StatusFooter()

    def on_mount(self):
        _lifecycle.on_mount(self)
        self._execute_auto_launch()

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

        old_disposers = getattr(self._view_store, "_reaction_disposers", None)
        if isinstance(old_disposers, list):
            self._dispose_reaction_handles(old_disposers)

        self._view_store._reaction_disposers = cc_dump.app.view_store.setup_reactions(
            self._view_store, ctx
        )

    def _dispose_reaction_handles(self, disposers: list[object]) -> None:
        """Dispose reaction handles that expose either .dispose() or callable teardown."""
        for handle in disposers:
            disposer = getattr(handle, "dispose", None)
            if callable(disposer):
                try:
                    disposer()
                except Exception:
                    pass
                continue
            if callable(handle):
                try:
                    handle()
                except Exception:
                    pass

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
        exc_item = cc_dump.app.error_models.ErrorItem(
            id=f"exc-{id(error)}",
            icon="💥",
            summary=f"{type(error).__name__}: {error}"
        )
        self._view_store.exception_items.append(exc_item)

        # DON'T call super() - keep running, hot reload will fix it

    # ─── Helpers ───────────────────────────────────────────────────────

    def _app_log(self, level: str, message: str, persist_to_file: bool = True):
        if level == "ERROR":
            self._error_log.append(f"[{level}] {message}")
        if self.is_running:
            logs = self._get_logs()
            if logs is not None:
                logs.app_log(level, message)
        if persist_to_file:
            level_num = getattr(logging, level, logging.INFO)
            logger.log(level_num, message, extra={"cc_dump_in_app": True})

    def _tmux_store_projection(self, tmux) -> dict[str, bool]:
        """Compute footer-facing tmux availability flag from controller state."""
        _TMUX_ACTIVE = {cc_dump.app.tmux_controller.TmuxState.READY, cc_dump.app.tmux_controller.TmuxState.TOOL_RUNNING}
        if tmux is None:
            return {
                "tmux:available": False,
            }
        return {
            "tmux:available": tmux.state in _TMUX_ACTIVE,
        }

    def _sync_tmux_to_store(self):
        """Mirror tmux controller state to view store for reactive footer updates."""
        self._view_store.update(self._tmux_store_projection(self._tmux_controller))

    def _sync_active_launch_config_state(self) -> None:
        """Mirror active launch config identity to view-store footer keys."""
        active = cc_dump.app.launch_config.get_active_config()
        self._view_store.update(
            {
                "launch:active_name": active.name,
                "launch:active_tool": active.launcher,
            }
        )

    def _build_server_info(self) -> dict:
        """// [LAW:one-source-of-truth] All server info derived from constructor params."""
        default_endpoint = self._provider_endpoints.get(
            cc_dump.providers.DEFAULT_PROVIDER_KEY
        )
        proxy_url = (
            default_endpoint.proxy_url
            if default_endpoint is not None and default_endpoint.proxy_url
            else "http://{}:{}".format(self._host, self._port)
        )
        primary_target = default_endpoint.target if default_endpoint is not None else None
        provider_modes: list[str] = []

        provider_rows: list[dict[str, str]] = []
        for spec in cc_dump.providers.all_provider_specs():
            endpoint = self._provider_endpoints.get(spec.key)
            if endpoint is None:
                continue
            provider_modes.append(endpoint.proxy_mode)
            provider_rows.append(
                {
                    "key": spec.key,
                    "name": spec.display_name,
                    "proxy_url": endpoint.proxy_url,
                    "target": endpoint.target or "",
                    "proxy_mode": endpoint.proxy_mode,
                    "base_url_env": spec.base_url_env,
                    "client_hint": spec.client_hint,
                }
            )
        unique_modes = set(provider_modes)
        proxy_mode = provider_modes[0] if len(unique_modes) == 1 and provider_modes else "mixed"

        info = {
            "proxy_url": proxy_url,
            "proxy_mode": proxy_mode,
            "target": primary_target,
            "providers": provider_rows,
            "session_id": self._session_id,
            "recording_path": self._recording_path,
            "recording_dir": cc_dump.io.sessions.get_recordings_dir(),
            "replay_file": self._replay_file,
            "python_version": sys.version.split()[0],
            "textual_version": textual.__version__,
            "pid": os.getpid(),
        }
        runtime_log = cc_dump.io.logging_setup.get_runtime()
        info["log_file"] = runtime_log.file_path if runtime_log is not None else None
        return info

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

        try:
            for (
                req_headers,
                req_body,
                resp_status,
                resp_headers,
                complete_message,
                provider,
            ) in self._replay_data:
                try:
                    # // [LAW:one-source-of-truth] Replay uses the same event pipeline as live.
                    events = cc_dump.pipeline.har_replayer.convert_to_events(
                        req_headers, req_body, resp_status, resp_headers, complete_message,
                        provider=provider,
                    )
                    for event in events:
                        self._handle_event(event)
                except Exception as e:
                    self._app_log("ERROR", f"Error processing replay pair: {e}")

            self._app_log(
                "INFO",
                f"Replay complete: {self._total_request_count()} requests processed",
            )
        except Exception as e:
            self._app_log("ERROR", f"Fatal error in replay processing: {e}")
        finally:
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
        provider = self._resolve_event_provider(event)
        state = self._provider_state(provider)
        session_key = self._resolve_event_session_key(event, provider=provider)
        conv = self._get_conv(session_key=session_key)
        if conv is None:
            conv = self._query_safe("#" + self._conv_id)
        if conv is None:
            return
        domain_store = self._get_domain_store(session_key)

        # [LAW:dataflow-not-control-flow] Unified context dict
        widgets = {
            "conv": conv,
            "filters": self.active_filters,
            "view_store": self._view_store,
            "domain_store": domain_store,
            "analytics_store": self._analytics_store,
        }

        # [LAW:dataflow-not-control-flow] Always call handler, use no-op for unknown
        handler = cast(
            cc_dump.tui.event_handlers.EventHandler,
            cc_dump.tui.event_handlers.EVENT_HANDLERS.get(
                kind, cc_dump.tui.event_handlers._noop
            ),
        )
        self._app_state = cast(
            AppState,
            handler(event, state, widgets, self._app_state, self._app_log),
        )
        self._track_request_activity(str(getattr(event, "request_id", "") or ""))
        self._sync_detected_session(state)

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
        self._bump_view_store_revision("session:revision")
        # // [LAW:one-source-of-truth] Back-compat alias points to active session store.
        self._domain_store = self._get_active_domain_store()

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

    # Session navigation
    def action_next_session(self):
        _actions.next_session(self)

    def action_prev_session(self):
        _actions.prev_session(self)

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

    def action_toggle_analytics(self, category: str):
        _actions.toggle_analytics(self, category)

    def action_toggle_expand(self, category: str):
        self.action_toggle_analytics(category)

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
    def action_launch_tool(self):
        config = cc_dump.app.launch_config.get_active_config()
        self._launch_with_config(config, log_label="launch_tool")

    def action_open_tmux_log_tail(self):
        tmux = self._tmux_controller
        if tmux is None:
            self.notify("Tmux not available", severity="warning")
            return
        runtime_log = cc_dump.io.logging_setup.get_runtime()
        log_file = runtime_log.file_path if runtime_log is not None else ""
        if not log_file:
            self.notify("Runtime log file unavailable", severity="error")
            return
        result = tmux.open_log_tail(log_file)
        self._app_log("INFO", "open_log_tail: {}".format(result))
        if result.success:
            self.notify("{}: {}".format(result.action.value, result.detail))
        else:
            self.notify("Tail failed: {}".format(result.detail), severity="error")

    def action_copy_log_path(self):
        runtime_log = cc_dump.io.logging_setup.get_runtime()
        log_path = runtime_log.file_path if runtime_log is not None else ""
        if not log_path:
            self.notify("Log file unavailable", severity="error")
            return
        self.copy_to_clipboard(log_path)
        self.notify(f"Copied: {log_path}")

    # Settings
    def action_toggle_settings(self):
        _actions.toggle_settings(self)

    def action_toggle_debug_settings(self):
        _actions.toggle_debug_settings(self)

    def _open_settings(self):
        _settings_launch.open_settings(self)

    def _close_settings(self) -> None:
        _settings_launch.close_settings(self)

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
        _settings_launch.open_launch_config(self)

    def _close_launch_config(self) -> None:
        _settings_launch.close_launch_config(self)

    def _execute_auto_launch(self) -> None:
        """Execute auto-launch from the CLI 'run' subcommand.

        // [LAW:dataflow-not-control-flow] Config resolution and extra-args merging
        // are data transformations; launch outcome determined by result values.
        """
        config_name = self._auto_launch_config
        if config_name is None:
            return
        configs = cc_dump.app.launch_config.load_configs()
        by_name = {c.name: c for c in configs}
        config = by_name.get(config_name)
        if config is None:
            available = ", ".join(c.name for c in configs)
            self.notify(
                "Unknown config '{}'. Available: {}".format(config_name, available),
                severity="error",
                timeout=10,
            )
            self._app_log("ERROR", "auto-launch: config '{}' not found".format(config_name))
            return
        merged = cc_dump.app.launch_config.config_with_extra_args(
            config, self._auto_launch_extra_args
        )
        extra_desc = " + {}".format(" ".join(self._auto_launch_extra_args)) if self._auto_launch_extra_args else ""
        self._app_log("INFO", "auto-launching '{}'{}".format(config_name, extra_desc))
        self._launch_with_config(merged, log_label="auto_launch:{}".format(config_name))

    def _launch_with_config(self, config, log_label: str = "launch_with_config") -> None:
        """Build args from config + session_id, launch via tmux."""
        _settings_launch.launch_with_config(self, config, log_label=log_label)

    def _save_launch_configs(self, configs: list, active_name: str) -> None:
        """Persist configs and active name, invalidating the command palette cache."""
        normalized = cc_dump.app.launch_config.save_configs(configs)
        # Reconcile active name against post-normalization names.
        normalized_names = {c.name for c in normalized}
        safe_name = active_name if active_name in normalized_names else (
            normalized[0].name if normalized else active_name
        )
        cc_dump.app.launch_config.save_active_name(safe_name)
        self._launch_configs_cache = normalized

    def on_launch_config_panel_saved(self, msg) -> None:
        """Handle LaunchConfigPanel.Saved — persist configs."""
        self._save_launch_configs(msg.configs, msg.active_name)
        self._sync_active_launch_config_state()
        self._close_launch_config()
        self.notify("Launch configs saved")

    def on_launch_config_panel_cancelled(self, msg) -> None:
        """Handle LaunchConfigPanel.Cancelled — close without saving."""
        self._close_launch_config()

    def on_launch_config_panel_quick_launch(self, msg) -> None:
        """Handle LaunchConfigPanel.QuickLaunch — save, close, launch."""
        self._save_launch_configs(msg.configs, msg.active_name)
        self._sync_active_launch_config_state()
        self._close_launch_config()
        self._launch_with_config(msg.config, log_label="quick_launch")

    def on_launch_config_panel_activated(self, msg) -> None:
        """Handle LaunchConfigPanel.Activated — save active name, notify."""
        self._save_launch_configs(msg.configs, msg.name)
        self._sync_active_launch_config_state()
        self.notify("Active: {}".format(msg.name))

    # Side channel
    def action_toggle_side_channel(self):
        _actions.toggle_side_channel(self)

    def _open_side_channel(self):
        _side_channel.open_side_channel(self)

    def _close_side_channel(self):
        _side_channel.close_side_channel(self)

    def action_sc_qa_estimate(self) -> None:
        _side_channel.action_sc_qa_estimate(self)

    def action_sc_qa_submit(self) -> None:
        _side_channel.action_sc_qa_submit(self)

    def _on_side_channel_qa_result(self, result, question: str, context_session_key: str) -> None:
        _side_channel.on_side_channel_qa_result(self, result, question, context_session_key)

    def action_sc_utility_run(self) -> None:
        _side_channel.action_sc_utility_run(self)

    def _on_side_channel_utility_result(self, result, context_session_key: str) -> None:
        _side_channel.on_side_channel_utility_result(self, result, context_session_key)

    def action_sc_preview_qa(self) -> None:
        _side_channel.action_sc_preview_qa(self)

    def action_sc_preview_handoff(self) -> None:
        _side_channel.action_sc_preview_handoff(self)

    def action_sc_preview_utilities(self) -> None:
        _side_channel.action_sc_preview_utilities(self)

    # Navigation
    def action_toggle_follow(self):
        _actions.toggle_follow(self)

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

    # Search
    def _start_search(self):
        _search.start_search(self)

    def _handle_search_editing_key(self, event):
        _search.handle_search_editing_key(self, event)

    def _handle_search_nav_special_keys(self, event) -> bool:
        return _search.handle_search_nav_special_keys(self, event)

    # ─── Reactive watchers ─────────────────────────────────────────────

    def _sync_panel_display(self, active: str):
        """// [LAW:one-source-of-truth] Panel visibility driven by panel registry order."""
        for name in cc_dump.tui.panel_registry.PANEL_ORDER:
            widget = self._get_panel(name)
            if widget is not None:
                widget.display = (name == active)

    def _sync_chrome_panels(self, state: tuple[bool, bool]) -> None:
        """Sync logs/info visibility from canonical view-store projection."""
        logs_visible, info_visible = state
        logs = self._get_logs()
        if logs is not None:
            logs.display = bool(logs_visible)
        info = self._get_info()
        if info is not None:
            info.display = bool(info_visible)

    def _sync_sidebar_panels(self, state: tuple[bool, bool, bool]) -> None:
        """Single enforcer for sidebar visibility + focus."""
        settings_open, launch_open, side_open = state
        def _first_or_none(panel_type):
            try:
                return self.screen.query(panel_type).first()
            except NoMatches:
                return None

        settings_panel = _first_or_none(cc_dump.tui.settings_panel.SettingsPanel)
        launch_panel = _first_or_none(cc_dump.tui.launch_config_panel.LaunchConfigPanel)
        side_panel = _first_or_none(cc_dump.tui.side_channel_panel.SideChannelPanel)

        if settings_panel is not None:
            settings_panel.display = settings_open
        if launch_panel is not None:
            launch_panel.display = launch_open
        if side_panel is not None:
            side_panel.display = side_open

        focus_target = None
        if side_open:
            focus_target = side_panel
        elif launch_open:
            focus_target = launch_panel
        elif settings_open:
            focus_target = settings_panel
        if focus_target is not None:
            focus_default = getattr(focus_target, "focus_default_control", None)
            if callable(focus_default):
                self.call_after_refresh(focus_default)
        else:
            conv = self._get_conv()
            if conv is not None:
                self.call_after_refresh(conv.focus)

    def _sync_aux_panels(self, state: tuple[bool, bool]) -> None:
        """Sync auxiliary overlays from canonical store flags."""
        keys_visible, debug_visible = state
        # [LAW:single-enforcer] Keep one mounted KeysPanel and let its reaction own visibility.
        self._ensure_panel_mounted(
            panel_type=cc_dump.tui.keys_panel.KeysPanel,
            create_panel=cc_dump.tui.keys_panel.create_keys_panel,
        )
        self._sync_optional_panel(
            panel_type=cc_dump.tui.debug_settings_panel.DebugSettingsPanel,
            visible=debug_visible,
            create_panel=lambda: cc_dump.tui.debug_settings_panel.create_debug_settings_panel(app_ref=self),
            on_hidden=self._focus_active_conversation,
        )

    def _ensure_panel_mounted(
        self,
        *,
        panel_type: type[Widget],
        create_panel: Callable[[], Widget],
    ) -> None:
        """Mount a panel if missing, without altering its display state."""
        panels: list[Widget] = list(self.screen.query(panel_type))
        if not panels:
            self.screen.mount(create_panel())

    def _sync_optional_panel(
        self,
        *,
        panel_type: type[Widget],
        visible: bool,
        create_panel: Callable[[], Widget],
        on_hidden: Callable[[], None] | None = None,
    ) -> None:
        """Sync optional overlay panel presence to a boolean visibility flag."""
        panels: list[Widget] = list(self.screen.query(panel_type))
        if visible:
            if not panels:
                self.screen.mount(create_panel())
            return
        if panels:
            for panel in panels:
                panel.remove()
            if on_hidden is not None:
                on_hidden()

    def _focus_active_conversation(self) -> None:
        conv = self._get_conv()
        if conv is not None:
            conv.focus()

    def _sync_error_items(self, items: list[cc_dump.app.error_models.ErrorItem]) -> None:
        """Project canonical error items to the active conversation indicator."""
        conv = self._get_conv()
        if conv is None:
            return
        ErrorItem = cc_dump.tui.error_indicator.ErrorItem
        conv.update_error_items(
            [
                ErrorItem(
                    str(item.id),
                    str(item.icon),
                    str(item.summary),
                )
                for item in items
            ]
        )

    def watch_theme(self, theme_name: str) -> None:
        if not stx.is_safe(self):
            return
        cc_dump.tui.rendering.set_theme(self.current_theme, runtime=self._render_runtime)
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

    def _handle_pre_keymap_event(self, event, mode) -> bool:
        InputMode = cc_dump.tui.input_modes.InputMode

        if mode == InputMode.SEARCH_EDIT:
            event.prevent_default()
            self._handle_search_editing_key(event)
            return True
        if mode == InputMode.SEARCH_NAV and self._handle_search_nav_special_keys(event):
            event.prevent_default()
            return True
        if event.key == "escape" and self._close_topmost_panel():
            event.prevent_default()
            return True
        if _event_key_is_consumed(event, _resolve_key_consumer(self.screen.focused)):
            return True
        if mode == InputMode.NORMAL and event.character == "/":
            event.prevent_default()
            self._start_search()
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
        if self._handle_pre_keymap_event(event, mode):
            return

        keymap = MODE_KEYMAP.get(mode, MODE_KEYMAP[InputMode.NORMAL])
        action_name = keymap.get(event.key)
        if action_name:
            event.prevent_default()
            await self.run_action(action_name)
