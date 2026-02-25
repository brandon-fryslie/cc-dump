"""Tests for live streaming preview truncation policy."""

from cc_dump.tui.widget_factory import _bounded_stream_preview_text


def test_bounded_stream_preview_text_passthrough() -> None:
    text = "hello world"
    preview, omitted = _bounded_stream_preview_text(text, 64)
    assert preview == text
    assert omitted == 0


def test_bounded_stream_preview_text_truncates_to_tail() -> None:
    text = "abcdefghij"
    preview, omitted = _bounded_stream_preview_text(text, 4)
    assert omitted == 6
    assert preview.endswith("ghij")
    assert "Live preview truncated" in preview


def test_bounded_stream_preview_text_non_positive_budget_is_noop() -> None:
    text = "abcdef"
    preview, omitted = _bounded_stream_preview_text(text, 0)
    assert preview == text
    assert omitted == 0
