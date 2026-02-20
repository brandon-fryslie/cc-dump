"""View store — category visibility + panel/follow + footer/error/side-channel state. RELOADABLE.

// [LAW:one-source-of-truth] Schema derived from CATEGORY_CONFIG + panel/follow + footer/error/sc keys.
// [LAW:single-enforcer] Single autorun triggers re-render on any visibility change.
// [LAW:single-enforcer] Single reaction per widget push (panel, footer, error, side-channel).
"""

import cc_dump.formatting

from cc_dump.tui.category_config import CATEGORY_CONFIG
from snarfx.hot_reload import HotReloadStore
from snarfx import computed, ObservableList
from snarfx import textual as stx
import cc_dump.tui.widget_factory
import cc_dump.tui.error_indicator
import cc_dump.tui.side_channel_panel
import cc_dump.tui.custom_footer
from cc_dump.tui import action_handlers as _actions


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
SCHEMA["follow"] = "active"

# Footer inputs (previously app attributes or external reads)
SCHEMA["active_filterset"] = None           # str|None — was app._active_filterset_slot
SCHEMA["tmux:available"] = False            # bool — mirrored from tmux controller
SCHEMA["tmux:auto_zoom"] = False            # bool — mirrored from tmux controller
SCHEMA["tmux:zoomed"] = False               # bool — mirrored from tmux controller
SCHEMA["active_launch_config_name"] = ""    # str — was load_active_name() file I/O each call
SCHEMA["theme_generation"] = 0              # int — bumped on theme change to invalidate footer

# Side-channel panel state (previously app._side_channel_* attributes)
SCHEMA["sc:loading"] = False
SCHEMA["sc:result_text"] = ""
SCHEMA["sc:result_source"] = ""
SCHEMA["sc:result_elapsed_ms"] = 0


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
    @computed
    def footer_state():
        return {
            **store.active_filters.get(),
            "active_panel": store.get("panel:active"),
            "follow_state": cc_dump.tui.widget_factory.FollowState(store.get("follow")),
            "active_filterset": store.get("active_filterset"),
            "tmux_available": store.get("tmux:available"),
            "tmux_auto_zoom": store.get("tmux:auto_zoom"),
            "tmux_zoomed": store.get("tmux:zoomed"),
            "active_launch_config_name": store.get("active_launch_config_name"),
            "_gen": store.get("theme_generation"),
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
    @computed
    def sc_panel_state():
        settings = getattr(store, '_settings_store', None)
        return cc_dump.tui.side_channel_panel.SideChannelPanelState(
            enabled=settings.get("side_channel_enabled") if settings else False,
            loading=store.get("sc:loading"),
            result_text=store.get("sc:result_text"),
            result_source=store.get("sc:result_source"),
            result_elapsed_ms=store.get("sc:result_elapsed_ms"),
        )

    store.sc_panel_state = sc_panel_state

    return store


def setup_reactions(store, context=None):
    """Register reactions. Returns list of disposers.

    Called on create and on hot-reload reconcile.
    context: dict with "app", optional "settings_store" keys.

    // [LAW:single-enforcer] All guards (pause, NoMatches, thread-marshal) enforced by stx.
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

            # // [LAW:single-enforcer] Single reaction drives panel display sync.
            def _on_panel_change(value):
                app._sync_panel_display(value)
                _actions.refresh_active_panel(app, value)

            disposers.append(stx.reaction(app,
                lambda: store.get("panel:active"),
                _on_panel_change,
            ))

            # // [LAW:single-enforcer] Footer reaction
            disposers.append(stx.reaction(app,
                lambda: store.footer_state.get(),
                lambda state: app.query_one(
                    cc_dump.tui.custom_footer.StatusFooter
                ).update_display(state),
            ))

            # // [LAW:single-enforcer] Error indicator reaction
            def _push_errors(items):
                conv = app._get_conv()
                if conv is not None:
                    conv.update_error_items(items)

            disposers.append(stx.reaction(app,
                lambda: store.error_items.get(),
                _push_errors,
            ))

            # // [LAW:single-enforcer] Side-channel panel reaction
            disposers.append(stx.reaction(app,
                lambda: store.sc_panel_state.get(),
                lambda state: app.screen.query(
                    cc_dump.tui.side_channel_panel.SideChannelPanel
                ).first().update_display(state),
            ))

    return disposers


def get_category_state(store, name: str) -> "cc_dump.formatting.VisState":
    """Read 3 keys, return VisState for a category."""
    return cc_dump.formatting.VisState(
        store.get(f"vis:{name}"),
        store.get(f"full:{name}"),
        store.get(f"exp:{name}"),
    )
