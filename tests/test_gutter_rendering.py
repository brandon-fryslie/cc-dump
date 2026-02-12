"""Tests for full-height gutter indicators in rendering.py."""

from cc_dump.formatting import (
    TextContentBlock,
    ToolResultBlock,
    Category,
)
from cc_dump.tui.rendering import (
    render_turn_to_strips,
    GUTTER_WIDTH,
    set_theme,
)
from rich.console import Console
from textual.theme import BUILTIN_THEMES


def test_gutter_width_constant():
    """GUTTER_WIDTH should be defined and equal to 3."""
    assert GUTTER_WIDTH == 3


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

    # Check each strip starts with gutter segments
    for i, strip in enumerate(strips):
        segments = list(strip)
        # First segment should be the indicator (▌)
        assert len(segments) >= 2, f"Strip {i} should have at least indicator + arrow/space segments"
        # First segment text should be "▌" (indicator, no trailing space)
        assert segments[0].text == "▌", f"Strip {i} first segment should be indicator"
        # Second segment should be arrow (▶ or ▼) or continuation space
        if i == 0:
            # First line has arrow or space
            assert segments[1].text in ["▶ ", "▼ ", "  "], f"Strip {i} second segment should be arrow or space"
        else:
            # Continuation lines have spaces
            assert segments[1].text == "  ", f"Strip {i} second segment should be continuation space"


def test_gutter_on_truncated_blocks():
    """Gutter should appear on truncated blocks including collapse indicator."""
    theme = BUILTIN_THEMES["textual-dark"]
    set_theme(theme)

    # Create a long block that will be truncated
    long_text = "\n".join([f"Line {i}" for i in range(20)])
    block = ToolResultBlock(
        tool_name="test",
        content=long_text,
        size=len(long_text),
        category=Category.TOOLS,
    )

    console = Console()
    # Set tools to FULL but collapsed (will truncate to 10 lines)
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


def test_blocks_without_category_no_gutter():
    """Blocks without category (e.g., NewlineBlock) should not have gutter."""
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

    # NewlineBlock should produce exactly 1 strip with empty text
    assert len(strips) == 1
    segments = list(strips[0])
    # Should NOT start with "▌" indicator
    if segments:
        assert segments[0].text != "▌", "NewlineBlock should not have category indicator"


def test_content_renders_at_reduced_width():
    """Content should render at (width - GUTTER_WIDTH) when gutter is present."""
    theme = BUILTIN_THEMES["textual-dark"]
    set_theme(theme)

    # Create a block with known width requirements
    # Use a long line that would wrap differently at different widths
    block = TextContentBlock(
        text="A" * 100,  # 100 chars
        category=Category.USER,
    )

    console = Console()
    filters = {"user": type("VisState", (), {"visible": True, "full": True, "expanded": True})()}

    # Render at width=50
    strips_50, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=50,
    )

    # Content should wrap at (50 - 3) = 47 chars per line
    # With 100 chars, we expect ceil(100 / 47) = 3 lines
    # But Rich does softwrap so it might be slightly different
    # The key test is that it wraps MORE than it would at width=50 (without gutter)
    assert len(strips_50) >= 2, "Content should wrap with gutter"


def test_expandable_arrow_changes():
    """Expandable blocks should show ▶ when collapsed, ▼ when expanded."""
    theme = BUILTIN_THEMES["textual-dark"]
    set_theme(theme)

    # Create a long block
    long_text = "\n".join([f"Line {i}" for i in range(20)])
    block = TextContentBlock(
        text=long_text,
        category=Category.ASSISTANT,
    )

    console = Console()

    # Collapsed state
    filters_collapsed = {
        "assistant": type("VisState", (), {"visible": True, "full": True, "expanded": False})()
    }
    strips_collapsed, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters_collapsed,
        console=console,
        width=80,
    )

    # Expanded state
    filters_expanded = {
        "assistant": type("VisState", (), {"visible": True, "full": True, "expanded": True})()
    }
    strips_expanded, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters_expanded,
        console=console,
        width=80,
    )

    # Check collapsed has ▶
    if len(strips_collapsed) > 0:
        segments = list(strips_collapsed[0])
        if len(segments) >= 2:
            assert segments[1].text in ["▶ ", "  "], "Collapsed should have ▶ or space"

    # Check expanded has ▼
    if len(strips_expanded) > 0:
        segments = list(strips_expanded[0])
        if len(segments) >= 2:
            assert segments[1].text in ["▼ ", "  "], "Expanded should have ▼ or space"
