"""Settings panel — docked side panel for editing app settings.

This module is RELOADABLE. When it reloads, any mounted panel is
removed during hot-reload (stateless, user can re-open with S).

// [LAW:one-source-of-truth] SETTINGS_FIELDS defines all editable settings.
// [LAW:one-type-per-behavior] Single FieldDef — instances differ by config (kind),
//   not by duplicated types.
// [LAW:locality-or-seam] Panel handles its own keys and messages — app.py just
//   listens for Saved/Cancelled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.widgets import Input, Label, Select, Static, Switch

import cc_dump.palette


# ─── Field definitions ───────────────────────────────────────────────────────
# // [LAW:one-type-per-behavior] One type with kind discriminator.


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    description: str
    kind: Literal["text", "bool", "select"]
    default: str | bool = ""
    options: tuple[str, ...] = ()  # only for kind="select"


# ─── Field registry ──────────────────────────────────────────────────────────
# // [LAW:one-source-of-truth] Defaults from settings_store.SCHEMA.

import cc_dump.settings_store

SETTINGS_FIELDS: list[FieldDef] = [
    FieldDef(
        key="auto_zoom_default",
        label="Auto-Zoom Default",
        description="Start with tmux auto-zoom enabled",
        kind="bool",
        default=cc_dump.settings_store.SCHEMA["auto_zoom_default"],
    ),
    FieldDef(
        key="side_channel_enabled",
        label="AI Summaries",
        description="Enable AI-powered summaries via claude -p",
        kind="bool",
        default=cc_dump.settings_store.SCHEMA["side_channel_enabled"],
    ),
]


# ─── Widget helpers ──────────────────────────────────────────────────────────


def _make_widget(field: FieldDef, value: object) -> Input | Switch | Select:
    """Create the appropriate Textual widget for a FieldDef."""
    widget_id = "field-{}".format(field.key)
    if field.kind == "text":
        return Input(value=str(value), id=widget_id)
    elif field.kind == "bool":
        return Switch(value=bool(value), id=widget_id)
    else:  # select
        s = str(value) if value else field.default
        options = [(opt or "(none)", opt) for opt in field.options]
        return Select(options, value=s, allow_blank=False, id=widget_id)


# ─── Panel widget ─────────────────────────────────────────────────────────────


class SettingsPanel(VerticalScroll):
    """Side panel for editing application settings.

    Posts Saved or Cancelled messages. App listens for them.
    """

    DEFAULT_CSS = """
    SettingsPanel {
        dock: right;
        width: 35%;
        min-width: 30;
        max-width: 50;
        border-left: solid $accent;
        padding: 0 1;
        height: 1fr;
    }
    SettingsPanel .panel-title {
        text-style: bold;
        margin-bottom: 0;
    }
    SettingsPanel .field-row {
        height: auto;
        width: 100%;
        margin-top: 1;
    }
    SettingsPanel .field-label {
        width: 1fr;
        text-style: bold;
        content-align-vertical: middle;
    }
    SettingsPanel .field-desc {
        color: $text-muted;
        text-style: italic;
        padding-left: 2;
        margin-bottom: 0;
    }
    SettingsPanel .panel-footer {
        margin-top: 1;
        color: $text-muted;
    }
    SettingsPanel Switch {
        width: auto;
        height: auto;
        border: none;
        padding: 0 1;
    }
    SettingsPanel Input {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0;
    }
    SettingsPanel Input:focus {
        border: none;
    }
    SettingsPanel Select {
        width: 1fr;
    }
    """

    class Saved(Message):
        """Posted when user saves settings (Enter)."""

        def __init__(self, values: dict) -> None:
            self.values = values
            super().__init__()

    class Cancelled(Message):
        """Posted when user cancels settings (Escape)."""

    def __init__(self, initial_values: dict | None = None) -> None:
        super().__init__()
        self._initial_values = initial_values or {}

    def compose(self) -> ComposeResult:
        p = cc_dump.palette.PALETTE
        yield Static("Settings", classes="panel-title")

        for field in SETTINGS_FIELDS:
            value = self._initial_values.get(field.key, field.default)
            with Horizontal(classes="field-row"):
                yield Label(field.label, classes="field-label")
                yield _make_widget(field, value)
            yield Static(field.description, classes="field-desc")

        yield Static(
            "[bold {info}]Tab[/] next  [bold {info}]Enter[/] save  [bold {info}]Esc[/] cancel".format(
                info=p.info
            ),
            classes="panel-footer",
        )

    def on_mount(self) -> None:
        """Focus first input widget on mount (standard Textual pattern)."""
        focusable = self.query("Input, Switch, Select, OptionList")
        if focusable:
            focusable.first().focus()

    def collect_values(self) -> dict:
        """Read current widget values into a dict keyed by field key."""
        result = {}
        for field in SETTINGS_FIELDS:
            widget = self.query_one("#field-{}".format(field.key))
            if field.kind == "text":
                result[field.key] = widget.value
            elif field.kind == "bool":
                result[field.key] = widget.value
            else:  # select
                result[field.key] = widget.value
        return result

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in any Input triggers save."""
        event.stop()
        self.post_message(self.Saved(self.collect_values()))

    def on_key(self, event) -> None:
        """Handle panel-level keys."""
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self.post_message(self.Cancelled())
        elif event.key == "enter":
            # Enter outside an Input (e.g. on a Switch) also saves
            event.stop()
            event.prevent_default()
            self.post_message(self.Saved(self.collect_values()))

    def get_state(self) -> dict:
        return {}

    def restore_state(self, state: dict) -> None:
        pass


def create_settings_panel(initial_values: dict | None = None) -> SettingsPanel:
    """Create a new SettingsPanel instance."""
    return SettingsPanel(initial_values=initial_values)
