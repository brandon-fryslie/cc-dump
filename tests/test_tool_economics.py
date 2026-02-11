"""Tests for tool economics query and rendering."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from cc_dump.analysis import ToolEconomicsRow, MODEL_PRICING
from cc_dump.db_queries import get_tool_economics
from cc_dump.schema import init_db
from cc_dump.tui.panel_renderers import render_economics_panel


def setup_test_data(db_path: str) -> str:
    """Insert test data and return session_id."""
    session_id = "test_session_123"
    conn = sqlite3.connect(db_path)
    try:
        # Create turns with different models
        conn.execute("""
            INSERT INTO turns (id, session_id, sequence_num, model, input_tokens, output_tokens, cache_read_tokens, request_json, response_json)
            VALUES (1, ?, 1, 'claude-sonnet-4', 1000, 500, 2000, '{}', '{}')
        """, (session_id,))

        conn.execute("""
            INSERT INTO turns (id, session_id, sequence_num, model, input_tokens, output_tokens, cache_read_tokens, request_json, response_json)
            VALUES (2, ?, 2, 'claude-haiku-4', 500, 200, 1000, '{}', '{}')
        """, (session_id,))

        # Create tool invocations for turn 1
        # Read tool: 600 input tokens (60% of 1000)
        conn.execute("""
            INSERT INTO tool_invocations (turn_id, tool_name, tool_use_id, input_bytes, result_bytes, input_tokens, result_tokens, is_error)
            VALUES (1, 'Read', 'tool_1', 2400, 4000, 600, 1000, 0)
        """)

        # Bash tool: 400 input tokens (40% of 1000)
        conn.execute("""
            INSERT INTO tool_invocations (turn_id, tool_name, tool_use_id, input_bytes, result_bytes, input_tokens, result_tokens, is_error)
            VALUES (1, 'Bash', 'tool_2', 1600, 2000, 400, 500, 0)
        """)

        # Create tool invocations for turn 2
        # Write tool: all 500 input tokens
        conn.execute("""
            INSERT INTO tool_invocations (turn_id, tool_name, tool_use_id, input_bytes, result_bytes, input_tokens, result_tokens, is_error)
            VALUES (2, 'Write', 'tool_3', 2000, 800, 500, 200, 0)
        """)

        conn.commit()
    finally:
        conn.close()

    return session_id


# ─── get_tool_economics() Query Tests ─────────────────────────────────────────


def test_get_tool_economics_empty_session(temp_db):
    """Empty session returns empty list."""
    rows = get_tool_economics(temp_db, "nonexistent_session")
    assert rows == []


def test_get_tool_economics_no_tools(temp_db):
    """Session with turns but no tool invocations returns empty list."""
    session_id = "test_session_no_tools"
    conn = sqlite3.connect(temp_db)
    try:
        conn.execute("""
            INSERT INTO turns (session_id, sequence_num, model, input_tokens, output_tokens, request_json, response_json)
            VALUES (?, 1, 'claude-sonnet-4', 1000, 500, '{}', '{}')
        """, (session_id,))
        conn.commit()
    finally:
        conn.close()

    rows = get_tool_economics(temp_db, session_id)
    assert rows == []


def test_get_tool_economics_aggregation(temp_db):
    """Test basic aggregation of tool invocations."""
    session_id = setup_test_data(temp_db)
    rows = get_tool_economics(temp_db, session_id)

    # Should have 3 distinct tools
    assert len(rows) == 3

    # Find each tool in results
    read_row = next((r for r in rows if r.name == "Read"), None)
    bash_row = next((r for r in rows if r.name == "Bash"), None)
    write_row = next((r for r in rows if r.name == "Write"), None)

    assert read_row is not None
    assert bash_row is not None
    assert write_row is not None

    # Check basic counts
    assert read_row.calls == 1
    assert read_row.input_tokens == 600
    assert read_row.result_tokens == 1000

    assert bash_row.calls == 1
    assert bash_row.input_tokens == 400
    assert bash_row.result_tokens == 500

    assert write_row.calls == 1
    assert write_row.input_tokens == 500
    assert write_row.result_tokens == 200


def test_get_tool_economics_cache_attribution(temp_db):
    """Test proportional cache attribution."""
    session_id = setup_test_data(temp_db)
    rows = get_tool_economics(temp_db, session_id)

    # Find tools from turn 1 (which has cache_read_tokens = 2000)
    read_row = next((r for r in rows if r.name == "Read"), None)
    bash_row = next((r for r in rows if r.name == "Bash"), None)

    # Read: 600 input / 1000 total = 60% share of cache
    # Expected cache: 2000 * 0.6 = 1200
    assert read_row.cache_read_tokens == 1200

    # Bash: 400 input / 1000 total = 40% share of cache
    # Expected cache: 2000 * 0.4 = 800
    assert bash_row.cache_read_tokens == 800

    # Write is from turn 2 (cache_read_tokens = 1000, single tool gets all)
    write_row = next((r for r in rows if r.name == "Write"), None)
    assert write_row.cache_read_tokens == 1000


def test_get_tool_economics_norm_cost(temp_db):
    """Test normalized cost calculation."""
    session_id = setup_test_data(temp_db)
    rows = get_tool_economics(temp_db, session_id)

    # Read tool is from Sonnet turn (base_input=3.0, output=15.0)
    read_row = next((r for r in rows if r.name == "Read"), None)
    # Cost = 600 * 3.0 + 1000 * 15.0 = 1800 + 15000 = 16800
    assert abs(read_row.norm_cost - 16800.0) < 0.01

    # Write tool is from Haiku turn (base_input=1.0, output=5.0)
    write_row = next((r for r in rows if r.name == "Write"), None)
    # Cost = 500 * 1.0 + 200 * 5.0 = 500 + 1000 = 1500
    assert abs(write_row.norm_cost - 1500.0) < 0.01


def test_get_tool_economics_sorting(temp_db):
    """Results should be sorted by norm_cost descending."""
    session_id = setup_test_data(temp_db)
    rows = get_tool_economics(temp_db, session_id)

    # Read has highest cost (16800), then Bash, then Write
    assert rows[0].name == "Read"
    assert rows[0].norm_cost > rows[1].norm_cost
    assert rows[1].norm_cost > rows[2].norm_cost


def test_get_tool_economics_multiple_invocations_same_tool(temp_db):
    """Multiple invocations of same tool are aggregated."""
    session_id = "test_multi"
    conn = sqlite3.connect(temp_db)
    try:
        conn.execute("""
            INSERT INTO turns (id, session_id, sequence_num, model, input_tokens, output_tokens, cache_read_tokens, request_json, response_json)
            VALUES (1, ?, 1, 'claude-sonnet-4', 1000, 500, 0, '{}', '{}')
        """, (session_id,))

        # Two Read invocations
        conn.execute("""
            INSERT INTO tool_invocations (turn_id, tool_name, tool_use_id, input_bytes, result_bytes, input_tokens, result_tokens, is_error)
            VALUES (1, 'Read', 'tool_1', 1000, 2000, 250, 500, 0)
        """)
        conn.execute("""
            INSERT INTO tool_invocations (turn_id, tool_name, tool_use_id, input_bytes, result_bytes, input_tokens, result_tokens, is_error)
            VALUES (1, 'Read', 'tool_2', 1000, 2000, 250, 500, 0)
        """)

        conn.commit()
    finally:
        conn.close()

    rows = get_tool_economics(temp_db, session_id)
    assert len(rows) == 1
    assert rows[0].name == "Read"
    assert rows[0].calls == 2
    assert rows[0].input_tokens == 500  # 250 + 250
    assert rows[0].result_tokens == 1000  # 500 + 500


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
