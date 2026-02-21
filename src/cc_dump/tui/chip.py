"""Reusable chip widgets — lightweight clickable text controls.

This module is STABLE (never hot-reloaded). Other reloadable modules
can safely use `from cc_dump.tui.chip import Chip, ToggleChip`.
"""

from textual.widgets import Static


class Chip(Static):
    """Clickable chip that dispatches an app action on click.

    Like Button's action= parameter but renders as plain text — no borders,
    no half-block chrome. Gets proper :hover CSS support as a real widget.
    """

    ALLOW_SELECT = False

    def __init__(self, label: str, *, action: str | None = None, **kwargs):
        super().__init__(label, **kwargs)
        self._action = action

    async def on_click(self, event) -> None:
        if self._action:
            await self.run_action(self._action)


class ToggleChip(Static):
    """Boolean toggle rendered as a clickable chip.

    Shows label + ON/OFF state inline. Click toggles the value.
    Bold+accent when on, dim when off.
    """

    ALLOW_SELECT = False

    DEFAULT_CSS = """
    ToggleChip {
        width: auto;
        height: 1;
        text-style: bold;
        background: $accent;
        color: $text;
    }

    ToggleChip:hover {
        opacity: 0.8;
    }

    ToggleChip.-off {
        text-style: initial;
        opacity: 0.5;
        background: transparent;
    }

    ToggleChip.-off:hover {
        opacity: 0.7;
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

    async def on_click(self, event) -> None:
        self.value = not self.value
        self._refresh_label()
