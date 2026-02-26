"""Unit tests for CycleSelector and MultiCycleSelector widgets.

Tests CSS structure, state transitions, value cycling, wrap-around,
zone management, message emission, render output, and disabled behavior.
"""

from unittest.mock import MagicMock

from rich.text import Text

from cc_dump.tui.cycle_selector import (
    CycleSelector,
    MultiCycleSelector,
    _ZONE_CENTER,
    _ZONE_NEXT,
    _ZONE_PREV,
)


# ═══════════════════════════════════════════════════════════════════════════
# CycleSelector (single-select) tests
# ═══════════════════════════════════════════════════════════════════════════


class TestCycleSelectorCSS:
    """CSS structure validation — ensure correct states, no opacity."""

    def test_default_css_has_base_state(self):
        css = CycleSelector.DEFAULT_CSS
        assert "background: $panel-lighten-2;" in css

    def test_default_css_has_hover_state(self):
        css = CycleSelector.DEFAULT_CSS
        assert "CycleSelector:hover" in css
        assert "background: $surface-darken-1;" in css

    def test_default_css_has_focus_state(self):
        css = CycleSelector.DEFAULT_CSS
        assert "CycleSelector:focus" in css
        assert "bold underline" in css

    def test_default_css_has_editing_modifier(self):
        css = CycleSelector.DEFAULT_CSS
        assert "CycleSelector.-editing" in css
        assert "background: $accent;" in css

    def test_default_css_no_opacity_or_border(self):
        css = CycleSelector.DEFAULT_CSS
        assert "opacity" not in css
        assert "border:" not in css
        assert "outline:" not in css


class TestCycleSelectorInit:
    """Constructor behavior."""

    def test_init_defaults_to_first_option(self):
        sel = CycleSelector(["A", "B", "C"])
        assert sel.value == "A"
        assert sel.index == 0

    def test_init_with_explicit_value(self):
        sel = CycleSelector(["A", "B", "C"], value="B")
        assert sel.value == "B"
        assert sel.index == 1

    def test_init_unknown_value_defaults_to_first(self):
        sel = CycleSelector(["A", "B", "C"], value="Z")
        assert sel.value == "A"
        assert sel.index == 0

    def test_init_not_editing(self):
        sel = CycleSelector(["A", "B"])
        assert sel._editing is False

    def test_init_with_widget_params(self):
        sel = CycleSelector(["A"], id="test-id", classes="my-class", disabled=True)
        assert sel.id == "test-id"
        assert sel.has_class("my-class")
        assert sel.disabled is True


class TestCycleSelectorCycling:
    """Core value cycling logic."""

    def test_cycle_next_normal(self):
        sel = CycleSelector(["A", "B", "C"], value="A")
        sel.post_message = MagicMock()
        sel._editing = True
        sel._activate_zone(_ZONE_NEXT)
        assert sel.value == "B"
        assert sel.index == 1

    def test_cycle_prev_normal(self):
        sel = CycleSelector(["A", "B", "C"], value="B")
        sel.post_message = MagicMock()
        sel._editing = True
        sel._activate_zone(_ZONE_PREV)
        assert sel.value == "A"
        assert sel.index == 0

    def test_cycle_next_wraps_around(self):
        sel = CycleSelector(["A", "B", "C"], value="C")
        sel.post_message = MagicMock()
        sel._editing = True
        sel._activate_zone(_ZONE_NEXT)
        assert sel.value == "A"
        assert sel.index == 0

    def test_cycle_prev_wraps_around(self):
        sel = CycleSelector(["A", "B", "C"], value="A")
        sel.post_message = MagicMock()
        sel._editing = True
        sel._activate_zone(_ZONE_PREV)
        assert sel.value == "C"
        assert sel.index == 2

    def test_single_option_no_change(self):
        sel = CycleSelector(["Only"])
        sel.post_message = MagicMock()
        sel._editing = True
        sel._activate_zone(_ZONE_NEXT)
        assert sel.value == "Only"
        sel.post_message.assert_not_called()


class TestCycleSelectorZoneBoundaries:
    """Click zone computation."""

    def test_boundaries_short_value(self):
        sel = CycleSelector(["A"])
        prev_end, next_start = sel._zone_boundaries()
        # " ▾ " = 3 chars, " A " = 3 chars
        assert prev_end == 3
        assert next_start == 6

    def test_boundaries_long_value(self):
        sel = CycleSelector(["Very Long Option"])
        prev_end, next_start = sel._zone_boundaries()
        assert prev_end == 3
        # " Very Long Option " = 18 chars
        assert next_start == 3 + len("Very Long Option") + 2


