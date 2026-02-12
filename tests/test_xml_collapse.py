"""Tests for collapsible XML sub-blocks within TextContentBlock."""

from cc_dump.formatting import TextContentBlock, Category, ALWAYS_VISIBLE
from cc_dump.tui.rendering import (
    render_turn_to_strips,
    set_theme,
    _render_xml_collapsed,
    _render_segmented_parts,
    _block_has_xml,
    GUTTER_WIDTH,
)
from rich.console import Console
from rich.text import Text
from textual.theme import BUILTIN_THEMES


def _setup_theme():
    """Initialize theme for tests."""
    theme = BUILTIN_THEMES["textual-dark"]
    set_theme(theme)


# ─── _render_xml_collapsed ─────────────────────────────────────────────────


def test_render_xml_collapsed_returns_text():
    """_render_xml_collapsed returns a Text with arrow, tag, and line count."""
    _setup_theme()
    result = _render_xml_collapsed("thinking", 47)
    assert isinstance(result, Text)
    plain = result.plain
    assert "▷" in plain
    assert "<thinking>" in plain
    assert "47 lines" in plain


def test_render_xml_collapsed_various_tags():
    """Different tag names and line counts render correctly."""
    _setup_theme()
    for tag, lines in [("search_results", 100), ("x", 1), ("my-tag", 0)]:
        result = _render_xml_collapsed(tag, lines)
        assert f"<{tag}>" in result.plain
        assert f"{lines} lines" in result.plain


# ─── _block_has_xml ─────────────────────────────────────────────────────────


def test_block_has_xml_with_xml_content():
    """Block with XML tags is detected."""
    _setup_theme()
    text = "Some text\n<thinking>\ninner content\n</thinking>\nmore text"
    block = TextContentBlock(text=text, category=Category.ASSISTANT)
    assert _block_has_xml(block) is True


def test_block_has_xml_without_xml():
    """Block without XML tags is not detected."""
    _setup_theme()
    block = TextContentBlock(text="Just plain text", category=Category.ASSISTANT)
    assert _block_has_xml(block) is False


def test_block_has_xml_wrong_category():
    """Block with XML but non-markdown category is not detected."""
    _setup_theme()
    text = "Some text\n<thinking>\ninner content\n</thinking>\nmore text"
    block = TextContentBlock(text=text, category=Category.TOOLS)
    assert _block_has_xml(block) is False


def test_block_has_xml_no_text():
    """Block with empty text is not detected."""
    _setup_theme()
    block = TextContentBlock(text="", category=Category.ASSISTANT)
    assert _block_has_xml(block) is False


# ─── _render_segmented_parts ───────────────────────────────────────────────


def test_segmented_parts_no_xml():
    """Text without XML returns single part with None index."""
    _setup_theme()
    parts = _render_segmented_parts("Hello world", None)
    assert len(parts) == 1
    renderable, idx = parts[0]
    assert idx is None


def test_segmented_parts_with_xml_expanded():
    """Text with XML returns parts including XML with index, all expanded by default."""
    _setup_theme()
    text = "Intro text\n<thinking>\nI need to think about this\n</thinking>\nConclusion"
    parts = _render_segmented_parts(text, None)

    # Should have multiple parts: MD before, XML block, MD after
    assert len(parts) >= 2  # at least intro+xml or xml+conclusion

    # Find the XML part
    xml_parts = [(r, idx) for r, idx in parts if idx is not None]
    assert len(xml_parts) == 1, f"Expected 1 XML part, got {len(xml_parts)}"
    _, xml_idx = xml_parts[0]
    assert xml_idx == 0  # first XML block


def test_segmented_parts_xml_collapsed():
    """Collapsed XML sub-block renders as single-line indicator."""
    _setup_theme()
    text = "Intro text\n<thinking>\nLine 1\nLine 2\nLine 3\n</thinking>\nConclusion"
    xml_expanded = {0: False}  # collapse first XML block
    parts = _render_segmented_parts(text, xml_expanded)

    # Find the XML part
    xml_parts = [(r, idx) for r, idx in parts if idx is not None]
    assert len(xml_parts) == 1
    renderable, _ = xml_parts[0]

    # Collapsed XML should be a Text with ▷
    assert isinstance(renderable, Text)
    assert "▷" in renderable.plain
    assert "<thinking>" in renderable.plain
    assert "lines" in renderable.plain


def test_segmented_parts_multiple_xml_blocks():
    """Multiple XML blocks get sequential indices."""
    _setup_theme()
    text = (
        "Before\n"
        "<thinking>\nThought 1\n</thinking>\n"
        "Middle\n"
        "<search_results>\nResult 1\n</search_results>\n"
        "After"
    )
    parts = _render_segmented_parts(text, None)

    xml_parts = [(r, idx) for r, idx in parts if idx is not None]
    assert len(xml_parts) == 2
    assert xml_parts[0][1] == 0
    assert xml_parts[1][1] == 1


