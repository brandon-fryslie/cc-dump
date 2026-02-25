"""Shared form panel infrastructure for settings-style side panels.

This module is RELOADABLE.

// [LAW:one-type-per-behavior] One generic settings form panel type powers both app and proxy settings UIs.
// [LAW:locality-or-seam] Panel-specific modules provide only field descriptors + title; form behavior is centralized here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.widgets import Input, Label, Select, Static

import cc_dump.core.palette
import cc_dump.tui.rendering
from cc_dump.tui.chip import ToggleChip


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    description: str
    kind: Literal["text", "bool", "select"]
    default: str | bool = ""
    options: tuple[str, ...] = ()
    secret: bool = False


def build_initial_values(fields: Sequence[FieldDef], settings_store) -> dict[str, object]:
    values: dict[str, object] = {}
    for field in fields:
        stored = settings_store.get(field.key) if settings_store is not None else None
        values[field.key] = stored if stored is not None else field.default
    return values


class SettingsFormPanel(VerticalScroll):
    """Generic side panel for editing a set of fields and posting save/cancel messages."""

    DEFAULT_CSS = """
    .settings-form {
        dock: right;
        width: 35%;
        min-width: 30;
        max-width: 50;
        border-left: solid $primary-muted;
        padding: 0 1;
        height: 1fr;
        background: $panel;
        color: $text;
    }
    .settings-form .panel-title {
        text-style: bold;
        margin-bottom: 0;
        color: $text-primary;
    }
    .settings-form .field-row {
        height: auto;
        width: 100%;
        margin-top: 1;
    }
    .settings-form .field-label {
        width: 1fr;
        text-style: bold;
        content-align-vertical: middle;
        color: $text-secondary;
    }
    .settings-form .field-desc {
        color: $text-muted;
        text-style: italic;
        padding-left: 2;
        margin-bottom: 0;
    }
    .settings-form .panel-footer {
        margin-top: 1;
        color: $text-muted;
        background: $panel-darken-1;
        padding: 0 1;
    }
    .settings-form ToggleChip {
        margin-top: 1;
    }
    .settings-form Input {
        width: 1fr;
        height: 1;
        border: round $border;
        padding: 0;
        background: $surface;
        color: $text;
    }
    .settings-form Input:focus {
        border: round $primary;
        background: $surface-lighten-1;
    }
    .settings-form Select {
        width: 1fr;
        background: $surface;
        color: $text;
        border: round $border;
    }
    .settings-form Select:focus {
        border: round $primary;
    }
    """

    class Saved(Message):
        """Posted when user saves form values."""

        def __init__(self, panel_key: str, values: dict[str, object]) -> None:
            self.panel_key = panel_key
            self.values = values
            super().__init__()

    class Cancelled(Message):
        """Posted when user cancels panel editing."""

        def __init__(self, panel_key: str) -> None:
            self.panel_key = panel_key
            super().__init__()

    def __init__(
        self,
        *,
        panel_key: str,
        title: str,
        fields: Sequence[FieldDef],
        initial_values: dict | None = None,
    ) -> None:
        super().__init__()
        self._panel_key = panel_key
        self._title = title
        self._fields = tuple(fields)
        self._initial_values = initial_values or {}
        self.add_class("settings-form")

    def _widget_id(self, field_key: str) -> str:
        return "{}-field-{}".format(self._panel_key, field_key)

    def _make_widget(self, field: FieldDef, value: object) -> Input | ToggleChip | Select:
        widget_id = self._widget_id(field.key)
        if field.kind == "text":
            return Input(value=str(value), id=widget_id, password=field.secret)
        if field.kind == "bool":
            return ToggleChip(field.label, value=bool(value), id=widget_id)
        selected = str(value) if value else field.default
        options = [(opt or "(none)", opt) for opt in field.options]
        return Select(options, value=selected, allow_blank=False, id=widget_id)

    def compose(self) -> ComposeResult:
        try:
            info_color = cc_dump.tui.rendering.get_theme_colors().info
        except RuntimeError:
            info_color = cc_dump.core.palette.PALETTE.info
        yield Static(self._title, classes="panel-title")

        for field in self._fields:
            value = self._initial_values.get(field.key, field.default)
            widget = self._make_widget(field, value)
            if field.kind == "bool":
                yield widget
            else:
                with Horizontal(classes="field-row"):
                    yield Label(field.label, classes="field-label")
                    yield widget
            yield Static(field.description, classes="field-desc")

        yield Static(
            "[bold {info}]Tab[/] next  [bold {info}]Enter[/] save  [bold {info}]Esc[/] cancel".format(
                info=info_color
            ),
            classes="panel-footer",
        )

    def on_mount(self) -> None:
        focusable = self.query("Input, Select, OptionList, ToggleChip")
        if focusable:
            focusable.first().focus()

    def collect_values(self) -> dict[str, object]:
        values: dict[str, object] = {}
        for field in self._fields:
            widget = self.query_one("#{}".format(self._widget_id(field.key)))
            if field.kind == "text":
                values[field.key] = widget.value
            elif field.kind == "bool":
                values[field.key] = widget.value
            else:
                values[field.key] = widget.value
        return values

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.post_message(self.Saved(self._panel_key, self.collect_values()))

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self.post_message(self.Cancelled(self._panel_key))
        elif event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Saved(self._panel_key, self.collect_values()))

    def get_state(self) -> dict:
        return {}

    def restore_state(self, state: dict) -> None:
        return
