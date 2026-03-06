"""StoreWidget mixin — self-subscribing store widget.

Widgets that subclass StoreWidget set up their own store reactions in on_mount
(guaranteed post-compose) and dispose them in on_unmount. Subscription lifecycle
is owned by the consumer, making it structurally impossible to receive store
pushes before child widgets exist.

// [LAW:single-enforcer] on_mount is the sole subscription entry point.
// [LAW:one-way-deps] Reactions flow store→widget; widgets never write to stores here.

RELOADABLE — must appear before consumers in _RELOAD_ORDER.
"""

from textual.widget import Widget


class StoreWidget(Widget):
    """Mixin: widget that self-subscribes to reactive stores.

    Override _setup_store_reactions() to return a list of disposers from
    stx.reaction() / stx.autorun() calls. They are created on mount and
    disposed on unmount automatically.
    """

    def on_mount(self) -> None:
        self._store_disposers = self._setup_store_reactions()

    def on_unmount(self) -> None:
        for d in getattr(self, "_store_disposers", []):
            d.dispose()

    def _setup_store_reactions(self) -> list:
        """Override to return list of reaction disposers.

        Called from on_mount — children are guaranteed ready.
        Use stx.reaction(self.app, data_fn, effect_fn) for Textual-safe reactions.
        """
        return []
