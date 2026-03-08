"""View store — category visibility + panel/follow + footer/error/side-channel state. RELOADABLE.

// [LAW:one-source-of-truth] Schema derived from CATEGORY_CONFIG + panel/follow + footer/error/sc keys.
// [LAW:single-enforcer] Single autorun triggers re-render on any visibility change.
// [LAW:single-enforcer] Single reaction per widget push (panel, footer, error, side-channel).
// [LAW:one-way-deps] No widget imports — push callbacks provided via context (see view_store_bridge).
"""

from cc_dump.core.formatting import VisState
from cc_dump.app.error_models import ErrorItem
from cc_dump.core.coerce import coerce_int

from cc_dump.tui.category_config import CATEGORY_CONFIG
from snarfx.hot_reload import HotReloadStore
from snarfx import computed, ObservableList
from snarfx import textual as stx


# [LAW:one-source-of-truth] Schema built programmatically from CATEGORY_CONFIG + panel/follow
SCHEMA: dict[str, object] = {}
for _key, _name, _desc, _default in CATEGORY_CONFIG:
    SCHEMA[f"vis:{_name}"] = _default.visible
    SCHEMA[f"full:{_name}"] = _default.full
    SCHEMA[f"exp:{_name}"] = _default.expanded

# Panel and follow state — survives hot-reload via reconcile
SCHEMA["panel:active"] = "session"
SCHEMA["panel:side_channel"] = False
SCHEMA["panel:settings"] = False
SCHEMA["panel:launch_config"] = False
SCHEMA["panel:logs"] = False
SCHEMA["panel:info"] = False
SCHEMA["panel:keys"] = False
SCHEMA["panel:debug_settings"] = False
# // [LAW:one-source-of-truth] String, not FollowState enum — enum class identity
# changes on reload; string comparison is stable across reloads.
SCHEMA["nav:follow"] = "active"

# Footer inputs (previously app attributes or external reads)
SCHEMA["filter:active"] = "1"               # str|None — default to F1 (Conversation)
SCHEMA["tmux:available"] = False            # bool — mirrored from tmux controller
SCHEMA["launch:active_name"] = ""           # str — was load_active_name() file I/O each call
SCHEMA["launch:active_tool"] = "claude"     # str — active launcher key for footer chip label
SCHEMA["theme:generation"] = 0              # int — bumped on theme change to invalidate footer

# Side-channel panel state (previously app._side_channel_* attributes)
SCHEMA["sc:loading"] = False
SCHEMA["sc:active_action"] = ""
SCHEMA["sc:result_text"] = ""
SCHEMA["sc:result_source"] = ""
SCHEMA["sc:result_elapsed_ms"] = 0
SCHEMA["sc:purpose_usage"] = {}
SCHEMA["settings:side_channel_enabled"] = False

# Workbench results projection state (canonical source for results tab rendering)
SCHEMA["workbench:text"] = ""
SCHEMA["workbench:source"] = ""
SCHEMA["workbench:elapsed_ms"] = 0
SCHEMA["workbench:action"] = ""
SCHEMA["workbench:context_session_id"] = ""

# Search identity state — survives hot-reload via reconcile
# // [LAW:one-source-of-truth] String, not SearchPhase enum — stable across reloads.
SCHEMA["search:phase"] = "inactive"
SCHEMA["search:query"] = ""
SCHEMA["search:modes"] = 13    # CASE_INSENSITIVE(1) | REGEX(4) | INCREMENTAL(8)
SCHEMA["search:cursor_pos"] = 0
SCHEMA["search:current_index"] = 0
SCHEMA["search:match_count"] = 0


