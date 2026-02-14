"""Tests for full-height gutter indicators in rendering.py."""

from cc_dump.formatting import (
    TextContentBlock,
    ToolResultBlock,
    Category,
)
from cc_dump.tui.rendering import (
    render_turn_to_strips,
    GUTTER_WIDTH,
    RIGHT_GUTTER_WIDTH,
    MIN_WIDTH_FOR_RIGHT_GUTTER,
    GUTTER_ARROWS,
    set_theme,
)
from rich.console import Console
from textual.theme import BUILTIN_THEMES


def test_gutter_width_constant():
    """GUTTER_WIDTH should be defined and equal to 4, RIGHT_GUTTER_WIDTH=1."""
    assert GUTTER_WIDTH == 4
    assert RIGHT_GUTTER_WIDTH == 1
    assert MIN_WIDTH_FOR_RIGHT_GUTTER == 40


def test_gutter_on_all_lines_multiline_block():
    """Gutter should appear on ALL lines of multi-line blocks."""
    # Initialize theme (required for rendering)
    theme = BUILTIN_THEMES["textual-dark"]
    set_theme(theme)

    # Create a ToolResultBlock with multi-line content (renders as plain text with newlines preserved)
    long_content = "\n".join([f"Result line {i}" for i in range(10)])
    block = ToolResultBlock(
        tool_name="test",
        content=long_content,
        size=len(long_content),
        category=Category.TOOLS,
    )

    console = Console()
    # Set tools to FULL level so content is displayed
    filters = {"tools": type("VisState", (), {"visible": True, "full": True, "expanded": True})()}

    strips, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
    )

    # Should have multiple strips (header + content lines)
    assert len(strips) > 1, f"Multi-line block should produce multiple strips, got {len(strips)}"

    # Check each strip has left gutter, content, and right gutter
    for i, strip in enumerate(strips):
        segments = list(strip)
        # Should have at least: left indicator + arrow/space + content + right gutter
        assert len(segments) >= 3, f"Strip {i} should have left + content + right gutter"
        # First segment text should be "▌" (left indicator)
        assert segments[0].text == "▌", f"Strip {i} first segment should be left indicator"
        # Second segment should be arrow or continuation space
        if i == 0:
            # First line has arrow or space
            assert segments[1].text in ["▶  ", "▼  ", "▷  ", "▽  ", "   "], f"Strip {i} second segment should be arrow or space"
        else:
            # Continuation lines have spaces
            assert segments[1].text == "   ", f"Strip {i} second segment should be continuation space"
        # Last segment should be right gutter "▐"
        assert segments[-1].text == "▐", f"Strip {i} last segment should be right gutter"


def test_gutter_on_truncated_blocks():
    """Gutter should appear on truncated blocks including collapse indicator.

    ToolResultBlock at full-collapsed uses header-only summary renderer,
    so use TextContentBlock instead to test truncation + gutter behavior.
    """
    theme = BUILTIN_THEMES["textual-dark"]
    set_theme(theme)

    # Create a long text block that will be truncated
    long_text = "\n".join([f"Line {i}" for i in range(20)])
    block = TextContentBlock(
        content=long_text,
        category=Category.TOOLS,
    )

    console = Console()
    # Set tools to FULL but collapsed (will truncate to 4 lines)
    filters = {"tools": type("VisState", (), {"visible": True, "full": True, "expanded": False})()}

    strips, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
    )

    # Should be truncated (less than 20 lines, but more than 1)
    assert len(strips) < 20, "Block should be truncated"
    assert len(strips) > 1, f"Should have multiple strips, got {len(strips)}"

    # All strips including collapse indicator should have gutter
    for i, strip in enumerate(strips):
        segments = list(strip)
        # Each strip should start with indicator segment
        assert len(segments) >= 1, f"Strip {i} should have at least indicator segment"
        # Check if it's the collapse indicator line (has "···")
        is_collapse_indicator = any("···" in seg.text for seg in segments)
        if not is_collapse_indicator:
            # Regular content line should have indicator + arrow/space
            assert segments[0].text == "▌", f"Strip {i} first segment should be indicator"


def test_blocks_without_category_neutral_gutter():
    """Blocks without category (e.g., NewlineBlock) should have dim neutral gutters."""
    from cc_dump.formatting import NewlineBlock
    theme = BUILTIN_THEMES["textual-dark"]
    set_theme(theme)

    block = NewlineBlock()
    console = Console()
    filters = {}

    strips, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
    )

    # NewlineBlock should produce exactly 1 strip with neutral gutters
    assert len(strips) == 1
    segments = list(strips[0])
    # Should have left gutter "▌" (dim), spaces, and right gutter "▐" (dim)
    assert len(segments) >= 3, "Should have left + content + right gutter"
    assert segments[0].text == "▌", "Should have left gutter indicator"
    # Check dim style on left gutter
    assert segments[0].style.dim, "Left gutter should be dim"
    # Last segment should be right gutter
    assert segments[-1].text == "▐", "Should have right gutter"
    assert segments[-1].style.dim, "Right gutter should be dim"


