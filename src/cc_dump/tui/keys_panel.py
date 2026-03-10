"""Keys panel showing keyboard shortcuts.

This module is RELOADABLE. When it reloads, any mounted panel is
removed during hot-reload (stateless, user can re-open with ?).
"""

from dataclasses import dataclass

from snarfx import Observable, reaction
from snarfx import textual as stx
from rich.text import Text
from textual.widgets import Static

# Use module-level imports for hot-reload
import cc_dump.tui.panel_renderers


@dataclass(frozen=True)
class KeysPanelState:
    text: Text


class KeysPanel(Static):
    """Side panel showing keyboard shortcuts."""

    DEFAULT_CSS = """
    KeysPanel {
        dock: right;
        width: 28%;
        min-width: 24;
        max-width: 36;
        border-left: solid $accent;
        padding: 1;
        height: 1fr;
        overflow-y: auto;
    }
    """

    def __init__(self):
        super().__init__("")
        self._state: Observable[KeysPanelState] = Observable(
            KeysPanelState(text=cc_dump.tui.panel_renderers.render_keys_panel())
        )
        # [LAW:single-enforcer] Keys panel text updates are projected via one local reaction.
        self._state_reaction = reaction(
            lambda: self._state.get(),
            self._apply_state,
            fire_immediately=False,
        )

    def on_mount(self) -> None:
        self._visibility_reaction = stx.reaction(
            self.app,
            lambda: bool(self.app.view_store.get("panel:keys")),
            self._apply_panel_visibility,
            fire_immediately=True,
        )
        self._apply_state(self._state.get())

    def on_unmount(self) -> None:
        self._visibility_reaction.dispose()
        self._state_reaction.dispose()

    def _apply_panel_visibility(self, visible: bool) -> None:
        self.display = bool(visible)

    def _apply_state(self, state: KeysPanelState) -> None:
        self.update(state.text)

    def _refresh_display(self):
        self._state.set(
            KeysPanelState(text=cc_dump.tui.panel_renderers.render_keys_panel())
        )

    def get_state(self) -> dict:
        return {}  # Stateless

    def restore_state(self, state: dict):
        self._refresh_display()


def create_keys_panel() -> KeysPanel:
    """Create a new KeysPanel instance."""
    return KeysPanel()
