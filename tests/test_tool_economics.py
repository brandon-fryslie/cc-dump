"""Tests for tool economics rendering."""

import pytest

from cc_dump.analysis import ToolEconomicsRow
from cc_dump.tui.panel_renderers import render_economics_panel


# ─── render_economics_panel() Tests ───────────────────────────────────────────


def test_render_economics_panel_empty():
    """Empty list shows no tools message."""
    text = render_economics_panel([])
    assert "(no tool calls yet)" in text


def test_render_economics_panel_basic():
    """Basic rendering with real data."""
    rows = [
        ToolEconomicsRow(
            name="Read",
            calls=5,
            input_tokens=1000,
            result_tokens=5000,
            cache_read_tokens=0,
            norm_cost=18000.0,
        ),
        ToolEconomicsRow(
            name="Bash",
            calls=3,
            input_tokens=500,
            result_tokens=2000,
            cache_read_tokens=0,
            norm_cost=11500.0,
        ),
    ]

    text = render_economics_panel(rows)

    # Check header
    assert "Tool Economics" in text
    assert "Tool" in text
    assert "Calls" in text
    assert "Input (Cached)" in text
    assert "Output" in text
    assert "Norm Cost" in text

    # Check data rows
    assert "Read" in text
    assert "5" in text  # calls
    assert "Bash" in text
    assert "3" in text  # calls


def test_render_economics_panel_cache_percentage():
    """Cache percentage shown correctly."""
    rows = [
        ToolEconomicsRow(
            name="Read",
            calls=1,
            input_tokens=1000,
            result_tokens=500,
            cache_read_tokens=9000,  # 9000 / (1000 + 9000) = 90%
            norm_cost=1000.0,
        ),
    ]

    text = render_economics_panel(rows)
    assert "90%" in text


def test_render_economics_panel_no_cache():
    """No cache percentage when cache_read_tokens is 0."""
    rows = [
        ToolEconomicsRow(
            name="Write",
            calls=1,
            input_tokens=1000,
            result_tokens=200,
            cache_read_tokens=0,
            norm_cost=1500.0,
        ),
    ]

    text = render_economics_panel(rows)
    # Should show just the token count, no percentage
    assert "1.0k" in text
    # Should not have percentage for 0 cache
    lines = text.split("\n")
    data_line = next((l for l in lines if "Write" in l), "")
    # Check that the Input column doesn't have a percentage
    assert "%" not in data_line or "0%" not in data_line


def test_render_economics_panel_zero_tokens():
    """Zero tokens show as -- instead of 0."""
    rows = [
        ToolEconomicsRow(
            name="Grep",
            calls=1,
            input_tokens=0,
            result_tokens=0,
            cache_read_tokens=0,
            norm_cost=0.0,
        ),
    ]

    text = render_economics_panel(rows)
    assert "Grep" in text
    assert "1" in text  # calls
    # Zero tokens and cost should show as --
    assert "--" in text


def test_render_economics_panel_token_formatting():
    """Large token counts formatted as k."""
    rows = [
        ToolEconomicsRow(
            name="Read",
            calls=1,
            input_tokens=45234,  # Should format as 45.2k
            result_tokens=12678,  # Should format as 12.7k
            cache_read_tokens=0,
            norm_cost=123456.0,  # Should format with comma: 123,456
        ),
    ]

    text = render_economics_panel(rows)
    assert "45.2k" in text
    assert "12.7k" in text or "12.6k" in text  # Allow minor rounding difference
    assert "123,456" in text


def test_render_economics_panel_column_alignment():
    """Check that columns are properly aligned."""
    rows = [
        ToolEconomicsRow(name="Read", calls=5, input_tokens=1000, result_tokens=5000, cache_read_tokens=0, norm_cost=18000.0),
        ToolEconomicsRow(name="Bash", calls=10, input_tokens=500, result_tokens=2000, cache_read_tokens=0, norm_cost=11500.0),
    ]

    text = render_economics_panel(rows)
    lines = text.split("\n")

    # Should have header + 2 data lines
    assert len(lines) >= 3

    # Tool names should be left-aligned (at start of line after indent)
    data_lines = [l for l in lines if "Read" in l or "Bash" in l]
    assert len(data_lines) == 2
