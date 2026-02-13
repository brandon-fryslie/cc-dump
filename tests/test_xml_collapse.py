"""Tests for collapsible XML sub-blocks within TextContentBlock."""

from cc_dump.formatting import TextContentBlock, ContentRegion, Category, ALWAYS_VISIBLE
from cc_dump.tui.rendering import (
    render_turn_to_strips,
    set_theme,
    _render_xml_collapsed,
    _render_region_parts,
    _ensure_content_regions,
)
from rich.console import Console
from textual.theme import BUILTIN_THEMES


def _setup_theme():
    """Initialize theme for tests."""
    theme = BUILTIN_THEMES["textual-dark"]
    set_theme(theme)


# ─── _render_xml_collapsed ─────────────────────────────────────────────────


def _render_to_text(renderable) -> str:
    """Render a ConsoleRenderable to plain text via Console."""
    c = Console(file=__import__("io").StringIO(), width=120)
    c.print(renderable, end="")
    return c.file.getvalue()


def test_render_xml_collapsed_returns_renderable():
    """_render_xml_collapsed returns a renderable with arrow, tag, and line count."""
    _setup_theme()
    result = _render_xml_collapsed("thinking", 47)
    plain = _render_to_text(result)
    assert "▷" in plain
    assert "<thinking>" in plain
    assert "47 lines" in plain


def test_render_xml_collapsed_various_tags():
    """Different tag names and line counts render correctly."""
    _setup_theme()
    for tag, lines in [("search_results", 100), ("x", 1), ("my-tag", 0)]:
        result = _render_xml_collapsed(tag, lines)
        plain = _render_to_text(result)
        assert f"<{tag}>" in plain
        assert f"{lines} lines" in plain


# ─── _ensure_content_regions ───────────────────────────────────────────────


def test_ensure_content_regions_with_xml_content():
    """Block with XML tags gets content_regions populated."""
    _setup_theme()
    text = "Some text\n<thinking>\ninner content\n</thinking>\nmore text"
    block = TextContentBlock(text=text, category=Category.ASSISTANT)
    _ensure_content_regions(block)
    assert len(block.content_regions) == 1
    assert block.content_regions[0].index == 0


def test_ensure_content_regions_without_xml():
    """Block without XML tags gets no content_regions."""
    _setup_theme()
    block = TextContentBlock(text="Just plain text", category=Category.ASSISTANT)
    _ensure_content_regions(block)
    assert block.content_regions == []


def test_ensure_content_regions_wrong_category():
    """Block with XML but non-markdown category gets no content_regions."""
    _setup_theme()
    text = "Some text\n<thinking>\ninner content\n</thinking>\nmore text"
    block = TextContentBlock(text=text, category=Category.TOOLS)
    _ensure_content_regions(block)
    assert block.content_regions == []


def test_ensure_content_regions_no_text():
    """Block with empty text gets no content_regions."""
    _setup_theme()
    block = TextContentBlock(text="", category=Category.ASSISTANT)
    _ensure_content_regions(block)
    assert block.content_regions == []


def test_ensure_content_regions_idempotent():
    """Calling _ensure_content_regions twice preserves existing regions."""
    _setup_theme()
    text = "Some text\n<thinking>\ninner content\n</thinking>\nmore text"
    block = TextContentBlock(text=text, category=Category.ASSISTANT)
    _ensure_content_regions(block)
    # Modify a region's state
    block.content_regions[0].expanded = False
    # Call again — should not overwrite
    _ensure_content_regions(block)
    assert block.content_regions[0].expanded is False


# ─── _render_region_parts ─────────────────────────────────────────────────


def test_region_parts_no_xml():
    """Text without XML returns single part with None index."""
    _setup_theme()
    block = TextContentBlock(text="Hello world", category=Category.ASSISTANT)
    block.content_regions = []  # no regions
    parts = _render_region_parts(block)
    assert len(parts) == 1
    renderable, idx = parts[0]
    assert idx is None