class TestCycleSelectorStateTransitions:
    """Two-state editing machine."""

    def test_enter_editing_sets_center_zone(self):
        sel = CycleSelector(["A", "B"])
        sel._enter_editing()
        assert sel._editing is True
        assert sel._zone == _ZONE_CENTER

    def test_exit_editing(self):
        sel = CycleSelector(["A", "B"])
        sel._editing = True
        sel._exit_editing()
        assert sel._editing is False

    def test_activate_prev_stays_editing(self):
        sel = CycleSelector(["A", "B", "C"])
        sel.post_message = MagicMock()
        sel._editing = True
        sel._activate_zone(_ZONE_PREV)
        assert sel._editing is True

    def test_activate_next_stays_editing(self):
        sel = CycleSelector(["A", "B", "C"])
        sel.post_message = MagicMock()
        sel._editing = True
        sel._activate_zone(_ZONE_NEXT)
        assert sel._editing is True

    def test_activate_center_exits_editing(self):
        sel = CycleSelector(["A", "B", "C"])
        sel.post_message = MagicMock()
        sel._editing = True
        sel._activate_zone(_ZONE_CENTER)
        assert sel._editing is False


class TestCycleSelectorZoneNavigation:
    """Internal focus zone movement."""

    def test_move_right_from_prev(self):
        sel = CycleSelector(["A"])
        sel._zone = _ZONE_PREV
        sel._move_zone(+1)
        assert sel._zone == _ZONE_CENTER

    def test_move_right_from_center(self):
        sel = CycleSelector(["A"])
        sel._zone = _ZONE_CENTER
        sel._move_zone(+1)
        assert sel._zone == _ZONE_NEXT

    def test_move_left_from_next(self):
        sel = CycleSelector(["A"])
        sel._zone = _ZONE_NEXT
        sel._move_zone(-1)
        assert sel._zone == _ZONE_CENTER

    def test_clamps_at_prev(self):
        sel = CycleSelector(["A"])
        sel._zone = _ZONE_PREV
        sel._move_zone(-1)
        assert sel._zone == _ZONE_PREV

    def test_clamps_at_next(self):
        sel = CycleSelector(["A"])
        sel._zone = _ZONE_NEXT
        sel._move_zone(+1)
        assert sel._zone == _ZONE_NEXT


class TestCycleSelectorMessages:
    """Changed message emission."""

    def test_changed_on_next(self):
        sel = CycleSelector(["A", "B", "C"], value="A")
        sel.post_message = MagicMock()
        sel._editing = True
        sel._activate_zone(_ZONE_NEXT)
        sel.post_message.assert_called_once()
        msg = sel.post_message.call_args[0][0]
        assert isinstance(msg, CycleSelector.Changed)
        assert msg.value == "B"
        assert msg.index == 1

    def test_changed_on_prev(self):
        sel = CycleSelector(["A", "B", "C"], value="B")
        sel.post_message = MagicMock()
        sel._editing = True
        sel._activate_zone(_ZONE_PREV)
        sel.post_message.assert_called_once()
        msg = sel.post_message.call_args[0][0]
        assert msg.value == "A"
        assert msg.index == 0

    def test_no_message_on_center_confirm(self):
        sel = CycleSelector(["A", "B", "C"])
        sel.post_message = MagicMock()
        sel._editing = True
        sel._activate_zone(_ZONE_CENTER)
        sel.post_message.assert_not_called()

    def test_no_message_single_option(self):
        sel = CycleSelector(["Only"])
        sel.post_message = MagicMock()
        sel._editing = True
        sel._activate_zone(_ZONE_NEXT)
        sel.post_message.assert_not_called()

    def test_changed_message_control_property(self):
        sel = CycleSelector(["A", "B"], value="A")
        sel.post_message = MagicMock()
        sel._editing = True
        sel._activate_zone(_ZONE_NEXT)
        msg = sel.post_message.call_args[0][0]
        assert msg.control is sel


