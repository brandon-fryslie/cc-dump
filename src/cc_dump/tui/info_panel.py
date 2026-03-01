"""Info panel showing server configuration and connection details.

This module is RELOADABLE. When it reloads, the app can create new
InfoPanel instances and swap them in via hot-reload.

All field values are click-to-copy.
"""

from textual.widgets import Static

# Use module-level imports for hot-reload
import cc_dump.core.palette
import cc_dump.tui.panel_renderers


class InfoPanel(Static):
    """Panel showing server configuration, connection info, and session details.

    All field values are click-to-copy.
    """

    DEFAULT_CSS = """
    InfoPanel {
        height: auto;
        max-height: 20;
        dock: bottom;
        padding: 0 1;
        border: solid $accent;
    }
    """

    def __init__(self):
        super().__init__("")
        self._info: dict = {}
        self._rows: list[tuple[str, str, str]] = []

    def update_info(self, info: dict):
        """Update the info panel with server configuration.

        Args:
            info: Dict with server info fields (see render_info_panel for schema)
        """
        self._info = info
        self._refresh_display()

    def _refresh_display(self):
        """Rebuild the info panel display."""
        # // [LAW:one-source-of-truth] Rows are derived by panel_renderers.info_panel_rows.
        self._rows = cc_dump.tui.panel_renderers.info_panel_rows(self._info)
        text = cc_dump.tui.panel_renderers.render_info_panel(self._info)
        self.update(text)

    def on_click(self, event) -> None:
        """Copy field value to clipboard on click.

        Determines which row was clicked by mapping click y to row index.
        // [LAW:dataflow-not-control-flow] Click always resolves to a row;
        // copy value is derived from the row's info key.
        """
        # Row 0 is the "Server Info" title, rows 1+ are data rows.
        clicked_row = int(event.y) - 1  # subtract title row
        if 0 <= clicked_row < len(self._rows):
            label, _display, copy_value = self._rows[clicked_row]
            if copy_value:
                self.app.copy_to_clipboard(copy_value)
                self.app.notify(f"Copied: {copy_value}", severity="information")

    def get_state(self) -> dict:
        """Extract state for transfer to a new instance."""
        return {"info": dict(self._info)}

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self._info = state.get("info", {})
        self._refresh_display()


def create_info_panel() -> InfoPanel:
    """Create a new InfoPanel instance."""
    return InfoPanel()
