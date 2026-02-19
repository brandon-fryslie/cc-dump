"""Launch config panel — docked side panel for managing run configurations.

This module is RELOADABLE. When it reloads, any mounted panel is
removed during hot-reload (stateless, user can re-open with C).

// [LAW:one-type-per-behavior] Reuses FieldDef/FieldState from settings_panel.
"""

from __future__ import annotations

from textual.widgets import Static

import cc_dump.palette
from cc_dump.tui.settings_panel import (
    TextFieldDef,
    BoolFieldDef,
    TextFieldState,
    BoolFieldState,
    FieldDef,
    FieldState,
)


# [LAW:one-source-of-truth] Field definitions for a LaunchConfig.
CONFIG_FIELDS: list[FieldDef] = [
    TextFieldDef(
        key="name",
        label="Name",
        default="default",
        description="Config identifier",
    ),
    TextFieldDef(
        key="model",
        label="Model",
        default="",
        description="--model flag (empty = none)",
    ),
    BoolFieldDef(
        key="auto_resume",
        label="Auto-Resume",
        default=True,
        description="Pass --resume <session_id>",
    ),
    TextFieldDef(
        key="extra_flags",
        label="Extra Flags",
        default="",
        description="Appended to command",
    ),
]


def make_field_states(config) -> list[FieldState]:
    """Create FieldState list from a LaunchConfig instance."""
    states: list[FieldState] = []
    for field_def in CONFIG_FIELDS:
        value = getattr(config, field_def.key, field_def.default)
        states.append(field_def.make_state(value))
    return states


def apply_fields_to_config(config, fields: list[FieldState]) -> None:
    """Write FieldState values back onto a LaunchConfig."""
    for field_state in fields:
        setattr(config, field_state.key, field_state.save_value)


class LaunchConfigPanel(Static):
    """Side panel for managing launch configurations."""

    DEFAULT_CSS = """
    LaunchConfigPanel {
        dock: right;
        width: 40%;
        min-width: 34;
        max-width: 56;
        border-left: solid $accent;
        padding: 1;
        height: 1fr;
        overflow-y: auto;
    }
    """

    def __init__(self):
        super().__init__("")

    def update_display(
        self,
        configs: list,
        selected_idx: int,
        fields: list[FieldState],
        active_field_idx: int,
        active_config_name: str,
    ) -> None:
        """Re-render with current editing state."""
        from rich.text import Text

        p = cc_dump.palette.PALETTE

        text = Text()
        text.append("Launch Configs", style="bold {}".format(p.info))
        text.append("\n\n")

        # Config list with numbers
        for i, config in enumerate(configs):
            is_selected = (i == selected_idx)
            is_active = (config.name == active_config_name)
            marker = "[*]" if is_active else "   "
            prefix = ">" if is_selected else " "
            style = "bold" if is_selected else "dim"
            text.append("  {} {}. {} {}".format(prefix, i + 1, marker, config.name), style=style)
            text.append("\n")

        text.append("\n")

        # Edit section for selected config
        selected_name = configs[selected_idx].name if configs else ""
        text.append("  -- Edit: {} --".format(selected_name), style="bold")
        text.append("\n\n")

        for i, (field_def, field_state) in enumerate(zip(CONFIG_FIELDS, fields)):
            is_active_field = (i == active_field_idx)
            label_style = "bold" if is_active_field else "dim bold"
            text.append("  ")
            text.append(field_def.label, style=label_style)
            text.append("\n")

            text.append("  ")
            if isinstance(field_state, TextFieldState):
                _render_text_field(text, field_state, is_active_field)
            elif isinstance(field_state, BoolFieldState):
                _render_bool_field(text, field_state, is_active_field)
            text.append("\n")

            text.append("  ")
            text.append(field_def.description, style="dim italic")
            text.append("\n\n")

        # Footer instructions
        text.append("  ")
        text.append("1-9", style="bold {}".format(p.info))
        text.append(" launch  ", style="dim")
        text.append("a", style="bold {}".format(p.info))
        text.append(" activate  ", style="dim")
        text.append("n", style="bold {}".format(p.info))
        text.append(" new", style="dim")
        text.append("\n  ")
        text.append("d", style="bold {}".format(p.info))
        text.append(" delete  ", style="dim")
        text.append("enter", style="bold {}".format(p.info))
        text.append(" save  ", style="dim")
        text.append("esc", style="bold {}".format(p.info))
        text.append(" close", style="dim")

        self.update(text)

    def get_state(self) -> dict:
        return {}  # Stateless

    def restore_state(self, state: dict):
        pass


def _render_text_field(text, state: TextFieldState, is_active: bool) -> None:
    """Render text field with cursor."""
    value = state.value
    if is_active:
        pos = state.cursor_pos
        before = value[:pos]
        cursor_char = value[pos] if pos < len(value) else " "
        after = value[pos + 1:] if pos < len(value) else ""
        text.append(before, style="bold")
        text.append(cursor_char, style="reverse bold")
        text.append(after, style="bold")
    else:
        text.append(value or "(empty)", style="dim")


def _render_bool_field(text, state: BoolFieldState, is_active: bool) -> None:
    """Render boolean checkbox."""
    marker = "x" if state.value else " "
    style = "bold" if is_active else "dim"
    text.append("[{}]".format(marker), style=style)
    text.append(" ", style=style)
    label = "Enabled" if state.value else "Disabled"
    text.append(label, style=style)


def create_launch_config_panel() -> LaunchConfigPanel:
    """Create a new LaunchConfigPanel instance."""
    return LaunchConfigPanel()
