"""Reusable chip widgets — lightweight clickable text controls.

This module is RELOADABLE. It appears in _RELOAD_ORDER before its
consumers (custom_footer, settings_panel, side_channel_panel).
"""

from textual.widgets import Static


class Chip(Static):
    """Clickable chip that dispatches an app action on click.

    Like Button's action= parameter but renders as plain text — no borders,
    no half-block chrome. Gets proper :hover CSS support as a real widget.
    """

    ALLOW_SELECT = False
    DEFAULT_CSS = """
    Chip {
        width: auto;
        height: 1;
        text-style: bold;
        background: $panel-lighten-2;
        color: $text;
    }

    Chip:hover {
        background: $panel-lighten-1;
        color: $text;
    }

    Chip:focus {
        text-style: bold underline;
        background: $panel-lighten-1;
        color: $text;
    }

    Chip.-dim {
        text-style: bold;
        background: $surface-lighten-1;
        color: $text-muted;
    }

    Chip.-dim:hover {
        background: $surface-lighten-2;
        color: $text;
    }

    Chip.-hidden {
        text-style: bold;
        background: $surface;
        color: $text-muted;
    }

    Chip.-hidden:hover {
        background: $surface-lighten-1;
        color: $text;
    }
    """

    def __init__(self, label: str, *, action: str | None = None, **kwargs):
        super().__init__(label, **kwargs)
        self._action = action

    async def on_click(self, event) -> None:
        if self._action:
            await self.run_action(self._action)


class ToggleChip(Static):
    """Boolean toggle rendered as a clickable chip.

    Shows label + ON/OFF state inline. Click or Space toggles the value.
    Bold+accent when on, dim when off. Focusable for Tab navigation.
    """

    ALLOW_SELECT = False
    can_focus = True

    DEFAULT_CSS = """
    ToggleChip {
        width: auto;
        height: 1;
        text-style: bold;
        background: $accent;
        color: $text;
    }

    ToggleChip:hover {
        background: $primary;
        color: $text;
    }

    ToggleChip:focus {
        text-style: bold underline;
        background: $primary;
        color: $text;
    }

    ToggleChip.-off {
        text-style: bold;
        background: $surface-lighten-1;
        color: $text-muted;
    }

    ToggleChip.-off:hover {
        background: $surface-lighten-2;
        color: $text;
    }

    ToggleChip.-off:focus {
        text-style: bold underline;
        background: $surface-lighten-2;
        color: $text;
    }
    """

    def __init__(self, label: str, *, value: bool = False, **kwargs):
        super().__init__("", **kwargs)
        self._base_label = label
        self.value = value
        self._refresh_label()

    def _refresh_label(self):
        self.update(f" {self._base_label}  {'ON' if self.value else 'OFF'} ")
        self.set_class(not self.value, "-off")

    def _toggle(self) -> None:
        self.value = not self.value
        self._refresh_label()

    async def on_click(self, event) -> None:
        self._toggle()

    def on_key(self, event) -> None:
        if event.key == "space":
            event.stop()
            event.prevent_default()
            self._toggle()
