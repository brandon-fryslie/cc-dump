"""Tests for collapsible XML sub-blocks within TextContentBlock."""

from cc_dump.formatting import TextContentBlock, ContentRegion, Category, ALWAYS_VISIBLE
from cc_dump.tui.rendering import (
    render_turn_to_strips,
    set_theme,
    _render_xml_collapsed,
    _render_region_parts,
    _ensure_content_regions,
)
from cc_dump.segmentation import segment, SubBlockKind
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
    """_render_xml_collapsed returns a renderable with arrow, tag pair, and preview."""
    _setup_theme()
    result = _render_xml_collapsed("thinking", "some inner content here")
    plain = _render_to_text(result)
    assert "▷" in plain
    assert "<thinking>" in plain
    assert "</thinking>" in plain
    assert "some inner content here" in plain


def test_render_xml_collapsed_various_tags():
    """Different tag names and inner text render correctly."""
    _setup_theme()
    for tag, inner in [("search_results", "result data"), ("x", "y"), ("my-tag", "")]:
        result = _render_xml_collapsed(tag, inner)
        plain = _render_to_text(result)
        assert f"<{tag}>" in plain
        assert f"</{tag}>" in plain


def test_render_xml_collapsed_truncates_long_preview():
    """Long inner text is truncated with ellipsis."""
    _setup_theme()
    long_text = "A" * 100
    result = _render_xml_collapsed("tag", long_text)
    plain = _render_to_text(result)
    assert "\u2026" in plain  # ellipsis
    assert "<tag>" in plain
    assert "</tag>" in plain


def test_render_xml_collapsed_multiline_preview():
    """Multi-line inner text is flattened to single line."""
    _setup_theme()
    inner = "Line 1\nLine 2\nLine 3"
    result = _render_xml_collapsed("thinking", inner)
    plain = _render_to_text(result)
    assert "Line 1 Line 2 Line 3" in plain
    assert "\n" not in plain.split("▷")[1].split("</thinking>")[0]


# ─── Segmentation: XML form detection ─────────────────────────────────────


def test_segment_form_b_tags_on_own_lines():
    """Form B: <tag>\\ncontent\\n</tag> — tags on their own lines."""
    text = "before\n<thinking>\ninner content\n</thinking>\nafter"
    result = segment(text)
    xml_blocks = [sb for sb in result.sub_blocks if sb.kind == SubBlockKind.XML_BLOCK]
    assert len(xml_blocks) == 1
    assert xml_blocks[0].meta.tag_name == "thinking"
    inner = text[xml_blocks[0].meta.inner_span.start : xml_blocks[0].meta.inner_span.end]
    assert "inner content" in inner


def test_segment_form_a_content_after_open_tag():
    """Form A: <tag>content after open tag\\n...\\n</tag>."""
    text = "before\n<thinking>I need to think\nabout this\n</thinking>\nafter"
    result = segment(text)
    xml_blocks = [sb for sb in result.sub_blocks if sb.kind == SubBlockKind.XML_BLOCK]
    assert len(xml_blocks) == 1
    assert xml_blocks[0].meta.tag_name == "thinking"
    inner = text[xml_blocks[0].meta.inner_span.start : xml_blocks[0].meta.inner_span.end]
    assert "I need to think" in inner


def test_segment_form_c_single_line():
    """Form C: <tag>content</tag> — all on one line."""
    text = "before\n<note>short note</note>\nafter"
    result = segment(text)
    xml_blocks = [sb for sb in result.sub_blocks if sb.kind == SubBlockKind.XML_BLOCK]
    assert len(xml_blocks) == 1
    assert xml_blocks[0].meta.tag_name == "note"
    inner = text[xml_blocks[0].meta.inner_span.start : xml_blocks[0].meta.inner_span.end]
    assert inner == "short note"


def test_segment_form_c_with_attributes():
    """Form C with attributes: <tag attr='val'>content</tag>."""
    text = "<result type='text'>hello world</result>"
    result = segment(text)
    xml_blocks = [sb for sb in result.sub_blocks if sb.kind == SubBlockKind.XML_BLOCK]
    assert len(xml_blocks) == 1
    assert xml_blocks[0].meta.tag_name == "result"
    inner = text[xml_blocks[0].meta.inner_span.start : xml_blocks[0].meta.inner_span.end]
    assert inner == "hello world"


def test_segment_mixed_forms():
    """Multiple XML blocks using different forms in the same text."""
    text = (
        "<thinking>quick thought</thinking>\n"
        "<details>\nmulti-line\ncontent\n</details>\n"
        "<note>another inline note\nwith continuation\n</note>"
    )
    result = segment(text)
    xml_blocks = [sb for sb in result.sub_blocks if sb.kind == SubBlockKind.XML_BLOCK]
    assert len(xml_blocks) == 3
    assert xml_blocks[0].meta.tag_name == "thinking"
    assert xml_blocks[1].meta.tag_name == "details"
    assert xml_blocks[2].meta.tag_name == "note"


def test_segment_self_closing_excluded():
    """Self-closing tags like <br/> are not treated as XML blocks."""
    text = "text\n<br/>\nmore text"
    result = segment(text)
    xml_blocks = [sb for sb in result.sub_blocks if sb.kind == SubBlockKind.XML_BLOCK]
    assert len(xml_blocks) == 0