def create():
    """Create view store with defaults from CATEGORY_CONFIG."""
    store = HotReloadStore(SCHEMA)

    # [LAW:one-source-of-truth] Computed assembles VisState dict from 18 observables.
    # Lives on the store object — survives reconcile (reads via stable store.get()).
    @computed
    def active_filters():
        return {
            name: VisState(
                store.get(f"vis:{name}"),
                store.get(f"full:{name}"),
                store.get(f"exp:{name}"),
            )
            for _, name, _, _ in CATEGORY_CONFIG
        }

    store.active_filters = active_filters

    # ObservableLists — tracked by SnarfX auto-tracking in Computeds
    store.stale_files = ObservableList()       # list[str] — was app._stale_files
    store.exception_items = ObservableList()   # list[ErrorItem] — was app._exception_items

    # // [LAW:single-enforcer] footer_state Computed reads all footer inputs from store.
    # Returns plain types — bridge converts to widget-specific types (FollowState).
    @computed
    def footer_state():
        return {
            **store.active_filters.get(),
            "active_panel": store.get("panel:active"),
            "follow_state": store.get("nav:follow"),
            "active_filterset": store.get("filter:active"),
            "tmux_available": store.get("tmux:available"),
            "active_launch_config_name": store.get("launch:active_name"),
            "active_launch_tool": store.get("launch:active_tool"),
            "_gen": store.get("theme:generation"),
        }

    store.footer_state = footer_state

    @computed
    def sidebar_panel_state():
        # [LAW:one-source-of-truth] Sidebar visibility tuple is derived from panel:* keys once.
        return (
            bool(store.get("panel:settings")),
            bool(store.get("panel:launch_config")),
            bool(store.get("panel:side_channel")),
        )

    store.sidebar_panel_state = sidebar_panel_state

    @computed
    def chrome_panel_state():
        # [LAW:one-source-of-truth] Logs/info visibility is derived from panel:* keys once.
        return (
            bool(store.get("panel:logs")),
            bool(store.get("panel:info")),
        )

    store.chrome_panel_state = chrome_panel_state

    @computed
    def aux_panel_state():
        # [LAW:one-source-of-truth] Keys/debug overlay visibility is derived from panel:* keys once.
        return (
            bool(store.get("panel:keys")),
            bool(store.get("panel:debug_settings")),
        )

    store.aux_panel_state = aux_panel_state

    # // [LAW:single-enforcer] error_items Computed combines stale files + exceptions.
    @computed
    def error_items():
        items = [ErrorItem("stale", "\u274c", s.split("/")[-1]) for s in store.stale_files]
        items.extend(store.exception_items)
        return items

    store.error_items = error_items

    # // [LAW:single-enforcer] sc_panel_state Computed combines side-channel fields.
    # Returns plain dict — bridge converts to SideChannelPanelState.
    @computed
    def sc_panel_state():
        return {
            "enabled": bool(store.get("settings:side_channel_enabled")),
            "loading": store.get("sc:loading"),
            "active_action": store.get("sc:active_action"),
            "result_text": store.get("sc:result_text"),
            "result_source": store.get("sc:result_source"),
            "result_elapsed_ms": store.get("sc:result_elapsed_ms"),
            "purpose_usage": store.get("sc:purpose_usage"),
        }

    store.sc_panel_state = sc_panel_state

    @computed
    def workbench_state():
        # [LAW:one-source-of-truth] Workbench result rendering is derived from canonical store keys.
        return {
            "text": str(store.get("workbench:text")),
            "source": str(store.get("workbench:source")),
            "elapsed_ms": coerce_int(store.get("workbench:elapsed_ms"), 0),
            "action": str(store.get("workbench:action")),
            "context_session_id": str(store.get("workbench:context_session_id")),
        }

    store.workbench_state = workbench_state

    @computed
    def search_ui_state():
        # [LAW:single-enforcer] Search bar + footer visibility projection is centralized here.
        phase = str(store.get("search:phase"))
        return {
            "phase": phase,
            "query": str(store.get("search:query")),
            "modes": coerce_int(store.get("search:modes"), 13),
            "cursor_pos": coerce_int(store.get("search:cursor_pos"), 0),
            "current_index": coerce_int(store.get("search:current_index"), 0),
            "match_count": coerce_int(store.get("search:match_count"), 0),
            # [LAW:dataflow-not-control-flow] Footer visibility is a derived value from search phase.
            "footer_visible": phase == "inactive",
        }

    store.search_ui_state = search_ui_state

    return store


def setup_reactions(store, context=None):
    """Register reactions. Returns list of disposers.

    Called on create and on hot-reload reconcile.
    context: dict with "app" and push callbacks from bridge.

    // [LAW:single-enforcer] All guards (pause, NoMatches, thread-marshal) enforced by stx.
    // [LAW:one-way-deps] Push callbacks provided by caller, not imported here.
    """
    disposers = []

    if context:
        app = context.get("app")
        if app is not None:
            disposers.append(stx.autorun(app,
                lambda: (store.active_filters.get(), app._rerender_if_mounted())
            ))

            # // [LAW:single-enforcer] Callback-based reactions — bridge provides push functions.
            for key, data_fn in [
                ("push_panel_change", lambda: store.get("panel:active")),
                ("push_sidebar_state", lambda: store.sidebar_panel_state.get()),
                ("push_chrome_panels", lambda: store.chrome_panel_state.get()),
                ("push_aux_panels", lambda: store.aux_panel_state.get()),
                ("push_errors", lambda: store.error_items.get()),
                ("push_sc_panel", lambda: store.sc_panel_state.get()),
                ("push_workbench", lambda: store.workbench_state.get()),
                ("push_search_ui", lambda: store.search_ui_state.get()),
            ]:
                cb = context.get(key)
                if cb:
                    disposers.append(stx.reaction(app, data_fn, cb))

    return disposers


def get_category_state(store, name: str) -> VisState:
    """Read 3 keys, return VisState for a category."""
    return VisState(
        store.get(f"vis:{name}"),
        store.get(f"full:{name}"),
        store.get(f"exp:{name}"),
    )
