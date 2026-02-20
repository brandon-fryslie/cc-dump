"""View store — category visibility state. RELOADABLE.

// [LAW:one-source-of-truth] Schema derived from CATEGORY_CONFIG.
// [LAW:single-enforcer] Single autorun triggers re-render on any visibility change.
"""

import cc_dump.formatting

from cc_dump.tui.category_config import CATEGORY_CONFIG


# [LAW:one-source-of-truth] Schema built programmatically from CATEGORY_CONFIG
SCHEMA: dict[str, bool] = {}
for _key, _name, _desc, _default in CATEGORY_CONFIG:
    SCHEMA[f"vis:{_name}"] = _default.visible
    SCHEMA[f"full:{_name}"] = _default.full
    SCHEMA[f"exp:{_name}"] = _default.expanded


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
    from snarfx import autorun

    disposers = []

    if context:
        app = context.get("app")
        if app is not None:
            disposers.append(autorun(
                lambda: (store.active_filters.get(), app._rerender_if_mounted())
            ))

    return disposers


def get_category_state(store, name: str) -> "cc_dump.formatting.VisState":
    """Read 3 keys, return VisState for a category."""
    return cc_dump.formatting.VisState(
        store.get(f"vis:{name}"),
        store.get(f"full:{name}"),
        store.get(f"exp:{name}"),
    )