class TestCycleSelectorRender:
    """Render output — Rich Text with correct zones and styling."""

    def test_non_editing_no_reverse(self):
        sel = CycleSelector(["Alpha"], value="Alpha")
        text = sel.render()
        assert isinstance(text, Text)
        plain = text.plain
        assert "\u25be" in plain  # ▾
        assert "Alpha" in plain
        assert "\u25b4" in plain  # ▴

    def test_editing_center_focused_has_reverse(self):
        sel = CycleSelector(["Alpha"], value="Alpha")
        sel._editing = True
        sel._zone = _ZONE_CENTER
        text = sel.render()
        # The center span should have reverse style
        spans = text._spans
        assert any(span.style and "reverse" in str(span.style) for span in spans)

    def test_editing_prev_focused_has_reverse_on_prev(self):
        sel = CycleSelector(["Alpha"], value="Alpha")
        sel._editing = True
        sel._zone = _ZONE_PREV
        text = sel.render()
        # First span (prev zone) should have reverse
        spans = text._spans
        assert len(spans) > 0
        # The reverse span should start at position 0 (prev zone)
        reverse_spans = [s for s in spans if s.style and "reverse" in str(s.style)]
        assert len(reverse_spans) == 1
        assert reverse_spans[0].start == 0


class TestCycleSelectorProperties:
    """Value and index property setters."""

    def test_value_setter(self):
        sel = CycleSelector(["A", "B", "C"])
        sel.value = "C"
        assert sel.value == "C"
        assert sel.index == 2

    def test_value_setter_invalid_raises(self):
        sel = CycleSelector(["A", "B", "C"])
        try:
            sel.value = "Z"
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_index_setter(self):
        sel = CycleSelector(["A", "B", "C"])
        sel.index = 2
        assert sel.value == "C"

    def test_index_setter_wraps(self):
        sel = CycleSelector(["A", "B", "C"])
        sel.index = 5  # 5 % 3 == 2
        assert sel.value == "C"


# ═══════════════════════════════════════════════════════════════════════════
# MultiCycleSelector tests
# ═══════════════════════════════════════════════════════════════════════════


class TestMultiCycleSelectorCSS:
    """CSS structure validation."""

    def test_default_css_has_base_state(self):
        css = MultiCycleSelector.DEFAULT_CSS
        assert "background: $panel-lighten-2;" in css

    def test_default_css_has_editing_modifier(self):
        css = MultiCycleSelector.DEFAULT_CSS
        assert "MultiCycleSelector.-editing" in css

    def test_default_css_has_selected_modifier(self):
        css = MultiCycleSelector.DEFAULT_CSS
        assert "MultiCycleSelector.-selected" in css

    def test_default_css_no_opacity(self):
        css = MultiCycleSelector.DEFAULT_CSS
        assert "opacity" not in css


class TestMultiCycleSelectorInit:
    """Constructor behavior."""

    def test_init_empty_selection(self):
        sel = MultiCycleSelector(["A", "B", "C"])
        assert sel.values == frozenset()
        assert sel.indices == frozenset()

    def test_init_with_values(self):
        sel = MultiCycleSelector(["A", "B", "C"], values={"A", "C"})
        assert sel.values == frozenset({"A", "C"})
        assert sel.indices == frozenset({0, 2})

    def test_init_unknown_values_ignored(self):
        sel = MultiCycleSelector(["A", "B"], values={"A", "Z"})
        assert sel.values == frozenset({"A"})

    def test_init_not_editing(self):
        sel = MultiCycleSelector(["A"])
        assert sel._editing is False

    def test_init_with_widget_params(self):
        sel = MultiCycleSelector(["A"], id="multi-id", disabled=True)
        assert sel.id == "multi-id"
        assert sel.disabled is True


