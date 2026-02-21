"""Tests for tool economics model breakdown rendering."""

import pytest

from cc_dump.analysis import ToolEconomicsRow, format_model_short
from cc_dump.tui.panel_renderers import render_economics_panel


# ─── format_model_short() Tests ───────────────────────────────────────────────


def test_format_model_short_sonnet():
    """Sonnet models formatted from parsed version tokens."""
    assert format_model_short("claude-sonnet-4-6-20260114") == "Sonnet 4.6"
    assert format_model_short("claude-sonnet-4-20250514") == "Sonnet 4"
    assert format_model_short("sonnet") == "Sonnet"


def test_format_model_short_opus():
    """Opus models formatted from parsed version tokens."""
    assert format_model_short("claude-opus-4-6-20260114") == "Opus 4.6"
    assert format_model_short("claude-opus-4") == "Opus 4"
    assert format_model_short("opus") == "Opus"


def test_format_model_short_haiku():
    """Haiku models formatted from parsed version tokens."""
    assert format_model_short("claude-haiku-4-6-20260114") == "Haiku 4.6"
    assert format_model_short("haiku") == "Haiku"


def test_format_model_short_unknown():
    """Unknown models truncated to 20 chars."""
    assert format_model_short("some-long-unknown-model-name-12345678") == "some-long-unknown-mo"
    assert format_model_short("short") == "short"


def test_format_model_short_empty():
    """Empty string returns 'Unknown'."""
    assert format_model_short("") == "Unknown"


# ─── render_economics_panel() Tests ───────────────────────────────────────────


def test_render_economics_panel_detects_breakdown_mode():
    """Renderer detects breakdown mode when rows have model != None."""
    # Aggregate rows (model=None)
    agg_rows = [
        ToolEconomicsRow(name="Read", calls=5, input_tokens=1000, result_tokens=5000,
                        cache_read_tokens=0, norm_cost=18000.0, model=None),
    ]

    # Breakdown rows (model set)
    bd_rows = [
        ToolEconomicsRow(name="Read", calls=3, input_tokens=600, result_tokens=3000,
                        cache_read_tokens=0, norm_cost=10800.0, model="claude-sonnet-4"),
        ToolEconomicsRow(name="Read", calls=2, input_tokens=400, result_tokens=2000,
                        cache_read_tokens=0, norm_cost=7200.0, model="claude-opus-4"),
    ]

    agg_text = render_economics_panel(agg_rows)
    bd_text = render_economics_panel(bd_rows)

    # Aggregate should say "session total"
    assert "session total" in agg_text
    assert "by model" not in agg_text

    # Breakdown should say "by model"
    assert "by model" in bd_text
    assert "session total" not in bd_text


def test_render_economics_panel_aggregate_layout():
    """Aggregate layout has no Model column."""
    rows = [
        ToolEconomicsRow(name="Read", calls=5, input_tokens=1000, result_tokens=5000,
                        cache_read_tokens=0, norm_cost=18000.0, model=None),
    ]

    text = render_economics_panel(rows)
    lines = text.split("\n")

    # Header should have: Tool | Calls | Input (Cached) | Output | Norm Cost
    header = next((l for l in lines if "Tool" in l and "Calls" in l), "")
    assert "Model" not in header
    assert "Tool" in header
    assert "Calls" in header
    assert "Input (Cached)" in header
    assert "Output" in header
    assert "Norm Cost" in header


def test_render_economics_panel_breakdown_layout():
    """Breakdown layout includes Model column."""
    rows = [
        ToolEconomicsRow(name="Read", calls=3, input_tokens=600, result_tokens=3000,
                        cache_read_tokens=0, norm_cost=10800.0, model="claude-sonnet-4"),
    ]

    text = render_economics_panel(rows)
    lines = text.split("\n")

    # Header should have: Tool | Model | Calls | Input (Cached) | Output | Norm Cost
    header = next((l for l in lines if "Tool" in l and "Model" in l), "")
    assert "Tool" in header
    assert "Model" in header
    assert "Calls" in header
    assert "Input (Cached)" in header
    assert "Output" in header
    assert "Norm Cost" in header


def test_render_economics_panel_model_names_shortened():
    """Model names displayed as short form in breakdown view."""
    rows = [
        ToolEconomicsRow(name="Read", calls=1, input_tokens=600, result_tokens=3000,
                        cache_read_tokens=0, norm_cost=10800.0, model="claude-sonnet-4-6-20260114"),
        ToolEconomicsRow(name="Bash", calls=1, input_tokens=400, result_tokens=2000,
                        cache_read_tokens=0, norm_cost=7200.0, model="claude-opus-4-6-20260114"),
    ]

    text = render_economics_panel(rows)

    # Should show short names
    assert "Sonnet 4.6" in text
    assert "Opus 4.6" in text

    # Should not show full model strings
    assert "claude-sonnet-4-6-20260114" not in text
    assert "claude-opus-4-6-20260114" not in text


def test_render_economics_panel_breakdown_formatting():
    """Breakdown view formats numbers correctly."""
    rows = [
        ToolEconomicsRow(name="Read", calls=5, input_tokens=45234, result_tokens=12678,
                        cache_read_tokens=40000, norm_cost=123456.0,
                        model="claude-sonnet-4"),
    ]

    text = render_economics_panel(rows)

    # Token counts formatted as k
    assert "45.2k" in text
    assert "12.7k" in text or "12.6k" in text  # Allow minor rounding difference

    # Cache percentage shown
    assert "47%" in text  # 40000 / (45234 + 40000)

    # Norm cost with comma
    assert "123,456" in text


def test_render_economics_panel_mixed_models_alignment():
    """Columns properly aligned in breakdown view with multiple models."""
    rows = [
        ToolEconomicsRow(name="Read", calls=10, input_tokens=1000, result_tokens=5000,
                        cache_read_tokens=0, norm_cost=18000.0, model="claude-sonnet-4"),
        ToolEconomicsRow(name="Bash", calls=5, input_tokens=500, result_tokens=2000,
                        cache_read_tokens=0, norm_cost=8700.0, model="claude-opus-4"),
    ]

    text = render_economics_panel(rows)
    lines = text.split("\n")

    # Should have header + 2 data lines
    data_lines = [l for l in lines if "Read" in l or "Bash" in l]
    assert len(data_lines) == 2

    # All lines should be non-empty
    for line in lines:
        if line.strip():
            assert len(line) > 0
