"""ConversationView top-right overlay rendering tests."""

from rich.style import Style
from rich.segment import Segment
from textual.strip import Strip

from cc_dump.tui.widget_factory import ConversationView


def test_busy_overlay_line_includes_reason() -> None:
    conv = ConversationView()
    conv.set_busy_state(True, ("events",))

    lines = conv._overlay_lines(80)
    assert lines
    text, style = lines[0]
    assert "events" in text
    assert isinstance(style, Style)


def test_metrics_overlay_line_includes_last_invalidate_stats() -> None:
    conv = ConversationView()
    conv._overlay_metrics_enabled = True
    conv._invalidate_last_ms = 42.5
    conv._invalidate_samples_ms.extend([10.0, 20.0, 30.0, 40.0, 50.0])

    lines = conv._overlay_lines(120)
    assert len(lines) == 1
    text, _style = lines[0]
    assert "inv" in text
    assert "p95" in text


def test_apply_top_right_overlay_paints_right_edge() -> None:
    conv = ConversationView()
    conv._overlay_metrics_enabled = True
    conv._invalidate_last_ms = 1.0
    base = Strip([Segment("x" * 40)])

    painted = conv._apply_top_right_overlay(base, 0, 40)
    assert painted.cell_length == 40
    assert painted.text != base.text