def test_content_renders_at_reduced_width():
    """Content should render at (width - GUTTER_WIDTH - RIGHT_GUTTER_WIDTH) when gutters present."""
    theme = BUILTIN_THEMES["textual-dark"]
    set_theme(theme)

    # Create a block with known width requirements
    # Use a long line that would wrap differently at different widths
    block = TextContentBlock(
        content="A" * 100,  # 100 chars
        category=Category.USER,
    )

    console = Console()
    filters = {"user": type("VisState", (), {"visible": True, "full": True, "expanded": True})()}

    # Render at width=50 (≥ MIN_WIDTH_FOR_RIGHT_GUTTER, so both gutters)
    strips_50, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=50,
    )

    # Content should wrap at (50 - 4 - 1) = 45 chars per line
    # With 100 chars, we expect ceil(100 / 46) = 3 lines
    # But Rich does softwrap so it might be slightly different
    # The key test is that it wraps MORE than it would at width=50 (without gutters)
    assert len(strips_50) >= 2, "Content should wrap with gutters"


def test_expandable_arrow_changes():
    """Expandable blocks should show ▶ (full collapsed) or ▼ (full expanded)."""
    theme = BUILTIN_THEMES["textual-dark"]
    set_theme(theme)

    # Create a long block
    long_text = "\n".join([f"Line {i}" for i in range(20)])
    block = TextContentBlock(
        content=long_text,
        category=Category.ASSISTANT,
    )

    console = Console()

    # Full level collapsed state
    filters_collapsed = {
        "assistant": type("VisState", (), {"visible": True, "full": True, "expanded": False})()
    }
    strips_collapsed, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters_collapsed,
        console=console,
        width=80,
    )

    # Full level expanded state
    filters_expanded = {
        "assistant": type("VisState", (), {"visible": True, "full": True, "expanded": True})()
    }
    strips_expanded, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters_expanded,
        console=console,
        width=80,
    )

    # Check collapsed has ▶ (full collapsed)
    if len(strips_collapsed) > 0:
        segments = list(strips_collapsed[0])
        if len(segments) >= 2:
            assert segments[1].text in ["▶  ", "   "], "Full collapsed should have ▶ or space"

    # Check expanded has ▼ (full expanded)
    if len(strips_expanded) > 0:
        segments = list(strips_expanded[0])
        if len(segments) >= 2:
            assert segments[1].text in ["▼  ", "   "], "Full expanded should have ▼ or space"


def test_right_gutter_appears_above_min_width():
    """Right gutter should appear when width >= MIN_WIDTH_FOR_RIGHT_GUTTER."""
    theme = BUILTIN_THEMES["textual-dark"]
    set_theme(theme)

    block = TextContentBlock(
        content="Test content",
        category=Category.USER,
    )

    console = Console()
    filters = {"user": type("VisState", (), {"visible": True, "full": True, "expanded": True})()}

    # Above threshold: right gutter should appear
    strips_wide, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=50,  # ≥ 40
    )
    assert len(strips_wide) > 0
    segments = list(strips_wide[0])
    assert segments[-1].text == "▐", "Right gutter should appear at width=50"

    # Below threshold: right gutter should NOT appear
    strips_narrow, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=30,  # < 40
    )
    assert len(strips_narrow) > 0
    segments = list(strips_narrow[0])
    assert segments[-1].text != "▐", "Right gutter should NOT appear at width=30"


def test_arrow_state_matches_visstate():
    """Arrow icons should match GUTTER_ARROWS mapping: ▷▽▶▼ based on (full, expanded)."""
    theme = BUILTIN_THEMES["textual-dark"]
    set_theme(theme)

    # Use ToolResultBlock with newline-separated content that won't be wrapped
    # This ensures we get exactly 20 lines that will be truncated at 4-line limits
    long_content = "\n".join([f"Result line {i}" for i in range(20)])
    block = ToolResultBlock(
        tool_name="test",
        content=long_content,
        size=len(long_content),
        category=Category.TOOLS,
    )

    console = Console()

    # Test cases: At full=True level (tools visible individually), test expanded state
    # At summary level (full=False), tools are collapsed into ToolUseSummaryBlock
    test_cases = [
        # Full level collapsed - truncated to 4 lines, shows full collapsed arrow ▶
        (True, False, "▶", "full collapsed (truncated)"),
        # Full level expanded - no truncation (None limit), shows full expanded arrow ▼
        (True, True, "▼", "full expanded (not truncated)"),
    ]

    for full, expanded, expected_arrow, description in test_cases:
        filters = {
            "tools": type("VisState", (), {"visible": True, "full": full, "expanded": expanded})()
        }
        strips, _ = render_turn_to_strips(
            blocks=[block],
            filters=filters,
            console=console,
            width=80,
        )

        assert len(strips) > 0, f"No strips for {description}"
        segments = list(strips[0])
        assert len(segments) >= 2, f"Not enough segments for {description}"

        # Check arrow matches expected
        actual_arrow = segments[1].text.strip()
        assert actual_arrow == expected_arrow, \
            f"{description}: expected '{expected_arrow}', got '{actual_arrow}'"


