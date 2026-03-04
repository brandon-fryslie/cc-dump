"""Reusable chip widgets — lightweight clickable text controls.

This module is RELOADABLE. It appears in _RELOAD_ORDER before its
consumers (custom_footer, settings_panel, side_channel_panel).
"""

from snarfx import Observable, reaction
from textual.widgets import Static


class Chip(Static):
    """Clickable chip that dispatches an app action on click.

    Like Button's action= parameter but renders as compact text with strong
    background/hover affordance. Gets proper :hover CSS support as a real widget.
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
        background: $surface-darken-1;
    }

    Chip:focus {
        text-style: bold underline;
        background: $surface-darken-1;
    }

    Chip.-dim {
        text-style: bold;
        background: $surface-lighten-1;
        color: $text-muted;
    }

    Chip.-dim:hover {
        background: $surface-darken-1;
    }

    Chip.-hidden {
        text-style: bold;
        background: $surface;
        color: $text-muted;
    }

    Chip.-hidden:hover {
        background: $surface-darken-1;
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
        background: $surface-darken-1;
    }

    ToggleChip:focus {
        text-style: bold underline;
        background: $surface-darken-1;
    }

    ToggleChip.-off {
        text-style: bold;
        background: $surface-lighten-1;
        color: $text-muted;
    }

    ToggleChip.-off:hover {
        background: $surface-darken-1;
    }

    ToggleChip.-off:focus {
        text-style: bold underline;
        background: $surface-darken-1;
    }
    """

    def __init__(self, label: str, *, value: bool = False, **kwargs):
        super().__init__("", **kwargs)
        self._base_label = label
        self._value = Observable(bool(value))
        # [LAW:single-enforcer] One reactive projection owns ToggleChip label/CSS state.
        self._value_reaction = reaction(
            lambda: self._value.get(),
            self._render_value,
            fire_immediately=True,
        )

    @property
    def value(self) -> bool:
        return bool(self._value.get())

    @value.setter
    def value(self, value: bool) -> None:
        self._value.set(bool(value))

    def _render_value(self, value: bool) -> None:
        self.update(f" {self._base_label}  {'ON' if value else 'OFF'} ")
        self.set_class(not value, "-off")

    def _toggle(self) -> None:
        self.value = not self.value

    def on_unmount(self) -> None:
        self._value_reaction.dispose()

    async def on_click(self, event) -> None:
        self._toggle()

    def on_key(self, event) -> None:
        if event.key == "space":
            event.stop()
            event.prevent_default()
            self._toggle()
