"""View store — category visibility + panel/follow + footer/error/side-channel state. RELOADABLE.

// [LAW:one-source-of-truth] Schema derived from CATEGORY_CONFIG + panel/follow + footer/error/sc keys.
// [LAW:one-way-deps] App/tui layers subscribe to this store; this module owns only data.
"""

from dataclasses import dataclass

from cc_dump.core.formatting import VisState
from cc_dump.app.error_models import ErrorItem
from cc_dump.core.coerce import coerce_int

from cc_dump.tui.category_config import CATEGORY_CONFIG
from snarfx.hot_reload import HotReloadStore
from snarfx import computed, ObservableList


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


@dataclass(frozen=True)
class SideChannelPanelProjection:
    enabled: bool
    loading: bool
    active_action: str
    result_text: str
    result_source: str
    result_elapsed_ms: int


@dataclass(frozen=True)
class WorkbenchProjection:
    text: str
    source: str
    elapsed_ms: int
    action: str
    context_session_id: str


@dataclass(frozen=True)
class SearchUiProjection:
    phase: str
    query: str
    modes: int
    cursor_pos: int
    current_index: int
    match_count: int
    footer_visible: bool


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
    # Returns plain types — footer widget performs local enum adaptation.
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

    # // [LAW:single-enforcer] error_items Computed combines stale files + exceptions.
    @computed
    def error_items():
        items = [ErrorItem("stale", "\u274c", s.split("/")[-1]) for s in store.stale_files]
        items.extend(store.exception_items)
        return items

    store.error_items = error_items

    # // [LAW:single-enforcer] sc_panel_state Computed combines side-channel fields.
    # SideChannelPanel adapts this projection to its local dataclass.
    @computed
    def sc_panel_state():
        return SideChannelPanelProjection(
            enabled=bool(store.get("settings:side_channel_enabled")),
            loading=bool(store.get("sc:loading")),
            active_action=str(store.get("sc:active_action")),
            result_text=str(store.get("sc:result_text")),
            result_source=str(store.get("sc:result_source")),
            result_elapsed_ms=coerce_int(store.get("sc:result_elapsed_ms"), 0),
        )

    store.sc_panel_state = sc_panel_state

    @computed
    def workbench_state():
        # [LAW:one-source-of-truth] Workbench result rendering is derived from canonical store keys.
        return WorkbenchProjection(
            text=str(store.get("workbench:text")),
            source=str(store.get("workbench:source")),
            elapsed_ms=coerce_int(store.get("workbench:elapsed_ms"), 0),
            action=str(store.get("workbench:action")),
            context_session_id=str(store.get("workbench:context_session_id")),
        )

    store.workbench_state = workbench_state

    @computed
    def search_ui_state():
        # [LAW:single-enforcer] Search bar + footer visibility projection is centralized here.
        phase = str(store.get("search:phase"))
        return SearchUiProjection(
            phase=phase,
            query=str(store.get("search:query")),
            modes=coerce_int(store.get("search:modes"), 13),
            cursor_pos=coerce_int(store.get("search:cursor_pos"), 0),
            current_index=coerce_int(store.get("search:current_index"), 0),
            match_count=coerce_int(store.get("search:match_count"), 0),
            # [LAW:dataflow-not-control-flow] Footer visibility is a derived value from search phase.
            footer_visible=phase == "inactive",
        )

    store.search_ui_state = search_ui_state

    return store


def get_category_state(store, name: str) -> VisState:
    """Read 3 keys, return VisState for a category."""
    return VisState(
        store.get(f"vis:{name}"),
        store.get(f"full:{name}"),
        store.get(f"exp:{name}"),
    )
