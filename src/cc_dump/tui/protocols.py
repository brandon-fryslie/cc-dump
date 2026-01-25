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

from typing import Protocol, Dict, Any


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
            def get_state(self) -> Dict[str, Any]:
                return {"count": self.count, "items": self.items}

            def restore_state(self, state: Dict[str, Any]) -> None:
                self.count = state.get("count", 0)
                self.items = state.get("items", [])
    """

    def get_state(self) -> Dict[str, Any]:
        """Extract widget state for transfer to a new instance.

        Returns:
            Dictionary containing all state needed to reconstruct the widget.
            Should be JSON-serializable (str, int, float, bool, list, dict, None).
        """
        ...

    def restore_state(self, state: Dict[str, Any]) -> None:
        """Restore state from a previous widget instance.

        Args:
            state: State dictionary from a previous instance's get_state().
                   Should handle missing keys gracefully with defaults.
        """
        ...
