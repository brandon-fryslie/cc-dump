"""View store — category visibility + panel/follow state. RELOADABLE.

// [LAW:one-source-of-truth] Schema derived from CATEGORY_CONFIG + panel/follow keys.
// [LAW:single-enforcer] Single autorun triggers re-render on any visibility change.
// [LAW:single-enforcer] Single reaction drives panel display sync.
"""

import cc_dump.formatting

from cc_dump.tui.category_config import CATEGORY_CONFIG


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


def create():
    """Create view store with defaults from CATEGORY_CONFIG."""
    from snarfx.hot_reload import HotReloadStore
    from snarfx import computed

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
    return store


def setup_reactions(store, context=None):
    """Register reactions. Returns list of disposers.

    Called on create and on hot-reload reconcile.
    context: dict with "app" key for re-render autorun.
    """
    from snarfx import autorun, reaction

    disposers = []

    if context:
        app = context.get("app")
        if app is not None:
            disposers.append(autorun(
                lambda: (store.active_filters.get(), app._rerender_if_mounted())
            ))

            # // [LAW:single-enforcer] Single reaction drives panel display sync.
            disposers.append(reaction(
                lambda: store.get("panel:active"),
                lambda value: _on_active_panel_changed(app, value),
            ))

    return disposers


def _on_active_panel_changed(app, value):
    """Effect: sync panel widget display, refresh data, update footer.

    Guard against firing during hot-reload widget swap or before app is running.
    """
    if not app.is_running or app._replacing_widgets:
        return
    from cc_dump.tui import action_handlers as _actions
    app._sync_panel_display(value)
    _actions.refresh_active_panel(app, value)
    app._update_footer_state()


def get_category_state(store, name: str) -> "cc_dump.formatting.VisState":
    """Read 3 keys, return VisState for a category."""
    return cc_dump.formatting.VisState(
        store.get(f"vis:{name}"),
        store.get(f"full:{name}"),
        store.get(f"exp:{name}"),
    )
