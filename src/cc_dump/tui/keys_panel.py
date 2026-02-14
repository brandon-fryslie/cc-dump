"""Keys panel showing keyboard shortcuts.

This module is RELOADABLE. When it reloads, any mounted panel is
removed during hot-reload (stateless, user can re-open with ?).
"""

from textual.widgets import Static

# Use module-level imports for hot-reload
import cc_dump.tui.panel_renderers


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
        self._refresh_display()

    def _refresh_display(self):
        text = cc_dump.tui.panel_renderers.render_keys_panel()
        self.update(text)

    def get_state(self) -> dict:
        return {}  # Stateless

    def restore_state(self, state: dict):
        self._refresh_display()


def create_keys_panel() -> KeysPanel:
    """Create a new KeysPanel instance."""
    return KeysPanel()
