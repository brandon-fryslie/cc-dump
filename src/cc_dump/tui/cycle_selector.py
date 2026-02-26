"""Compact inline cycle selectors — space-efficient dropdown alternatives.

Single-select (CycleSelector) and multi-select (MultiCycleSelector) variants.
Both render as ▾ value ▴ with two-state editing behavior.

This module is RELOADABLE. It appears in _RELOAD_ORDER right after
cc_dump.tui.chip (same dependency profile: nothing).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

from rich.style import Style
from rich.text import Text
from textual.message import Message
from textual.widget import Widget

# ---------------------------------------------------------------------------
# Zone constants — internal focus zones within editing mode
# ---------------------------------------------------------------------------
_ZONE_PREV = 0
_ZONE_CENTER = 1
_ZONE_NEXT = 2

# Arrow characters
_ARROW_PREV = "\u25be"  # ▾ (down-pointing small triangle)
_ARROW_NEXT = "\u25b4"  # ▴ (up-pointing small triangle)

# [LAW:dataflow-not-control-flow] Zone activation deltas as data.
# Center delta=0 is a sentinel: single-select exits editing, multi-select toggles.
_ZONE_DELTAS: dict[int, int] = {
    _ZONE_PREV: -1,
    _ZONE_CENTER: 0,
    _ZONE_NEXT: +1,
}


# ═══════════════════════════════════════════════════════════════════════════
# CycleSelector — single-select
# ═══════════════════════════════════════════════════════════════════════════


class CycleSelector(Widget, can_focus=True):
    """Compact inline single-select option selector with cycling behavior.

    Three zones: prev arrow (▾), current value, next arrow (▴).
    Two modes: non-editing (single focusable unit) and editing
    (internal zone navigation with arrow keys).

    // [LAW:one-source-of-truth] _options is the canonical option list.
    // _index is the canonical selected index. .value is derived.
    """

    ALLOW_SELECT: ClassVar[bool] = False

    DEFAULT_CSS = """
    CycleSelector {
        width: auto;
        height: 1;
        text-style: bold;
        background: $panel-lighten-2;
        color: $text;
    }

    CycleSelector:hover {
        background: $surface-darken-1;
    }

    CycleSelector:focus {
        text-style: bold underline;
        background: $surface-darken-1;
    }

    CycleSelector.-editing {
        text-style: bold;
        background: $accent;
        color: $text;
    }
    """

    class Changed(Message):
        """Posted when the selected value changes (on prev/next activation).

        Attributes:
            cycle_selector: The CycleSelector that changed.
            value: The new selected value.
            index: The new selected index.
        """

        def __init__(
            self, cycle_selector: CycleSelector, value: str, index: int
        ) -> None:
            self.cycle_selector = cycle_selector
            self.value = value
            self.index = index
            super().__init__()

        @property
        def control(self) -> CycleSelector:
            """The CycleSelector widget that posted this message."""
            return self.cycle_selector

    def __init__(
        self,
        options: Sequence[str],
        *,
        value: str | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
        tooltip: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        if tooltip is not None:
            self.tooltip = tooltip
        # [LAW:one-source-of-truth] _options is the canonical option list.
        self._options: list[str] = list(options)
        # [LAW:one-source-of-truth] _index is the canonical selected index.
        self._index: int = (
            self._options.index(value)
            if value is not None and value in self._options
            else 0
        )
        self._editing: bool = False
        self._zone: int = _ZONE_CENTER

    # -- Properties ----------------------------------------------------------

    @property
    def value(self) -> str:
        """Current selected option value."""
        return self._options[self._index]

    @value.setter
    def value(self, new_value: str) -> None:
        """Set value programmatically. Raises ValueError if not in options."""
        self._index = self._options.index(new_value)
        self.refresh()

    @property
    def index(self) -> int:
        """Current selected index."""
        return self._index

    @index.setter
    def index(self, new_index: int) -> None:
        """Set index programmatically (wraps around)."""
        self._index = new_index % len(self._options)
        self.refresh()

    # -- Rendering -----------------------------------------------------------

    def render(self) -> Text:
        """Render the widget as a Rich Text with zone-specific styling.

        // [LAW:dataflow-not-control-flow] Always builds all 3 zones.
        // Editing varies the styling, not the structure.
        """
        val = self._options[self._index]
        parts = [f" {_ARROW_PREV} ", f" {val} ", f" {_ARROW_NEXT} "]

        text = Text()
        reverse = Style(reverse=True)
        for i, part in enumerate(parts):
            style = reverse if (self._editing and i == self._zone) else Style.null()
            text.append(part, style=style)

        self.set_class(self._editing, "-editing")
        return text

    # -- Zone management -----------------------------------------------------

    def _zone_boundaries(self) -> tuple[int, int]:
        """Return (prev_end, next_start) x-offsets for click zone detection.

        // [LAW:one-source-of-truth] Boundaries derived from content lengths.
        """
        prev_width = 3  # " ▾ "
        center_width = len(self._options[self._index]) + 2  # " value "
        return prev_width, prev_width + center_width

    def _move_zone(self, delta: int) -> None:
        """Move internal focus zone by delta, clamping to valid range."""
        self._zone = max(_ZONE_PREV, min(_ZONE_NEXT, self._zone + delta))
        self.refresh()

    def _activate_zone(self, zone: int) -> None:
        """Activate a zone: cycle prev/next or confirm center.

        // [LAW:dataflow-not-control-flow] _ZONE_DELTAS drives behavior.
        """
        delta = _ZONE_DELTAS[zone]
        old_index = self._index

        self._index = (self._index + delta) % len(self._options)
        # delta==0 means center (confirm) → exit editing
        self._editing = self._editing and delta != 0

        self.refresh()

        if self._index != old_index:
            self.post_message(self.Changed(self, self.value, self._index))

    def _enter_editing(self) -> None:
        """Enter editing mode, starting with center zone focused."""
        self._editing = True
        self._zone = _ZONE_CENTER
        self.refresh()

    def _exit_editing(self) -> None:
        """Exit editing mode."""
        self._editing = False
        self.refresh()

    # -- Event handlers ------------------------------------------------------

    def on_click(self, event) -> None:
        """Handle click: enter editing or activate zone."""
        if self.disabled:
            return

        prev_end, next_start = self._zone_boundaries()
        zone = (
            _ZONE_PREV
            if event.x < prev_end
            else _ZONE_NEXT
            if event.x >= next_start
            else _ZONE_CENTER
        )

        if not self._editing:
            self._zone = zone
            self._editing = True
            self.refresh()
        else:
            self._activate_zone(zone)

    def on_key(self, event) -> None:
        """Handle keyboard: Enter/Space toggle editing, arrows navigate zones."""
        if self.disabled:
            return

        if not self._editing:
            if event.key in ("enter", "space"):
                event.stop()
                event.prevent_default()
                self._enter_editing()
            return

        # Editing mode — consume all handled keys
        key = event.key
        if key in ("left", "right", "enter", "space", "escape"):
            event.stop()
            event.prevent_default()

        if key == "left":
            self._move_zone(-1)
        elif key == "right":
            self._move_zone(+1)
        elif key in ("enter", "space"):
            self._activate_zone(self._zone)
        elif key == "escape":
            self._exit_editing()


# ═══════════════════════════════════════════════════════════════════════════
# MultiCycleSelector — multi-select
# ═══════════════════════════════════════════════════════════════════════════


class MultiCycleSelector(Widget, can_focus=True):
    """Compact inline multi-select option selector with cycling behavior.

    Non-editing: shows comma-joined selected values.
    Editing: shows current cursor item with selection indicator (✓ / space).
    Center activates toggle, Escape exits editing.

    // [LAW:one-source-of-truth] _options is the canonical option list.
    // _selected (set of indices) is the canonical selection state.
    """

    ALLOW_SELECT: ClassVar[bool] = False

    DEFAULT_CSS = """
    MultiCycleSelector {
        width: auto;
        height: 1;
        text-style: bold;
        background: $panel-lighten-2;
        color: $text;
    }

    MultiCycleSelector:hover {
        background: $surface-darken-1;
    }

    MultiCycleSelector:focus {
        text-style: bold underline;
        background: $surface-darken-1;
    }

    MultiCycleSelector.-editing {
        text-style: bold;
        background: $accent;
        color: $text;
    }

    MultiCycleSelector.-selected {
        text-style: bold;
        background: $accent-lighten-2;
        color: $text;
    }
    """

    class Changed(Message):
        """Posted when the selection set changes (on center toggle).

        Attributes:
            multi_cycle_selector: The MultiCycleSelector that changed.
            values: The new set of selected values.
            indices: The new set of selected indices.
        """

        def __init__(
            self,
            multi_cycle_selector: MultiCycleSelector,
            values: frozenset[str],
            indices: frozenset[int],
        ) -> None:
            self.multi_cycle_selector = multi_cycle_selector
            self.values = values
            self.indices = indices
            super().__init__()

        @property
        def control(self) -> MultiCycleSelector:
            """The MultiCycleSelector widget that posted this message."""
            return self.multi_cycle_selector

    def __init__(
        self,
        options: Sequence[str],
        *,
        values: set[str] | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
        tooltip: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        if tooltip is not None:
            self.tooltip = tooltip
        self._options: list[str] = list(options)
        # [LAW:one-source-of-truth] _selected is the canonical selection state.
        self._selected: set[int] = (
            {self._options.index(v) for v in values if v in self._options}
            if values
            else set()
        )
        self._cursor: int = 0
        self._editing: bool = False
        self._zone: int = _ZONE_CENTER

    # -- Properties ----------------------------------------------------------

    @property
    def values(self) -> frozenset[str]:
        """Set of currently selected option values."""
        return frozenset(self._options[i] for i in self._selected)

    @property
    def indices(self) -> frozenset[int]:
        """Set of currently selected indices."""
        return frozenset(self._selected)

    # -- Rendering -----------------------------------------------------------

    def render(self) -> Text:
        """Render the widget.

        Non-editing: ▾ Alpha, Beta ▴ (comma-joined selected)
        Editing: ▾ ✓ Alpha ▴ (cursor item with selection indicator)
        """
        center = self._render_center()
        parts = [f" {_ARROW_PREV} ", center, f" {_ARROW_NEXT} "]

        text = Text()
        reverse = Style(reverse=True)
        for i, part in enumerate(parts):
            style = reverse if (self._editing and i == self._zone) else Style.null()
            text.append(part, style=style)

        self.set_class(self._editing, "-editing")
        self.set_class(
            self._editing and self._cursor in self._selected, "-selected"
        )
        return text

    def _render_center(self) -> str:
        """Build the center zone text content."""
        if not self._editing:
            # Non-editing: comma-joined selected values
            selected_names = [
                self._options[i]
                for i in sorted(self._selected)
            ]
            display = ", ".join(selected_names) if selected_names else "(none)"
            return f" {display} "

        # Editing: show cursor item with selection indicator
        name = self._options[self._cursor]
        marker = "\u2713" if self._cursor in self._selected else " "  # ✓ or space
        return f" {marker} {name} "

    # -- Zone management -----------------------------------------------------

    def _zone_boundaries(self) -> tuple[int, int]:
        """Return (prev_end, next_start) x-offsets for click zone detection."""
        prev_width = 3  # " ▾ "
        center_text = self._render_center()
        return prev_width, prev_width + len(center_text)

    def _move_zone(self, delta: int) -> None:
        """Move internal focus zone by delta, clamping."""
        self._zone = max(_ZONE_PREV, min(_ZONE_NEXT, self._zone + delta))
        self.refresh()

    def _activate_zone(self, zone: int) -> None:
        """Activate a zone: cycle cursor or toggle selection.

        // [LAW:dataflow-not-control-flow] _ZONE_DELTAS drives cursor movement.
        // Center (delta==0) toggles selection instead of exiting.
        """
        delta = _ZONE_DELTAS[zone]

        if delta != 0:
            # Prev/Next: move cursor through options
            self._cursor = (self._cursor + delta) % len(self._options)
        else:
            # Center: toggle selection of current cursor item
            if self._cursor in self._selected:
                self._selected.discard(self._cursor)
            else:
                self._selected.add(self._cursor)
            self.post_message(self.Changed(self, self.values, self.indices))

        self.refresh()

    def _enter_editing(self) -> None:
        """Enter editing mode, cursor starts at first option."""
        self._editing = True
        self._cursor = 0
        self._zone = _ZONE_CENTER
        self.refresh()

    def _exit_editing(self) -> None:
        """Exit editing mode (keeps current selections)."""
        self._editing = False
        self.refresh()

    # -- Event handlers ------------------------------------------------------

    def on_click(self, event) -> None:
        """Handle click: enter editing or activate zone."""
        if self.disabled:
            return

        prev_end, next_start = self._zone_boundaries()
        zone = (
            _ZONE_PREV
            if event.x < prev_end
            else _ZONE_NEXT
            if event.x >= next_start
            else _ZONE_CENTER
        )

        if not self._editing:
            self._zone = zone
            self._editing = True
            self.refresh()
        else:
            self._activate_zone(zone)

    def on_key(self, event) -> None:
        """Handle keyboard: Enter/Space enter editing, Escape exits."""
        if self.disabled:
            return

        if not self._editing:
            if event.key in ("enter", "space"):
                event.stop()
                event.prevent_default()
                self._enter_editing()
            return

        # Editing mode
        key = event.key
        if key in ("left", "right", "enter", "space", "escape"):
            event.stop()
            event.prevent_default()

        if key == "left":
            self._move_zone(-1)
        elif key == "right":
            self._move_zone(+1)
        elif key in ("enter", "space"):
            self._activate_zone(self._zone)
        elif key == "escape":
            self._exit_editing()