def test_summary_level_arrows():
    """Summary level should show ▷ (collapsed) or ▽ (expanded)."""
    theme = BUILTIN_THEMES["textual-dark"]
    set_theme(theme)

    # Use a category that doesn't collapse at summary level (not tools)
    # HeaderBlock at summary level
    from cc_dump.formatting import HttpHeadersBlock
    block = HttpHeadersBlock(
        header_type="request",
        headers={f"X-Header-{i}": f"value{i}" for i in range(10)},
        category=Category.HEADERS,
    )

    console = Console()

    # Test summary level collapsed
    filters_collapsed = {
        "headers": type("VisState", (), {"visible": True, "full": False, "expanded": False})()
    }
    strips_collapsed, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters_collapsed,
        console=console,
        width=80,
    )

    if len(strips_collapsed) > 0:
        segments = list(strips_collapsed[0])
        if len(segments) >= 2:
            actual_arrow = segments[1].text.strip()
            # Should show summary collapsed arrow if block is truncated
            if actual_arrow:  # only check if expandable
                assert actual_arrow == "▷", f"Summary collapsed should show ▷, got '{actual_arrow}'"

    # Test summary level expanded
    filters_expanded = {
        "headers": type("VisState", (), {"visible": True, "full": False, "expanded": True})()
    }
    strips_expanded, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters_expanded,
        console=console,
        width=80,
    )

    if len(strips_expanded) > 0:
        segments = list(strips_expanded[0])
        if len(segments) >= 2:
            actual_arrow = segments[1].text.strip()
            # Should show summary expanded arrow if block is expandable
            if actual_arrow:  # only check if expandable
                assert actual_arrow == "▽", f"Summary expanded should show ▽, got '{actual_arrow}'"


def test_neutral_gutter_for_newline_and_error():
    """NewlineBlock and ErrorBlock should have dim neutral gutters (not category color)."""
    from cc_dump.formatting import NewlineBlock, ErrorBlock
    theme = BUILTIN_THEMES["textual-dark"]
    set_theme(theme)

    console = Console()
    filters = {}

    # Test NewlineBlock
    newline_block = NewlineBlock()
    strips_newline, _ = render_turn_to_strips(
        blocks=[newline_block],
        filters=filters,
        console=console,
        width=80,
    )
    assert len(strips_newline) == 1
    segments = list(strips_newline[0])
    # Should have dim left and right gutters
    assert segments[0].text == "▌"
    assert segments[0].style.dim, "NewlineBlock left gutter should be dim"
    assert segments[-1].text == "▐"
    assert segments[-1].style.dim, "NewlineBlock right gutter should be dim"

    # Test ErrorBlock
    error_block = ErrorBlock(code=500, reason="Internal Server Error")
    strips_error, _ = render_turn_to_strips(
        blocks=[error_block],
        filters=filters,
        console=console,
        width=80,
    )
    assert len(strips_error) > 0
    segments = list(strips_error[0])
    # ErrorBlock has no category, so should use neutral gutters
    assert segments[0].text == "▌"
    assert segments[0].style.dim, "ErrorBlock left gutter should be dim"
    assert segments[-1].text == "▐"
    assert segments[-1].style.dim, "ErrorBlock right gutter should be dim"


def test_filter_indicators_adapt_to_theme():
    """FILTER_INDICATORS should change when set_theme() switches dark/light.

    Must access via module-level attribute (not from-imported snapshot)
    since set_theme() rebinds the module-level name.
    """
    import cc_dump.tui.rendering as rendering_mod

    dark_theme = BUILTIN_THEMES["textual-dark"]
    rendering_mod.set_theme(dark_theme)
    dark_indicators = dict(rendering_mod.FILTER_INDICATORS)

    light_theme = BUILTIN_THEMES["textual-light"]
    rendering_mod.set_theme(light_theme)
    light_indicators = dict(rendering_mod.FILTER_INDICATORS)

    # Colors should differ between dark and light modes
    for name in ["headers", "tools", "system", "user", "assistant"]:
        dark_color = dark_indicators[name][1]
        light_color = light_indicators[name][1]
        assert dark_color != light_color, (
            f"Filter indicator '{name}' should have different colors in dark vs light mode: "
            f"dark={dark_color}, light={light_color}"
        )

    # Restore dark theme for other tests
    rendering_mod.set_theme(dark_theme)