def test_segment_start_tag_span_covers_just_tag():
    """start_tag_span covers only the <tag> part, not the whole line."""
    text = "<thinking>content here\nmore\n</thinking>"
    result = segment(text)
    xml_blocks = [sb for sb in result.sub_blocks if sb.kind == SubBlockKind.XML_BLOCK]
    assert len(xml_blocks) == 1
    start_tag = text[xml_blocks[0].meta.start_tag_span.start : xml_blocks[0].meta.start_tag_span.end]
    assert start_tag == "<thinking>"


def test_segment_end_tag_span_covers_just_tag():
    """end_tag_span covers only the </tag> part."""
    text = "<thinking>\ncontent\n</thinking>"
    result = segment(text)
    xml_blocks = [sb for sb in result.sub_blocks if sb.kind == SubBlockKind.XML_BLOCK]
    assert len(xml_blocks) == 1
    end_tag = text[xml_blocks[0].meta.end_tag_span.start : xml_blocks[0].meta.end_tag_span.end]
    assert end_tag == "</thinking>"


# ─── _ensure_content_regions ───────────────────────────────────────────────


def test_ensure_content_regions_with_xml_content():
    """Block with XML tags gets content_regions populated."""
    _setup_theme()
    text = "Some text\n<thinking>\ninner content\n</thinking>\nmore text"
    block = TextContentBlock(text=text, category=Category.ASSISTANT)
    _ensure_content_regions(block)
    assert len(block.content_regions) == 1
    assert block.content_regions[0].index == 0


def test_ensure_content_regions_form_a():
    """Block with Form A XML gets content_regions populated."""
    _setup_theme()
    text = "Some text\n<thinking>content after tag\nmore\n</thinking>\nend"
    block = TextContentBlock(text=text, category=Category.ASSISTANT)
    _ensure_content_regions(block)
    assert len(block.content_regions) == 1


def test_ensure_content_regions_form_c():
    """Block with Form C single-line XML gets content_regions populated."""
    _setup_theme()
    text = "Some text\n<note>inline note</note>\nend"
    block = TextContentBlock(text=text, category=Category.ASSISTANT)
    _ensure_content_regions(block)
    assert len(block.content_regions) == 1


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
    """Collapsed XML sub-block renders with preview text."""
    _setup_theme()
    text = "Intro text\n<thinking>\nLine 1\nLine 2\nLine 3\n</thinking>\nConclusion"
    block = TextContentBlock(text=text, category=Category.ASSISTANT)
    block.content_regions = [ContentRegion(index=0, expanded=False)]
    parts = _render_region_parts(block)

    # Find the XML part
    xml_parts = [(r, idx) for r, idx in parts if idx is not None]
    assert len(xml_parts) == 1
    renderable, _ = xml_parts[0]

    # Collapsed XML should show arrow, both tags, and preview content
    plain = _render_to_text(renderable)
    assert "▷" in plain
    assert "<thinking>" in plain
    assert "</thinking>" in plain
    assert "Line 1" in plain


def test_region_parts_form_a_collapsed():
    """Form A collapsed: shows content preview from after open tag."""
    _setup_theme()
    text = "Intro\n<thinking>I need to think\nabout something\n</thinking>\nEnd"
    block = TextContentBlock(text=text, category=Category.ASSISTANT)
    block.content_regions = [ContentRegion(index=0, expanded=False)]
    parts = _render_region_parts(block)

    xml_parts = [(r, idx) for r, idx in parts if idx is not None]
    assert len(xml_parts) == 1
    plain = _render_to_text(xml_parts[0][0])
    assert "▷" in plain
    assert "I need to think" in plain


def test_region_parts_form_c_collapsed():
    """Form C collapsed: single-line XML shows content."""
    _setup_theme()
    text = "Intro\n<note>short note</note>\nEnd"
    block = TextContentBlock(text=text, category=Category.ASSISTANT)
    block.content_regions = [ContentRegion(index=0, expanded=False)]
    parts = _render_region_parts(block)

    xml_parts = [(r, idx) for r, idx in parts if idx is not None]
    assert len(xml_parts) == 1
    plain = _render_to_text(xml_parts[0][0])
    assert "▷" in plain
    assert "short note" in plain


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


# ─── Form A/C rendering through full pipeline ─────────────────────────────


def test_form_a_renders_as_xml_block():
    """Form A content renders with syntax-highlighted tags (not backtick-wrapped)."""
    _setup_theme()
    text = "<thinking>I need to think\nabout this problem\n</thinking>"
    block = TextContentBlock(text=text, category=Category.ASSISTANT)

    console = Console()
    filters = {"assistant": ALWAYS_VISIBLE}

    strips, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
    )

    # Should have content_regions (detected as XML)
    assert len(block.content_regions) == 1


def test_form_c_renders_as_xml_block():
    """Form C single-line renders with syntax-highlighted tags."""
    _setup_theme()
    text = "<note>short note</note>"
    block = TextContentBlock(text=text, category=Category.ASSISTANT)

    console = Console()
    filters = {"assistant": ALWAYS_VISIBLE}

    strips, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
    )

    # Should have content_regions (detected as XML)
    assert len(block.content_regions) == 1
