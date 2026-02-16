"""Protocol definitions for hot-swappable TUI widgets.

This module defines the contracts that widgets must satisfy to be hot-reloadable.
It is itself RELOADABLE and has no dependencies on other project modules.

The HotSwappableWidget protocol enables the widget hot-swap pattern:
1. Widget modification triggers reload of widget_factory.py
2. App extracts state from old widget instances via get_state()
3. App creates new widget instances from reloaded factory
4. App restores state to new instances via restore_state()
5. App swaps new widgets in place of old ones

This guarantees that code changes take effect immediately without proxy restart.
"""

from typing import Protocol


_Leaf = str | int | float | bool | None
WidgetStateValue = _Leaf | list | dict | set
WidgetState = dict[str, WidgetStateValue]


class HotSwappableWidget(Protocol):
    """Protocol for widgets that can be hot-swapped at runtime.

    Any widget that implements get_state() and restore_state() with these
    signatures can be hot-swapped. The protocol uses structural typing
    (duck typing with type safety), so widgets don't need to explicitly
    inherit from this protocol.

    State Transfer Contract:
    - get_state() must return all data needed to reconstruct the widget's
      visual and logical state
    - restore_state() must accept that dict and restore the widget to the
      equivalent state
    - State dicts should be JSON-serializable for future persistence/debugging
    - Missing keys in restore_state() should have sensible defaults

    Example:
        class MyWidget:
            def get_state(self) -> WidgetState:
                return {"count": self.count, "items": self.items}

            def restore_state(self, state: WidgetState) -> None:
                self.count = state.get("count", 0)
                self.items = state.get("items", [])
    """

    def get_state(self) -> WidgetState:
        """Extract widget state for transfer to a new instance.

        Returns:
            Dictionary containing all state needed to reconstruct the widget.
            Should be JSON-serializable (str, int, float, bool, list, dict, None).
        """
        ...

    def restore_state(self, state: WidgetState) -> None:
        """Restore state from a previous widget instance.

        Args:
            state: State dictionary from a previous instance's get_state().
                   Should handle missing keys gracefully with defaults.
        """
        ...


class CyclingPanel(Protocol):
    """Protocol for cycling panels that refresh from the analytics store.

    Extends HotSwappableWidget with refresh_from_store() and cycle_mode().
    All cycling panels (stats, economics, timeline, session) implement this shape.
    """

    def refresh_from_store(self, store, **kwargs) -> None:
        """Refresh panel data from the analytics store."""
        ...

    def cycle_mode(self) -> None:
        """Cycle intra-panel display mode (e.g. aggregate vs breakdown)."""
        ...

    def get_state(self) -> WidgetState:
        """Extract widget state for transfer to a new instance."""
        ...

    def restore_state(self, state: WidgetState) -> None:
        """Restore state from a previous widget instance."""
        ...


def validate_widget_protocol(widget) -> None:
    """Validate that a widget implements the HotSwappableWidget protocol.

    This function performs runtime validation using duck typing to ensure
    a widget has the required methods for hot-swapping.

    Args:
        widget: Widget instance to validate

    Raises:
        TypeError: If widget is missing required methods or they're not callable

    Example:
        >>> widget = MyWidget()
        >>> validate_widget_protocol(widget)  # Raises if invalid
    """
    required_methods = ["get_state", "restore_state"]

    for method_name in required_methods:
        if not hasattr(widget, method_name):
            raise TypeError(
                f"Widget {type(widget).__name__} does not implement HotSwappableWidget protocol: "
                f"missing method '{method_name}()'"
            )

        method = getattr(widget, method_name)
        if not callable(method):
            raise TypeError(
                f"Widget {type(widget).__name__} does not implement HotSwappableWidget protocol: "
                f"'{method_name}' exists but is not callable"
            )
