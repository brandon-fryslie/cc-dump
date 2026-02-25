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
        border: solid $primary-muted;
        background: $panel;
        color: $text;
    }
    """

    def __init__(self):
        super().__init__("")
        self._info: dict = {}
        # // [LAW:one-source-of-truth] Copiable field mapping: label → info dict key
        # // [LAW:one-type-per-behavior] All rows have identical click-to-copy behavior
        self._copiable_fields = {
            "Proxy URL": "proxy_url",
            "Proxy Mode": "proxy_mode",
            "Provider": "provider",
            "Target": "target",
            "Session": "session_name",
            "Session ID": "session_id",
            "Recording": "recording_path",
            "Recordings Dir": "recording_dir",
            "Replay From": "replay_file",
            "Python": "python_version",
            "Textual": "textual_version",
            "PID": "pid",
        }

    def update_info(self, info: dict):
        """Update the info panel with server configuration.

        Args:
            info: Dict with server info fields (see render_info_panel for schema)
        """
        self._info = info
        self._refresh_display()

    def _refresh_display(self):
        """Rebuild the info panel display."""
        text = cc_dump.tui.panel_renderers.render_info_panel(self._info)
        self.update(text)

    def on_click(self, event) -> None:
        """Copy field value to clipboard on click.

        Determines which row was clicked by mapping click y to row index.
        // [LAW:dataflow-not-control-flow] Click always resolves to a row;
        // copy value is derived from the row's info key.
        """
        # Row 0 is the "Server Info" title, rows 1+ are data rows
        # // [LAW:one-source-of-truth] Row order derived from _copiable_fields
        row_labels = list(self._copiable_fields.keys())

        # Click y is relative to widget; row 0 = title, row 1+ = data
        clicked_row = int(event.y) - 1  # subtract title row
        if 0 <= clicked_row < len(row_labels):
            label = row_labels[clicked_row]
            info_key = self._copiable_fields[label]
            value = str(self._info.get(info_key, "") or "")
            if value:
                self.app.copy_to_clipboard(value)
                self.app.notify(f"Copied {label}: {value}", severity="information")

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
