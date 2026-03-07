"""Unit tests for CycleSelector and MultiCycleSelector widgets."""
from unittest.mock import MagicMock

from rich.text import Text

from cc_dump.tui.cycle_selector import (
    CycleSelector,
    MultiCycleSelector,
    _ZONE_CENTER,
    _ZONE_NEXT,
    _ZONE_PREV,
)


class _KeyEvent:
    def __init__(self, key: str) -> None:
        self.key = key
        self.stopped = False
        self.default_prevented = False

    def stop(self) -> None:
        self.stopped = True

    def prevent_default(self) -> None:
        self.default_prevented = True


class _ClickEvent:
    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y


def _mock_post_message(widget: object) -> MagicMock:
    mock = MagicMock()
    object.__setattr__(widget, "post_message", mock)
    return mock


class TestCycleSelectorCSS:
    def test_default_css_has_expanding_height(self):
        css = CycleSelector.DEFAULT_CSS
        assert "height: auto;" in css
        assert "min-height: 1;" in css

    def test_default_css_has_editing_modifier(self):
        css = CycleSelector.DEFAULT_CSS
        assert "CycleSelector.-editing" in css
        assert "background: $accent;" in css


class TestCycleSelectorInit:
    def test_init_defaults_to_first_option(self):
        sel = CycleSelector(["A", "B", "C"])
        assert sel.value == "A"
        assert sel.index == 0
        assert sel._cursor == 0

    def test_init_with_explicit_value(self):
        sel = CycleSelector(["A", "B", "C"], value="B")
        assert sel.value == "B"
        assert sel.index == 1
        assert sel._cursor == 1

    def test_init_unknown_value_defaults_to_first(self):
        sel = CycleSelector(["A", "B", "C"], value="Z")
        assert sel.value == "A"
        assert sel.index == 0


class TestCycleSelectorSelection:
    def test_up_key_wraps_to_end(self):
        sel = CycleSelector(["A", "B", "C"], value="A")
        _mock_post_message(sel)
        sel.on_key(_KeyEvent("up"))
        assert sel.value == "C"
        assert sel.index == 2

    def test_down_key_wraps_to_start(self):
        sel = CycleSelector(["A", "B", "C"], value="C")
        _mock_post_message(sel)
        sel.on_key(_KeyEvent("down"))
        assert sel.value == "A"
        assert sel.index == 0

    def test_enter_keeps_current_selection(self):
        sel = CycleSelector(["A", "B", "C"], value="B")
        post_message = _mock_post_message(sel)
        sel._editing = True
        sel._cursor = 1
        sel.on_key(_KeyEvent("enter"))
        assert sel.value == "B"
        post_message.assert_not_called()

    def test_space_keeps_current_selection(self):
        sel = CycleSelector(["A", "B", "C"], value="B")
        post_message = _mock_post_message(sel)
        sel._editing = True
        sel._cursor = 1
        sel.on_key(_KeyEvent("space"))
        assert sel.value == "B"
        post_message.assert_not_called()

    def test_changed_message_posts_on_arrow_navigation(self):
        sel = CycleSelector(["A", "B", "C"], value="A")
        post_message = _mock_post_message(sel)
        sel.on_key(_KeyEvent("down"))
        msg = post_message.call_args[0][0]
        assert isinstance(msg, CycleSelector.Changed)
        assert msg.value == "B"
        assert msg.index == 1
        assert msg.control is sel

    def test_clicking_current_row_arrows_cycles_selection(self):
        sel = CycleSelector(["A", "B", "C"], value="B")
        _mock_post_message(sel)
        sel._editing = True
        sel._cursor = 1

        sel.on_click(_ClickEvent(0, 1))
        assert sel.value == "A"

        sel.on_click(_ClickEvent(len(sel._active_line("A")) - 1, 0))
        assert sel.value == "B"

    def test_clicking_expanded_row_selects_that_row(self):
        sel = CycleSelector(["A", "B", "C"], value="A")
        _mock_post_message(sel)
        sel._editing = True
        sel.on_click(_ClickEvent(4, 2))
        assert sel.value == "C"
        assert sel.index == 2


class TestCycleSelectorRendering:
    def test_collapsed_render_is_single_line(self):
        sel = CycleSelector(["Alpha", "Beta"], value="Alpha")
        text = sel.render()
        assert isinstance(text, Text)
        assert text.plain == " ▾ Alpha ▴ "

    def test_focused_render_shows_all_options(self):
        sel = CycleSelector(["Alpha", "Beta", "Gamma"], value="Beta")
        sel._editing = True
        text = sel.render()
        assert text.plain == "   Alpha   \n ▾ Beta ▴ \n   Gamma   "

    def test_zone_boundaries_match_active_row(self):
        sel = CycleSelector(["Very Long Option"], value="Very Long Option")
        prev_end, next_start = sel._zone_boundaries()
        assert prev_end == 3
        assert next_start == len(sel._active_line("Very Long Option")) - 3

    def test_render_marks_cursor_row_with_reverse_style(self):
        sel = CycleSelector(["Alpha", "Beta"], value="Beta")
        sel._editing = True
        text = sel.render()
        assert any(span.style and "reverse" in str(span.style) for span in text.spans)