def test_segmented_parts_mixed_collapse():
    """One XML collapsed, another expanded."""
    _setup_theme()
    text = (
        "Before\n"
        "<thinking>\nThought 1\n</thinking>\n"
        "Middle\n"
        "<search_results>\nResult 1\n</search_results>\n"
        "After"
    )
    xml_expanded = {0: False, 1: True}  # thinking collapsed, search expanded
    parts = _render_segmented_parts(text, xml_expanded)

    xml_parts = [(r, idx) for r, idx in parts if idx is not None]
    assert len(xml_parts) == 2

    # First XML (thinking) should be collapsed (Text with ▷)
    assert isinstance(xml_parts[0][0], Text)
    assert "▷" in xml_parts[0][0].plain

    # Second XML (search_results) should be expanded (Group with ▽)
    # It won't be a plain Text since it's expanded
    assert not isinstance(xml_parts[1][0], Text) or "▽" in xml_parts[1][0].plain


# ─── render_turn_to_strips with XML ────────────────────────────────────────


def test_xml_block_renders_with_strip_ranges():
    """TextContentBlock with XML sets _xml_strip_ranges on the block."""
    _setup_theme()
    text = "Intro\n<thinking>\nLine 1\nLine 2\nLine 3\n</thinking>\nEnd"
    block = TextContentBlock(text=text, category=Category.ASSISTANT)

    console = Console()
    filters = {"assistant": ALWAYS_VISIBLE}

    strips, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
    )

    # Block should have _xml_strip_ranges set
    assert hasattr(block, "_xml_strip_ranges")
    assert isinstance(block._xml_strip_ranges, dict)
    assert 0 in block._xml_strip_ranges, "First XML sub-block should have range"

    # Range should be valid
    start, end = block._xml_strip_ranges[0]
    assert start >= 0
    assert end > start
    assert block._xml_expandable is True


def test_xml_collapsed_fewer_strips():
    """Collapsed XML sub-block produces fewer strips than expanded."""
    _setup_theme()
    text = (
        "Before text\n"
        "<thinking>\n"
        + "\n".join(f"Thought line {i}" for i in range(20))
        + "\n</thinking>\n"
        "After text"
    )

    console = Console()
    filters = {"assistant": ALWAYS_VISIBLE}

    # Expanded (default)
    block_expanded = TextContentBlock(text=text, category=Category.ASSISTANT)
    strips_expanded, _ = render_turn_to_strips(
        blocks=[block_expanded],
        filters=filters,
        console=console,
        width=80,
    )

    # Collapsed
    block_collapsed = TextContentBlock(text=text, category=Category.ASSISTANT)
    block_collapsed._xml_expanded = {0: False}
    strips_collapsed, _ = render_turn_to_strips(
        blocks=[block_collapsed],
        filters=filters,
        console=console,
        width=80,
    )

    # Collapsed should have significantly fewer strips
    assert len(strips_collapsed) < len(strips_expanded), (
        f"Collapsed ({len(strips_collapsed)}) should have fewer strips "
        f"than expanded ({len(strips_expanded)})"
    )


def test_xml_no_strip_ranges_for_plain_text():
    """TextContentBlock without XML has empty _xml_strip_ranges."""
    _setup_theme()
    block = TextContentBlock(text="Just plain text", category=Category.ASSISTANT)

    console = Console()
    filters = {"assistant": ALWAYS_VISIBLE}

    render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
    )

    # Should have empty strip ranges
    assert getattr(block, "_xml_strip_ranges", {}) == {}
    assert getattr(block, "_xml_expandable", False) is False


def test_xml_expanded_survives_rerender():
    """_xml_expanded state persists across re-renders (same block object)."""
    _setup_theme()
    text = "Intro\n<thinking>\nLine 1\nLine 2\n</thinking>\nEnd"
    block = TextContentBlock(text=text, category=Category.ASSISTANT)
    block._xml_expanded = {0: False}

    console = Console()
    filters = {"assistant": ALWAYS_VISIBLE}

    # First render
    strips1, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
    )

    # Verify state preserved
    assert block._xml_expanded == {0: False}

    # Second render (same block, should use same state)
    strips2, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
    )

    # Strip counts should be the same
    assert len(strips1) == len(strips2)


# ─── Gutter width with XML ────────────────────────────────────────────────


def test_xml_strips_have_gutter():
    """XML sub-block strips should have the standard gutter."""
    _setup_theme()
    text = "Intro\n<thinking>\nThought\n</thinking>\nEnd"
    block = TextContentBlock(text=text, category=Category.ASSISTANT)

    console = Console()
    filters = {"assistant": ALWAYS_VISIBLE}

    strips, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
    )

    # All strips should have the gutter
    for i, strip in enumerate(strips):
        segments = list(strip)
        assert len(segments) >= 2, f"Strip {i} should have at least left gutter + content"
        assert segments[0].text == "▌", f"Strip {i} should start with left gutter indicator"
