"""Compact inline cycle selectors.

Single-select (CycleSelector) and multi-select (MultiCycleSelector) variants.
Both render as a compact single line when blurred and expand into a vertical
option list when focused.

This module is RELOADABLE. It appears in _RELOAD_ORDER right after
cc_dump.tui.chip (same dependency profile: nothing).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import ClassVar

from snarfx import Observable, reaction
from rich.style import Style
from rich.text import Text
from textual.message import Message
from textual.widget import Widget

_ZONE_PREV = 0
_ZONE_CENTER = 1
_ZONE_NEXT = 2

_ARROW_PREV = "▾"
_ARROW_NEXT = "▴"
_CHECKMARK = "✓"


def _normalize_options(options: Sequence[str]) -> tuple[str, ...]:
    return tuple(options) if options else ("",)


def _wrap_index(index: int, size: int) -> int:
    return index % size


def _line_click_zone(x: int, line_length: int) -> int:
    if x < 3:
        return _ZONE_PREV
    if x >= line_length - 3:
        return _ZONE_NEXT
    return _ZONE_CENTER


@dataclass(frozen=True)
class CycleSelectorState:
    options: tuple[str, ...]
    index: int = 0
    cursor: int = 0
    editing: bool = False


def _initial_cycle_selector_state(
    options: Sequence[str],
    value: str | None,
) -> CycleSelectorState:
    """Build initial reactive state from options/value inputs.

    # [LAW:one-source-of-truth] Option normalization and initial selection live here.
    """
    normalized = _normalize_options(options)
    index = normalized.index(value) if value is not None and value in normalized else 0
    return CycleSelectorState(options=normalized, index=index, cursor=index)


class CycleSelector(Widget, can_focus=True):
    """Compact inline single-select option selector."""

    ALLOW_SELECT: ClassVar[bool] = False

    DEFAULT_CSS = """
    CycleSelector {
        width: auto;
        height: auto;
        min-height: 1;
        text-style: bold;
        background: $panel-lighten-2;
        color: $text;
    }

    CycleSelector:hover {
        background: $surface-darken-1;
    }

    CycleSelector:focus {
        background: $surface-darken-1;
    }

    CycleSelector.-editing {
        background: $accent;
        color: $text;
    }
    """

    class Changed(Message):
        """Posted when the selected value changes."""

        def __init__(
            self, cycle_selector: CycleSelector, value: str, index: int
        ) -> None:
            self.cycle_selector = cycle_selector
            self.value = value
            self.index = index
            super().__init__()

        @property
        def control(self) -> CycleSelector:
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
        self._state: Observable[CycleSelectorState] = Observable(
            _initial_cycle_selector_state(options, value)
        )
        self._state_reaction = reaction(
            lambda: self._state.get(),
            self._apply_state,
            fire_immediately=False,
        )

    def on_unmount(self) -> None:
        self._state_reaction.dispose()

    def _apply_state(self, _state: CycleSelectorState) -> None:
        self.refresh()

    @property
    def _options(self) -> list[str]:
        return list(self._state.get().options)

    @_options.setter
    def _options(self, value: Sequence[str]) -> None:
        state = self._state.get()
        options = _normalize_options(value)
        index = min(state.index, len(options) - 1)
        self._state.set(replace(state, options=options, index=index, cursor=index))

    @property
    def _index(self) -> int:
        return self._state.get().index

    @_index.setter
    def _index(self, value: int) -> None:
        self._set_index(int(value))

    @property
    def _cursor(self) -> int:
        return self._state.get().cursor

    @_cursor.setter
    def _cursor(self, value: int) -> None:
        state = self._state.get()
        self._state.set(replace(state, cursor=_wrap_index(int(value), len(state.options))))

    @property
    def _editing(self) -> bool:
        return self._state.get().editing

    @_editing.setter
    def _editing(self, value: bool) -> None:
        state = self._state.get()
        cursor = state.index if value else state.cursor
        self._state.set(replace(state, editing=bool(value), cursor=cursor))

    @property
    def value(self) -> str:
        state = self._state.get()
        return state.options[state.index]

    @value.setter
    def value(self, new_value: str) -> None:
        state = self._state.get()
        self._state.set(
            replace(
                state,
                index=state.options.index(new_value),
                cursor=state.options.index(new_value),
            )
        )

    @property
    def index(self) -> int:
        return self._state.get().index

    @index.setter
    def index(self, new_index: int) -> None:
        self._set_index(new_index)

    def set_options(self, options: Sequence[str], *, value: str | None = None) -> None:
        """Replace options list and selected value."""
        normalized = _normalize_options(options)
        index = normalized.index(value) if value is not None and value in normalized else 0
        self._state.set(
            CycleSelectorState(
                options=normalized,
                index=index,
                cursor=index,
                editing=False,
            )
        )

    def _set_index(self, new_index: int) -> None:
        state = self._state.get()
        next_index = _wrap_index(new_index, len(state.options))
        next_state = replace(state, index=next_index, cursor=next_index)
        self._state.set(next_state)
        if next_index != state.index:
            self.post_message(self.Changed(self, next_state.options[next_index], next_index))

    def _move_selection(self, delta: int) -> None:
        state = self._state.get()
        self._set_index(state.index + delta)

    def _select_row(self, row: int) -> None:
        self._set_index(row)

    def _expanded(self) -> bool:
        return self.has_focus or self._state.get().editing

    def _active_line(self, label: str) -> str:
        return f" {_ARROW_PREV} {label} {_ARROW_NEXT} "

    def _inactive_line(self, label: str) -> str:
        return f"   {label}   "

    def _zone_boundaries(self, label: str | None = None) -> tuple[int, int]:
        active_label = self.value if label is None else label
        line_length = len(self._active_line(active_label))
        return 3, line_length - 3

    def render(self) -> Text:
        """Render the widget as a single line or expanded vertical option list.

        # [LAW:dataflow-not-control-flow] exception: focus intentionally changes the
        # rendered structure to match standard select affordances.
        """
        state = self._state.get()
        expanded = self._expanded()
        text = Text()

        if not expanded:
            text.append(self._active_line(state.options[state.index]))
            self.set_class(False, "-editing")
            return text

        self.set_class(True, "-editing")
        for row, option in enumerate(state.options):
            line = (
                self._active_line(option)
                if row == state.cursor
                else self._inactive_line(option)
            )
            style = Style(reverse=row == state.cursor, bold=row == state.index)
            text.append(line, style=style)
            if row < len(state.options) - 1:
                text.append("\n")
        return text

    def on_focus(self, _event) -> None:
        state = self._state.get()
        self._state.set(replace(state, editing=True, cursor=state.index))

    def on_blur(self, _event) -> None:
        state = self._state.get()
        self._state.set(replace(state, editing=False, cursor=state.index))

    def on_click(self, event) -> None:
        if self.disabled:
            return

        if not self._expanded():
            zone = _line_click_zone(event.x, len(self._active_line(self.value)))
            if zone == _ZONE_PREV:
                self._move_selection(-1)
            elif zone == _ZONE_NEXT:
                self._move_selection(+1)
            return

        state = self._state.get()
        row = max(0, min(int(event.y), len(state.options) - 1))
        if row == state.cursor:
            zone = _line_click_zone(event.x, len(self._active_line(state.options[row])))
            if zone == _ZONE_PREV:
                self._move_selection(-1)
                return
            if zone == _ZONE_NEXT:
                self._move_selection(+1)
                return
        self._select_row(row)

    def on_key(self, event) -> None:
        if self.disabled:
            return

        key = event.key
        if key not in ("up", "down", "enter", "space"):
            return

        event.stop()
        event.prevent_default()

        if key == "up":
            self._move_selection(-1)
        elif key == "down":
            self._move_selection(+1)
        else:
            self._select_row(self._state.get().cursor)


class MultiCycleSelector(Widget, can_focus=True):
    """Compact inline multi-select option selector."""

    ALLOW_SELECT: ClassVar[bool] = False

    DEFAULT_CSS = """
    MultiCycleSelector {
        width: auto;
        height: auto;
        min-height: 1;
        text-style: bold;
        background: $panel-lighten-2;
        color: $text;
    }

    MultiCycleSelector:hover {
        background: $surface-darken-1;
    }

    MultiCycleSelector:focus {
        background: $surface-darken-1;
    }

    MultiCycleSelector.-editing {
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
        """Posted when the selection set changes."""

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
        self._options: list[str] = list(options) or [""]
        self._selected: set[int] = (
            {self._options.index(value) for value in values if value in self._options}
            if values
            else set()
        )
        self._cursor: int = min(self._selected) if self._selected else 0
        self._editing: bool = False

    @property
    def values(self) -> frozenset[str]:
        return frozenset(self._options[index] for index in self._selected)

    @property
    def indices(self) -> frozenset[int]:
        return frozenset(self._selected)

    def _expanded(self) -> bool:
        return self.has_focus or self._editing

    def _collapsed_line(self) -> str:
        selected_names = [self._options[index] for index in sorted(self._selected)]
        display = ", ".join(selected_names) if selected_names else "(none)"
        return f" {_ARROW_PREV} {display} {_ARROW_NEXT} "

    def _row_line(self, row: int) -> str:
        marker = _CHECKMARK if row in self._selected else " "
        label = self._options[row]
        if row == self._cursor:
            return f" {_ARROW_PREV} {marker} {label} {_ARROW_NEXT} "
        return f"   {marker} {label}   "

    def _set_cursor(self, index: int) -> None:
        self._cursor = _wrap_index(index, len(self._options))
        self.refresh()

    def _move_cursor(self, delta: int) -> None:
        self._set_cursor(self._cursor + delta)

    def _emit_changed(self) -> None:
        self.post_message(self.Changed(self, self.values, self.indices))

    def _toggle_index(self, index: int) -> None:
        if index in self._selected:
            self._selected.discard(index)
        else:
            self._selected.add(index)
        self._cursor = index
        self.refresh()
        self._emit_changed()

    def _select_index(self, index: int) -> None:
        if index in self._selected:
            self._cursor = index
            self.refresh()
            return
        self._selected.add(index)
        self._cursor = index
        self.refresh()
        self._emit_changed()

    def render(self) -> Text:
        """Render the widget as collapsed summary or expanded option list.

        # [LAW:dataflow-not-control-flow] exception: focus intentionally changes the
        # rendered structure to match standard select affordances.
        """
        text = Text()
        expanded = self._expanded()
        self.set_class(expanded, "-editing")
        self.set_class(expanded and self._cursor in self._selected, "-selected")

        if not expanded:
            text.append(self._collapsed_line())
            return text

        for row in range(len(self._options)):
            style = Style(reverse=row == self._cursor, bold=row in self._selected)
            text.append(self._row_line(row), style=style)
            if row < len(self._options) - 1:
                text.append("\n")
        return text

    def on_focus(self, _event) -> None:
        self._editing = True
        self.refresh()

    def on_blur(self, _event) -> None:
        self._editing = False
        self.refresh()

    def on_click(self, event) -> None:
        if self.disabled:
            return

        if not self._expanded():
            return

        row = max(0, min(int(event.y), len(self._options) - 1))
        if row == self._cursor:
            zone = _line_click_zone(event.x, len(self._row_line(row)))
            if zone == _ZONE_PREV:
                self._move_cursor(-1)
                return
            if zone == _ZONE_NEXT:
                self._move_cursor(+1)
                return
        self._toggle_index(row)

    def on_key(self, event) -> None:
        if self.disabled:
            return

        key = event.key
        if key not in ("up", "down", "enter", "space"):
            return

        event.stop()
        event.prevent_default()

        if key == "up":
            self._move_cursor(-1)
        elif key == "down":
            self._move_cursor(+1)
        elif key == "space":
            self._toggle_index(self._cursor)
        else:
            self._select_index(self._cursor)
