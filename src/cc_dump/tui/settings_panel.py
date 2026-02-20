"""Settings panel — docked side panel for editing app settings.

This module is RELOADABLE. When it reloads, any mounted panel is
removed during hot-reload (stateless, user can re-open with S).

// [LAW:one-source-of-truth] SETTINGS_FIELDS defines all editable settings.
// [LAW:one-type-per-behavior] FieldDef/FieldState unions — one type per behavior,
//   instances differ by config, not by duplicated types.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.widgets import Static

import cc_dump.palette


# ─── Field definitions (frozen, describe what a field is) ─────────────────────


@dataclass(frozen=True)
class TextFieldDef:
    key: str
    label: str
    description: str
    default: str

    def make_state(self, value: object) -> TextFieldState:
        s = str(value)
        return TextFieldState(key=self.key, value=s, cursor_pos=len(s))


@dataclass(frozen=True)
class BoolFieldDef:
    key: str
    label: str
    description: str
    default: bool

    def make_state(self, value: object) -> BoolFieldState:
        return BoolFieldState(key=self.key, value=bool(value))


FieldDef = TextFieldDef | BoolFieldDef


# ─── Field editing state (mutable, handles input) ────────────────────────────


@dataclass
class TextFieldState:
    key: str
    value: str
    cursor_pos: int

    def handle_key(self, key: str, character: str | None) -> None:
        """Handle text editing keys: backspace, delete, arrows, home, end, printable."""
        pos = self.cursor_pos
        value = self.value

        # [LAW:dataflow-not-control-flow] Lookup table for cursor-only mutations
        _CURSOR_MOVES = {
            "left": lambda v, p: max(0, p - 1),
            "right": lambda v, p: min(len(v), p + 1),
            "home": lambda v, p: 0,
            "end": lambda v, p: len(v),
        }
        if key in _CURSOR_MOVES:
            self.cursor_pos = _CURSOR_MOVES[key](value, pos)
            return

        if key == "backspace" and pos > 0:
            self.value = value[:pos - 1] + value[pos:]
            self.cursor_pos = pos - 1
            return

        if key == "delete" and pos < len(value):
            self.value = value[:pos] + value[pos + 1:]
            return

        if character and character.isprintable():
            self.value = value[:pos] + character + value[pos:]
            self.cursor_pos = pos + 1

    @property
    def save_value(self) -> str:
        return self.value


@dataclass
class BoolFieldState:
    key: str
    value: bool

    def handle_key(self, key: str, character: str | None) -> None:
        """Space toggles the boolean."""
        if key == "space":
            self.value = not self.value

    @property
    def save_value(self) -> bool:
        return self.value


@dataclass(frozen=True)
class SelectFieldDef:
    key: str
    label: str
    description: str
    options: tuple[str, ...]  # ordered choices
    default: str

    def make_state(self, value: object) -> "SelectFieldState":
        s = str(value) if value else self.default
        # Clamp to valid option
        idx = self.options.index(s) if s in self.options else 0
        return SelectFieldState(key=self.key, options=self.options, selected=idx)


@dataclass
class SelectFieldState:
    key: str
    options: tuple[str, ...]
    selected: int

    def handle_key(self, key: str, character: str | None) -> None:
        """Left/right or space cycles through options."""
        if key in ("space", "right"):
            self.selected = (self.selected + 1) % len(self.options)
        elif key == "left":
            self.selected = (self.selected - 1) % len(self.options)

    @property
    def value(self) -> str:
        return self.options[self.selected]

    @property
    def save_value(self) -> str:
        return self.options[self.selected]


FieldDef = TextFieldDef | BoolFieldDef | SelectFieldDef
FieldState = TextFieldState | BoolFieldState | SelectFieldState


# ─── Field registry ──────────────────────────────────────────────────────────
# [LAW:one-source-of-truth] Adding a new setting = adding an entry here.

SETTINGS_FIELDS: list[FieldDef] = [
    TextFieldDef(
        key="claude_command",
        label="Claude Command",
        default="claude",
        description="Command to launch Claude in tmux pane",
    ),
    BoolFieldDef(
        key="auto_zoom_default",
        label="Auto-Zoom Default",
        default=False,
        description="Start with tmux auto-zoom enabled",
    ),
    BoolFieldDef(
        key="side_channel_enabled",
        label="AI Summaries",
        default=True,
        description="Enable AI-powered summaries via claude -p",
    ),
]


# ─── Panel widget ─────────────────────────────────────────────────────────────


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

    def update_display(self, fields: list[FieldState], active_idx: int) -> None:
        """Re-render with current editing state."""
        from rich.text import Text

        p = cc_dump.palette.PALETTE
        text = Text()
        text.append("Settings", style="bold {}".format(p.info))
        text.append("\n\n")

        for i, (field_def, field_state) in enumerate(zip(SETTINGS_FIELDS, fields)):
            is_active = (i == active_idx)
            # Label
            label_style = "bold" if is_active else "dim bold"
            text.append("  ")
            text.append(field_def.label, style=label_style)
            text.append("\n")

            # Value rendering — dispatched by state type
            text.append("  ")
            if isinstance(field_state, TextFieldState):
                self._render_text_field(text, field_state, is_active)
            elif isinstance(field_state, BoolFieldState):
                self._render_bool_field(text, field_state, is_active)
            text.append("\n")

            # Description
            text.append("  ")
            text.append(field_def.description, style="dim italic")
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

    @staticmethod
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
            text.append(value, style="dim")

    @staticmethod
    def _render_bool_field(text, state: BoolFieldState, is_active: bool) -> None:
        """Render boolean checkbox."""
        marker = "x" if state.value else " "
        style = "bold" if is_active else "dim"
        text.append("[{}]".format(marker), style=style)
        text.append(" ", style=style)
        label = "Enabled" if state.value else "Disabled"
        text.append(label, style=style)

    def get_state(self) -> dict:
        return {}  # Stateless

    def restore_state(self, state: dict):
        pass


def create_settings_panel() -> SettingsPanel:
    """Create a new SettingsPanel instance."""
    return SettingsPanel()
