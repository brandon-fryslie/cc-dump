"""Info panel showing server configuration and connection details.

This module is RELOADABLE. When it reloads, the app can create new
InfoPanel instances and swap them in via hot-reload.

All field values are click-to-copy.
"""

from snarfx import Observable, reaction
from snarfx import textual as stx
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
        overflow-y: auto;
    }
    """

    def __init__(self):
        super().__init__("")
        self._rows: list[tuple[str, str, str]] = []
        self._info: Observable[dict[str, object]] = Observable({})
        # [LAW:single-enforcer] One reactive projection owns info text + click rows.
        self._info_reaction = reaction(
            lambda: self._info.get(),
            self._render_info,
            fire_immediately=False,
        )

    def update_info(self, info: dict):
        """Update the info panel with server configuration.

        Args:
            info: Dict with server info fields (see render_info_panel for schema)
        """
        self._info.set(dict(info))

    def _render_info(self, info: dict):
        """Rebuild the info panel display from current info state."""
        # // [LAW:one-source-of-truth] Rows are derived by panel_renderers.info_panel_rows.
        self._rows = cc_dump.tui.panel_renderers.info_panel_rows(info)
        if not self.is_attached:
            return
        text = cc_dump.tui.panel_renderers.render_info_panel(info)
        self.update(text)

    def on_mount(self) -> None:
        self._visibility_reaction = stx.reaction(
            self.app,
            lambda: bool(self.app.view_store.get("panel:info")),
            self._apply_panel_visibility,
            fire_immediately=True,
        )
        self._render_info(dict(self._info.get()))

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
        return {"info": dict(self._info.get())}

    def restore_state(self, state: dict):
        """Restore state from a previous instance."""
        self._info.set(dict(state.get("info", {})))

    def on_unmount(self) -> None:
        self._visibility_reaction.dispose()
        self._info_reaction.dispose()

    def _apply_panel_visibility(self, visible: bool) -> None:
        self.display = bool(visible)


def create_info_panel() -> InfoPanel:
    """Create a new InfoPanel instance."""
    return InfoPanel()
