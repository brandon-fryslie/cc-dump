from cc_dump.tui.chip import Chip, ToggleChip


def test_chip_default_css_uses_visible_state_colors_without_opacity_fade():
    css = Chip.DEFAULT_CSS
    assert "background: $panel-lighten-2;" in css
    assert "background: $surface;" in css
    assert "border: solid $panel-lighten-1;" in css
    assert "border: solid $primary;" in css
    assert "Chip.-dim" in css
    assert "Chip.-hidden" in css
    assert "opacity" not in css


def test_toggle_chip_default_css_keeps_on_off_states_visible():
    css = ToggleChip.DEFAULT_CSS
    assert "background: $accent;" in css
    assert "border: solid $primary;" in css
    assert "ToggleChip.-off" in css
    assert "background: $surface-lighten-1;" in css
    assert "background: $surface;" in css
    assert "border: solid $panel-lighten-1;" in css
    assert "opacity" not in css