def test_region_parts_with_xml_expanded():
    """Text with XML returns parts including XML with index, all expanded by default."""
    _setup_theme()
    text = "Intro text\n<thinking>\nI need to think about this\n</thinking>\nConclusion"
    block = TextContentBlock(text=text, category=Category.ASSISTANT)
    _ensure_content_regions(block)
    parts = _render_region_parts(block)

    # Should have multiple parts: MD before, XML block, MD after
    assert len(parts) >= 2  # at least intro+xml or xml+conclusion

    # Find the XML part
    xml_parts = [(r, idx) for r, idx in parts if idx is not None]
    assert len(xml_parts) == 1, f"Expected 1 XML part, got {len(xml_parts)}"
    _, xml_idx = xml_parts[0]
    assert xml_idx == 0  # first XML block


def test_region_parts_xml_collapsed():
    """Collapsed XML sub-block renders as single-line indicator."""
    _setup_theme()
    text = "Intro text\n<thinking>\nLine 1\nLine 2\nLine 3\n</thinking>\nConclusion"
    block = TextContentBlock(text=text, category=Category.ASSISTANT)
    block.content_regions = [ContentRegion(index=0, expanded=False)]
    parts = _render_region_parts(block)

    # Find the XML part
    xml_parts = [(r, idx) for r, idx in parts if idx is not None]
    assert len(xml_parts) == 1
    renderable, _ = xml_parts[0]

    # Collapsed XML should be a renderable with ▷
    plain = _render_to_text(renderable)
    assert "▷" in plain
    assert "<thinking>" in plain
    assert "lines" in plain


def test_region_parts_multiple_xml_blocks():
    """Multiple XML blocks get sequential indices."""
    _setup_theme()
    text = (
        "Before\n"
        "<thinking>\nThought 1\n</thinking>\n"
        "Middle\n"
        "<search_results>\nResult 1\n</search_results>\n"
        "After"
    )
    block = TextContentBlock(text=text, category=Category.ASSISTANT)
    _ensure_content_regions(block)
    parts = _render_region_parts(block)

    xml_parts = [(r, idx) for r, idx in parts if idx is not None]
    assert len(xml_parts) == 2
    assert xml_parts[0][1] == 0
    assert xml_parts[1][1] == 1


def test_region_parts_mixed_collapse():
    """One XML collapsed, another expanded."""
    _setup_theme()
    text = (
        "Before\n"
        "<thinking>\nThought 1\n</thinking>\n"
        "Middle\n"
        "<search_results>\nResult 1\n</search_results>\n"
        "After"
    )
    block = TextContentBlock(text=text, category=Category.ASSISTANT)
    block.content_regions = [
        ContentRegion(index=0, expanded=False),  # thinking collapsed
        ContentRegion(index=1, expanded=None),    # search expanded (default)
    ]
    parts = _render_region_parts(block)

    xml_parts = [(r, idx) for r, idx in parts if idx is not None]
    assert len(xml_parts) == 2

    # First XML (thinking) should be collapsed (renderable with ▷)
    plain = _render_to_text(xml_parts[0][0])
    assert "▷" in plain

    # Second XML (search_results) should be expanded (renderable with ▽)
    plain2 = _render_to_text(xml_parts[1][0])
    assert "▽" in plain2


# ─── render_turn_to_strips with XML ────────────────────────────────────────


def test_xml_block_renders_with_content_regions():
    """TextContentBlock with XML sets content_regions with _strip_range on each."""
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

    # Block should have content_regions populated
    assert len(block.content_regions) == 1
    region = block.content_regions[0]
    assert region._strip_range is not None, "Region should have strip range set"

    # Range should be valid
    start, end = region._strip_range
    assert start >= 0
    assert end > start


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
    block_collapsed.content_regions = [ContentRegion(index=0, expanded=False)]
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


def test_xml_no_content_regions_for_plain_text():
    """TextContentBlock without XML has empty content_regions."""
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

    # Should have empty content_regions
    assert block.content_regions == []


def test_xml_expanded_survives_rerender():
    """content_regions state persists across re-renders (same block object)."""
    _setup_theme()
    text = "Intro\n<thinking>\nLine 1\nLine 2\n</thinking>\nEnd"
    block = TextContentBlock(text=text, category=Category.ASSISTANT)
    block.content_regions = [ContentRegion(index=0, expanded=False)]

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
    assert block.content_regions[0].expanded is False

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
