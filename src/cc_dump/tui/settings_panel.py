"""Settings panel — docked side panel for editing app settings.

This module is RELOADABLE. When it reloads, any mounted panel is
removed during hot-reload (stateless, user can re-open with S).

// [LAW:one-source-of-truth] SETTINGS_FIELDS defines all editable settings.
"""

from textual.widgets import Static

import cc_dump.palette

# [LAW:one-source-of-truth] Field definitions for the settings panel.
# Adding a new setting = adding an entry here.
SETTINGS_FIELDS = [
    {
        "key": "claude_command",
        "label": "Claude Command",
        "default": "claude",
        "description": "Command to launch Claude in tmux pane",
    },
]


class SettingsPanel(Static):
    """Side panel for editing application settings."""

    DEFAULT_CSS = """
    SettingsPanel {
        dock: right;
        width: 35%;
        min-width: 30;
        max-width: 50;
        border-left: solid $accent;
        padding: 1;
        height: 1fr;
        overflow-y: auto;
    }
    """

    def __init__(self):
        super().__init__("")

    def update_display(self, fields: list[dict], active_idx: int) -> None:
        """Re-render with current editing state.

        Args:
            fields: list of {key, value, cursor_pos} dicts
            active_idx: index of the currently active field
        """
        from rich.text import Text

        p = cc_dump.palette.PALETTE
        text = Text()
        text.append("Settings", style="bold {}".format(p.info))
        text.append("\n\n")

        for i, field_def in enumerate(SETTINGS_FIELDS):
            is_active = (i == active_idx)
            field_data = fields[i] if i < len(fields) else {}
            value = field_data.get("value", field_def["default"])
            cursor_pos = field_data.get("cursor_pos", len(value))

            # Label
            label_style = "bold" if is_active else "dim bold"
            text.append("  ")
            text.append(field_def["label"], style=label_style)
            text.append("\n")

            # Value with cursor
            text.append("  ")
            if is_active:
                # Show cursor as reverse-styled character
                before = value[:cursor_pos]
                cursor_char = value[cursor_pos] if cursor_pos < len(value) else " "
                after = value[cursor_pos + 1:] if cursor_pos < len(value) else ""
                text.append(before, style="bold")
                text.append(cursor_char, style="reverse bold")
                text.append(after, style="bold")
            else:
                text.append(value, style="dim")
            text.append("\n")

            # Description
            text.append("  ")
            text.append(field_def["description"], style="dim italic")
            text.append("\n\n")

        # Footer instructions
        text.append("  ")
        text.append("Tab", style="bold {}".format(p.info))
        text.append(" next  ", style="dim")
        text.append("Enter", style="bold {}".format(p.info))
        text.append(" save  ", style="dim")
        text.append("Esc", style="bold {}".format(p.info))
        text.append(" cancel", style="dim")

        self.update(text)

    def get_state(self) -> dict:
        return {}  # Stateless

    def restore_state(self, state: dict):
        pass


def create_settings_panel() -> SettingsPanel:
    """Create a new SettingsPanel instance."""
    return SettingsPanel()
