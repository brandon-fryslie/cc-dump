"""View store — category visibility + panel/follow + footer/error/side-channel state. RELOADABLE.

// [LAW:one-source-of-truth] Schema derived from CATEGORY_CONFIG + panel/follow + footer/error/sc keys.
// [LAW:single-enforcer] Single autorun triggers re-render on any visibility change.
// [LAW:single-enforcer] Single reaction per widget push (panel, footer, error, side-channel).
// [LAW:one-way-deps] No widget imports — push callbacks provided via context (see view_store_bridge).
"""

import cc_dump.formatting
import cc_dump.tui.error_indicator

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
# // [LAW:one-source-of-truth] String, not FollowState enum — enum class identity
# changes on reload; string comparison is stable across reloads.
SCHEMA["nav:follow"] = "active"

# Footer inputs (previously app attributes or external reads)
SCHEMA["filter:active"] = None              # str|None — was app._active_filterset_slot
SCHEMA["tmux:available"] = False            # bool — mirrored from tmux controller
SCHEMA["tmux:auto_zoom"] = False            # bool — mirrored from tmux controller
SCHEMA["tmux:zoomed"] = False               # bool — mirrored from tmux controller
SCHEMA["launch:active_name"] = ""           # str — was load_active_name() file I/O each call
SCHEMA["theme:generation"] = 0              # int — bumped on theme change to invalidate footer
SCHEMA["streams:active"] = ()               # tuple[(request_id, label, kind), ...]
SCHEMA["streams:focused"] = ""              # request_id of focused active stream
SCHEMA["streams:view"] = "focused"          # "focused" | "lanes"

# Side-channel panel state (previously app._side_channel_* attributes)
SCHEMA["sc:loading"] = False
SCHEMA["sc:result_text"] = ""
SCHEMA["sc:result_source"] = ""
SCHEMA["sc:result_elapsed_ms"] = 0

# Search identity state — survives hot-reload via reconcile
# // [LAW:one-source-of-truth] String, not SearchPhase enum — stable across reloads.
SCHEMA["search:phase"] = "inactive"
SCHEMA["search:query"] = ""
SCHEMA["search:modes"] = 13    # CASE_INSENSITIVE(1) | REGEX(4) | INCREMENTAL(8)
SCHEMA["search:cursor_pos"] = 0


def create():
    """Create view store with defaults from CATEGORY_CONFIG."""
    store = HotReloadStore(SCHEMA)

    # [LAW:one-source-of-truth] Computed assembles VisState dict from 18 observables.
    # Lives on the store object — survives reconcile (reads via stable store.get()).
    @computed
    def active_filters():
        return {
            name: cc_dump.formatting.VisState(
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
            "tmux_auto_zoom": store.get("tmux:auto_zoom"),
            "tmux_zoomed": store.get("tmux:zoomed"),
            "active_launch_config_name": store.get("launch:active_name"),
            "active_streams": store.get("streams:active"),
            "focused_stream_id": store.get("streams:focused"),
            "stream_view_mode": store.get("streams:view"),
            "_gen": store.get("theme:generation"),
        }

    store.footer_state = footer_state

    # // [LAW:single-enforcer] error_items Computed combines stale files + exceptions.
    @computed
    def error_items():
        ErrorItem = cc_dump.tui.error_indicator.ErrorItem
        items = [ErrorItem("stale", "\u274c", s.split("/")[-1]) for s in store.stale_files]
        items.extend(store.exception_items)
        return items

    store.error_items = error_items

    # // [LAW:single-enforcer] sc_panel_state Computed combines side-channel fields.
    # Returns plain dict — bridge converts to SideChannelPanelState.
    @computed
    def sc_panel_state():
        settings = getattr(store, '_settings_store', None)
        return {
            "enabled": settings.get("side_channel_enabled") if settings else False,
            "loading": store.get("sc:loading"),
            "result_text": store.get("sc:result_text"),
            "result_source": store.get("sc:result_source"),
            "result_elapsed_ms": store.get("sc:result_elapsed_ms"),
        }

    store.sc_panel_state = sc_panel_state

    return store


def setup_reactions(store, context=None):
    """Register reactions. Returns list of disposers.

    Called on create and on hot-reload reconcile.
    context: dict with "app", optional "settings_store", and push callbacks from bridge.

    // [LAW:single-enforcer] All guards (pause, NoMatches, thread-marshal) enforced by stx.
    // [LAW:one-way-deps] Push callbacks provided by caller, not imported here.
    """
    disposers = []

    if context:
        app = context.get("app")
        settings_store = context.get("settings_store")

        # Wire settings_store ref for sc_panel_state Computed cross-store access
        if settings_store is not None:
            store._settings_store = settings_store

        if app is not None:
            disposers.append(stx.autorun(app,
                lambda: (store.active_filters.get(), app._rerender_if_mounted())
            ))

            # // [LAW:single-enforcer] Callback-based reactions — bridge provides push functions.
            for key, data_fn in [
                ("push_panel_change", lambda: store.get("panel:active")),
                ("push_footer", lambda: store.footer_state.get()),
                ("push_errors", lambda: store.error_items.get()),
                ("push_sc_panel", lambda: store.sc_panel_state.get()),
            ]:
                cb = context.get(key)
                if cb:
                    disposers.append(stx.reaction(app, data_fn, cb))

    return disposers


def get_category_state(store, name: str) -> "cc_dump.formatting.VisState":
    """Read 3 keys, return VisState for a category."""
    return cc_dump.formatting.VisState(
        store.get(f"vis:{name}"),
        store.get(f"full:{name}"),
        store.get(f"exp:{name}"),
    )