class TestMultiCycleSelectorToggle:
    """Center zone toggles selection."""

    def test_toggle_selects_unselected(self):
        sel = MultiCycleSelector(["A", "B", "C"])
        sel.post_message = MagicMock()
        sel._editing = True
        sel._cursor = 0
        sel._activate_zone(_ZONE_CENTER)
        assert 0 in sel._selected
        assert "A" in sel.values

    def test_toggle_deselects_selected(self):
        sel = MultiCycleSelector(["A", "B", "C"], values={"A"})
        sel.post_message = MagicMock()
        sel._editing = True
        sel._cursor = 0
        sel._activate_zone(_ZONE_CENTER)
        assert 0 not in sel._selected
        assert "A" not in sel.values

    def test_toggle_posts_changed(self):
        sel = MultiCycleSelector(["A", "B", "C"])
        sel.post_message = MagicMock()
        sel._editing = True
        sel._cursor = 1
        sel._activate_zone(_ZONE_CENTER)
        sel.post_message.assert_called_once()
        msg = sel.post_message.call_args[0][0]
        assert isinstance(msg, MultiCycleSelector.Changed)
        assert msg.values == frozenset({"B"})
        assert msg.indices == frozenset({1})
        assert msg.control is sel

    def test_toggle_stays_in_editing(self):
        sel = MultiCycleSelector(["A", "B"])
        sel.post_message = MagicMock()
        sel._editing = True
        sel._cursor = 0
        sel._activate_zone(_ZONE_CENTER)
        assert sel._editing is True


class TestMultiCycleSelectorCursorCycling:
    """Prev/next move cursor through options."""

    def test_next_moves_cursor(self):
        sel = MultiCycleSelector(["A", "B", "C"])
        sel._editing = True
        sel._cursor = 0
        sel._activate_zone(_ZONE_NEXT)
        assert sel._cursor == 1

    def test_prev_moves_cursor(self):
        sel = MultiCycleSelector(["A", "B", "C"])
        sel._editing = True
        sel._cursor = 1
        sel._activate_zone(_ZONE_PREV)
        assert sel._cursor == 0

    def test_next_wraps_around(self):
        sel = MultiCycleSelector(["A", "B", "C"])
        sel._editing = True
        sel._cursor = 2
        sel._activate_zone(_ZONE_NEXT)
        assert sel._cursor == 0

    def test_prev_wraps_around(self):
        sel = MultiCycleSelector(["A", "B", "C"])
        sel._editing = True
        sel._cursor = 0
        sel._activate_zone(_ZONE_PREV)
        assert sel._cursor == 2

    def test_cursor_cycling_does_not_post_changed(self):
        sel = MultiCycleSelector(["A", "B", "C"])
        sel.post_message = MagicMock()
        sel._editing = True
        sel._cursor = 0
        sel._activate_zone(_ZONE_NEXT)
        sel.post_message.assert_not_called()


class TestMultiCycleSelectorDisplay:
    """Render output for both states."""

    def test_non_editing_comma_joined(self):
        sel = MultiCycleSelector(["A", "B", "C"], values={"A", "C"})
        text = sel.render()
        plain = text.plain
        assert "A, C" in plain

    def test_non_editing_none_selected(self):
        sel = MultiCycleSelector(["A", "B", "C"])
        text = sel.render()
        plain = text.plain
        assert "(none)" in plain

    def test_editing_shows_checkmark_for_selected(self):
        sel = MultiCycleSelector(["Alpha", "Beta"], values={"Alpha"})
        sel._editing = True
        sel._cursor = 0
        text = sel.render()
        plain = text.plain
        assert "\u2713" in plain  # ✓
        assert "Alpha" in plain

    def test_editing_shows_space_for_unselected(self):
        sel = MultiCycleSelector(["Alpha", "Beta"])
        sel._editing = True
        sel._cursor = 0
        text = sel.render()
        plain = text.plain
        assert "Alpha" in plain
        # No checkmark present
        assert "\u2713" not in plain


class TestMultiCycleSelectorEscape:
    """Escape exits editing, keeps selections."""

    def test_escape_exits_editing(self):
        sel = MultiCycleSelector(["A", "B", "C"], values={"A"})
        sel._editing = True
        sel._exit_editing()
        assert sel._editing is False

    def test_escape_keeps_selections(self):
        sel = MultiCycleSelector(["A", "B", "C"], values={"A"})
        sel.post_message = MagicMock()
        sel._editing = True
        sel._cursor = 1
        sel._activate_zone(_ZONE_CENTER)  # toggle B on
        sel._exit_editing()
        assert sel.values == frozenset({"A", "B"})


class TestMultiCycleSelectorEnterEditing:
    """Enter editing state."""

    def test_enter_editing_starts_at_first_option(self):
        sel = MultiCycleSelector(["A", "B", "C"])
        sel._enter_editing()
        assert sel._editing is True
        assert sel._cursor == 0
        assert sel._zone == _ZONE_CENTER
