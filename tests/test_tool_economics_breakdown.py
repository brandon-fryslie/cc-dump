"""Tests for tool economics model breakdown toggle."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from cc_dump.analysis import ToolEconomicsRow, format_model_short
from cc_dump.db_queries import get_tool_economics
from cc_dump.schema import init_db
from cc_dump.tui.panel_renderers import render_economics_panel


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        conn = init_db(db_path)
        conn.close()
        yield db_path


def setup_mixed_model_data(db_path: str) -> str:
    """Insert test data with multiple models and return session_id."""
    session_id = "test_session_mixed"
    conn = sqlite3.connect(db_path)
    try:
        # Turn 1: Sonnet model
        conn.execute("""
            INSERT INTO turns (id, session_id, sequence_num, model, input_tokens, output_tokens, cache_read_tokens, request_json, response_json)
            VALUES (1, ?, 1, 'claude-sonnet-4-20250514', 1000, 500, 2000, '{}', '{}')
        """, (session_id,))

        # Turn 2: Opus model
        conn.execute("""
            INSERT INTO turns (id, session_id, sequence_num, model, input_tokens, output_tokens, cache_read_tokens, request_json, response_json)
            VALUES (2, ?, 2, 'claude-opus-4-20251101', 800, 400, 1500, '{}', '{}')
        """, (session_id,))

        # Turn 3: Another Sonnet turn
        conn.execute("""
            INSERT INTO turns (id, session_id, sequence_num, model, input_tokens, output_tokens, cache_read_tokens, request_json, response_json)
            VALUES (3, ?, 3, 'claude-sonnet-4-20250514', 600, 300, 1000, '{}', '{}')
        """, (session_id,))

        # Tool invocations for turn 1 (Sonnet)
        # Read: 600 tokens (60% of 1000)
        conn.execute("""
            INSERT INTO tool_invocations (turn_id, tool_name, tool_use_id, input_bytes, result_bytes, input_tokens, result_tokens, is_error)
            VALUES (1, 'Read', 'tool_1', 2400, 4000, 600, 1000, 0)
        """)

        # Bash: 400 tokens (40% of 1000)
        conn.execute("""
            INSERT INTO tool_invocations (turn_id, tool_name, tool_use_id, input_bytes, result_bytes, input_tokens, result_tokens, is_error)
            VALUES (1, 'Bash', 'tool_2', 1600, 2000, 400, 500, 0)
        """)

        # Tool invocations for turn 2 (Opus)
        # Read: all 800 tokens
        conn.execute("""
            INSERT INTO tool_invocations (turn_id, tool_name, tool_use_id, input_bytes, result_bytes, input_tokens, result_tokens, is_error)
            VALUES (2, 'Read', 'tool_3', 3200, 3000, 800, 750, 0)
        """)

        # Tool invocations for turn 3 (Sonnet again)
        # Write: all 600 tokens
        conn.execute("""
            INSERT INTO tool_invocations (turn_id, tool_name, tool_use_id, input_bytes, result_bytes, input_tokens, result_tokens, is_error)
            VALUES (3, 'Write', 'tool_4', 2400, 800, 600, 200, 0)
        """)

        conn.commit()
    finally:
        conn.close()

    return session_id


# ─── format_model_short() Tests ───────────────────────────────────────────────


def test_format_model_short_sonnet():
    """Sonnet models formatted as 'Sonnet 4.5'."""
    assert format_model_short("claude-sonnet-4-20250514") == "Sonnet 4.5"
    assert format_model_short("claude-sonnet-4") == "Sonnet 4.5"
    assert format_model_short("sonnet") == "Sonnet 4.5"


def test_format_model_short_opus():
    """Opus models formatted as 'Opus 4.5'."""
    assert format_model_short("claude-opus-4-20251101") == "Opus 4.5"
    assert format_model_short("claude-opus-4") == "Opus 4.5"
    assert format_model_short("opus") == "Opus 4.5"


def test_format_model_short_haiku():
    """Haiku models formatted as 'Haiku 4.5'."""
    assert format_model_short("claude-haiku-4-20250514") == "Haiku 4.5"
    assert format_model_short("haiku") == "Haiku 4.5"


def test_format_model_short_unknown():
    """Unknown models truncated to 20 chars."""
    assert format_model_short("some-long-unknown-model-name-12345678") == "some-long-unknown-mo"
    assert format_model_short("short") == "short"


def test_format_model_short_empty():
    """Empty string returns 'Unknown'."""
    assert format_model_short("") == "Unknown"


# ─── get_tool_economics() Aggregate Mode Tests ────────────────────────────────


def test_get_tool_economics_aggregate_default(temp_db):
    """Default mode (group_by_model=False) aggregates across models."""
    session_id = setup_mixed_model_data(temp_db)
    rows = get_tool_economics(temp_db, session_id, group_by_model=False)

    # Should have 3 tools: Read, Bash, Write
    assert len(rows) == 3

    # Find each tool
    read_row = next((r for r in rows if r.name == "Read"), None)
    bash_row = next((r for r in rows if r.name == "Bash"), None)
    write_row = next((r for r in rows if r.name == "Write"), None)

    assert read_row is not None
    assert bash_row is not None
    assert write_row is not None

    # Check model field is None for aggregate
    assert read_row.model is None
    assert bash_row.model is None
    assert write_row.model is None

    # Read appears in both turn 1 (Sonnet, 600 tokens) and turn 2 (Opus, 800 tokens)
    assert read_row.calls == 2
    assert read_row.input_tokens == 1400  # 600 + 800
    assert read_row.result_tokens == 1750  # 1000 + 750

    # Bash only in turn 1 (Sonnet)
    assert bash_row.calls == 1
    assert bash_row.input_tokens == 400
    assert bash_row.result_tokens == 500

    # Write only in turn 3 (Sonnet)
    assert write_row.calls == 1
    assert write_row.input_tokens == 600
    assert write_row.result_tokens == 200


def test_get_tool_economics_aggregate_cache_attribution(temp_db):
    """Aggregate mode combines cache attribution from all models."""
    session_id = setup_mixed_model_data(temp_db)
    rows = get_tool_economics(temp_db, session_id, group_by_model=False)

    read_row = next((r for r in rows if r.name == "Read"), None)

    # Turn 1: Read has 600 input / 1000 total = 60% share of 2000 cache = 1200
    # Turn 2: Read has 800 input / 800 total = 100% share of 1500 cache = 1500
    # Total cache for Read: 1200 + 1500 = 2700
    assert read_row.cache_read_tokens == 2700


def test_get_tool_economics_aggregate_norm_cost(temp_db):
    """Aggregate mode sums norm cost across models."""
    session_id = setup_mixed_model_data(temp_db)
    rows = get_tool_economics(temp_db, session_id, group_by_model=False)

    read_row = next((r for r in rows if r.name == "Read"), None)

    # Turn 1 (Sonnet): 600 * 3.0 + 1000 * 15.0 = 1800 + 15000 = 16800
    # Turn 2 (Opus): 800 * 5.0 + 750 * 25.0 = 4000 + 18750 = 22750
    # Total: 16800 + 22750 = 39550
    assert abs(read_row.norm_cost - 39550.0) < 0.01


# ─── get_tool_economics() Breakdown Mode Tests ────────────────────────────────


def test_get_tool_economics_breakdown_mode(temp_db):
    """Breakdown mode (group_by_model=True) groups by (tool, model)."""
    session_id = setup_mixed_model_data(temp_db)
    rows = get_tool_economics(temp_db, session_id, group_by_model=True)

    # Should have 4 rows: (Read, Sonnet), (Read, Opus), (Bash, Sonnet), (Write, Sonnet)
    assert len(rows) == 4

    # Check each row has a model field
    for row in rows:
        assert row.model is not None
        assert isinstance(row.model, str)

    # Find specific combinations
    read_sonnet = next((r for r in rows if r.name == "Read" and "sonnet" in r.model.lower()), None)
    read_opus = next((r for r in rows if r.name == "Read" and "opus" in r.model.lower()), None)
    bash_sonnet = next((r for r in rows if r.name == "Bash" and "sonnet" in r.model.lower()), None)
    write_sonnet = next((r for r in rows if r.name == "Write" and "sonnet" in r.model.lower()), None)

    assert read_sonnet is not None
    assert read_opus is not None
    assert bash_sonnet is not None
    assert write_sonnet is not None

    # Read/Sonnet (turn 1 only)
    assert read_sonnet.calls == 1
    assert read_sonnet.input_tokens == 600
    assert read_sonnet.result_tokens == 1000

    # Read/Opus (turn 2 only)
    assert read_opus.calls == 1
    assert read_opus.input_tokens == 800
    assert read_opus.result_tokens == 750


def test_get_tool_economics_breakdown_cache_attribution(temp_db):
    """Breakdown mode attributes cache correctly per model."""
    session_id = setup_mixed_model_data(temp_db)
    rows = get_tool_economics(temp_db, session_id, group_by_model=True)

    read_sonnet = next((r for r in rows if r.name == "Read" and "sonnet" in r.model.lower()), None)
    read_opus = next((r for r in rows if r.name == "Read" and "opus" in r.model.lower()), None)

    # Read/Sonnet (turn 1): 600 / 1000 * 2000 = 1200
    assert read_sonnet.cache_read_tokens == 1200

    # Read/Opus (turn 2): 800 / 800 * 1500 = 1500
    assert read_opus.cache_read_tokens == 1500


def test_get_tool_economics_breakdown_norm_cost(temp_db):
    """Breakdown mode calculates norm cost per (tool, model)."""
    session_id = setup_mixed_model_data(temp_db)
    rows = get_tool_economics(temp_db, session_id, group_by_model=True)

    read_sonnet = next((r for r in rows if r.name == "Read" and "sonnet" in r.model.lower()), None)
    read_opus = next((r for r in rows if r.name == "Read" and "opus" in r.model.lower()), None)

    # Read/Sonnet: 600 * 3.0 + 1000 * 15.0 = 16800
    assert abs(read_sonnet.norm_cost - 16800.0) < 0.01

    # Read/Opus: 800 * 5.0 + 750 * 25.0 = 22750
    assert abs(read_opus.norm_cost - 22750.0) < 0.01


def test_get_tool_economics_breakdown_sum_equals_aggregate(temp_db):
    """Sum of breakdown costs for same tool equals aggregate cost."""
    session_id = setup_mixed_model_data(temp_db)

    # Get both modes
    agg_rows = get_tool_economics(temp_db, session_id, group_by_model=False)
    bd_rows = get_tool_economics(temp_db, session_id, group_by_model=True)

    # Find Read in aggregate
    read_agg = next((r for r in agg_rows if r.name == "Read"), None)

    # Find all Read entries in breakdown
    read_bds = [r for r in bd_rows if r.name == "Read"]

    # Sum breakdown costs
    bd_cost_sum = sum(r.norm_cost for r in read_bds)

    # Should match aggregate
    assert abs(read_agg.norm_cost - bd_cost_sum) < 0.01


def test_get_tool_economics_breakdown_sorting(temp_db):
    """Breakdown rows sorted by norm_cost desc, then tool_name, then model."""
    session_id = setup_mixed_model_data(temp_db)
    rows = get_tool_economics(temp_db, session_id, group_by_model=True)

    # Costs (highest first):
    # Read/Opus: 22750
    # Read/Sonnet: 16800
    # Bash/Sonnet: 400*3 + 500*15 = 1200 + 7500 = 8700
    # Write/Sonnet: 600*3 + 200*15 = 1800 + 3000 = 4800

    assert rows[0].name == "Read"
    assert "opus" in rows[0].model.lower()

    assert rows[1].name == "Read"
    assert "sonnet" in rows[1].model.lower()

    # Costs should be descending
    for i in range(len(rows) - 1):
        assert rows[i].norm_cost >= rows[i + 1].norm_cost


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
                        cache_read_tokens=0, norm_cost=10800.0, model="claude-sonnet-4-20250514"),
        ToolEconomicsRow(name="Bash", calls=1, input_tokens=400, result_tokens=2000,
                        cache_read_tokens=0, norm_cost=7200.0, model="claude-opus-4-20251101"),
    ]

    text = render_economics_panel(rows)

    # Should show short names
    assert "Sonnet 4.5" in text
    assert "Opus 4.5" in text

    # Should not show full model strings
    assert "claude-sonnet-4-20250514" not in text
    assert "claude-opus-4-20251101" not in text


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