class TestMultiCycleSelectorCSS:
    def test_default_css_has_expanding_height(self):
        css = MultiCycleSelector.DEFAULT_CSS
        assert "height: auto;" in css
        assert "min-height: 1;" in css

    def test_default_css_has_selected_modifier(self):
        css = MultiCycleSelector.DEFAULT_CSS
        assert "MultiCycleSelector.-selected" in css


class TestMultiCycleSelectorInit:
    def test_init_tracks_selected_values(self):
        sel = MultiCycleSelector(["A", "B", "C"], values={"A", "C"})
        assert sel.values == frozenset({"A", "C"})
        assert sel.indices == frozenset({0, 2})

    def test_init_starts_cursor_on_first_selected_value(self):
        sel = MultiCycleSelector(["A", "B", "C"], values={"C", "B"})
        assert sel._cursor == 1


class TestMultiCycleSelectorKeyboard:
    def test_up_and_down_move_cursor_with_wraparound(self):
        sel = MultiCycleSelector(["A", "B", "C"])
        sel._editing = True

        sel.on_key(_KeyEvent("up"))
        assert sel._cursor == 2

        sel.on_key(_KeyEvent("down"))
        assert sel._cursor == 0

    def test_space_toggles_cursor_item(self):
        sel = MultiCycleSelector(["A", "B", "C"])
        sel._editing = True
        sel._cursor = 1
        post_message = _mock_post_message(sel)

        sel.on_key(_KeyEvent("space"))

        assert sel.values == frozenset({"B"})
        msg = post_message.call_args[0][0]
        assert isinstance(msg, MultiCycleSelector.Changed)
        assert msg.values == frozenset({"B"})
        assert msg.indices == frozenset({1})
        assert msg.control is sel

    def test_enter_selects_without_toggling_off(self):
        sel = MultiCycleSelector(["A", "B", "C"], values={"B"})
        sel._editing = True
        sel._cursor = 1
        post_message = _mock_post_message(sel)

        sel.on_key(_KeyEvent("enter"))

        assert sel.values == frozenset({"B"})
        post_message.assert_not_called()

    def test_enter_adds_current_item_when_unselected(self):
        sel = MultiCycleSelector(["A", "B", "C"])
        sel._editing = True
        sel._cursor = 2
        post_message = _mock_post_message(sel)

        sel.on_key(_KeyEvent("enter"))

        assert sel.values == frozenset({"C"})
        msg = post_message.call_args[0][0]
        assert msg.values == frozenset({"C"})
        assert msg.indices == frozenset({2})


class TestMultiCycleSelectorRendering:
    def test_collapsed_render_shows_selected_summary(self):
        sel = MultiCycleSelector(["A", "B", "C"], values={"A", "C"})
        text = sel.render()
        assert text.plain == " ▾ A, C ▴ "

    def test_collapsed_render_shows_none_when_empty(self):
        sel = MultiCycleSelector(["A", "B", "C"])
        text = sel.render()
        assert text.plain == " ▾ (none) ▴ "

    def test_focused_render_shows_all_options_and_selection_markers(self):
        sel = MultiCycleSelector(["Alpha", "Beta"], values={"Alpha"})
        sel._editing = True
        text = sel.render()
        assert text.plain == " ▾ ✓ Alpha ▴ \n     Beta   "

    def test_clicking_current_row_arrows_moves_cursor(self):
        sel = MultiCycleSelector(["A", "B", "C"])
        sel._editing = True
        sel._cursor = 1

        sel.on_click(_ClickEvent(0, 1))
        assert sel._cursor == 0

        sel.on_click(_ClickEvent(len(sel._row_line(0)) - 1, 0))
        assert sel._cursor == 1

    def test_clicking_a_row_toggles_that_row(self):
        sel = MultiCycleSelector(["A", "B", "C"])
        sel._editing = True
        _mock_post_message(sel)

        sel.on_click(_ClickEvent(4, 2))

        assert sel.values == frozenset({"C"})
        assert sel._cursor == 2


class TestZoneConstants:
    def test_zone_constants_remain_stable(self):
        assert (_ZONE_PREV, _ZONE_CENTER, _ZONE_NEXT) == (0, 1, 2)
