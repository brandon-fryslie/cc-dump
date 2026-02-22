"""Tests for collapsible XML sub-blocks within TextContentBlock."""

from cc_dump.formatting import (
    TextContentBlock,
    ContentRegion,
    Category,
    ALWAYS_VISIBLE,
    VisState,
    populate_content_regions,
)
from cc_dump.tui.rendering import (
    render_turn_to_strips,
    set_theme,
    _render_xml_collapsed,
    _render_code_fence_collapsed,
    _render_region_parts,
    COLLAPSIBLE_REGION_KINDS,
)
from cc_dump.tui.view_overrides import ViewOverrides
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


def test_render_code_fence_collapsed_renders_preview():
    """Collapsed code-fence preview includes language, count, and snippet."""
    _setup_theme()
    result = _render_code_fence_collapsed("python", "print('a')\nprint('b')\n")
    plain = _render_to_text(result)
    assert "▷ ```python```" in plain
    assert "2 lines" in plain
    assert "print('a')" in plain


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


# ─── populate_content_regions ────────────────────────────────────────────


def test_populate_content_regions_with_xml_content():
    """Block with XML tags gets content_regions populated for ALL segments."""
    text = "Some text\n<thinking>\ninner content\n</thinking>\nmore text"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)
    # 3 segments: MD, XML, MD
    assert len(block.content_regions) == 3
    assert block.content_regions[0].kind == "md"
    assert block.content_regions[1].kind == "xml_block"
    assert block.content_regions[1].tags == ["thinking"]
    assert block.content_regions[2].kind == "md"


def test_populate_content_regions_form_a():
    """Block with Form A XML gets content_regions populated."""
    text = "Some text\n<thinking>content after tag\nmore\n</thinking>\nend"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)
    # 3 segments: MD, XML, MD
    assert len(block.content_regions) == 3
    assert block.content_regions[1].kind == "xml_block"


def test_populate_content_regions_form_c():
    """Block with Form C single-line XML gets content_regions populated."""
    text = "Some text\n<note>inline note</note>\nend"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)
    # 3 segments: MD, XML, MD
    assert len(block.content_regions) == 3
    assert block.content_regions[1].kind == "xml_block"
    assert block.content_regions[1].tags == ["note"]


def test_populate_content_regions_plain_text():
    """Block without XML gets regions for MD segments."""
    block = TextContentBlock(content="Just plain text", category=Category.ASSISTANT)
    populate_content_regions(block)
    # 1 segment: MD
    assert len(block.content_regions) == 1
    assert block.content_regions[0].kind == "md"
    assert block.content_regions[0].tags == []


def test_populate_content_regions_any_category():
    """populate_content_regions works for any category (no category gate)."""
    text = "Some text\n<thinking>\ninner content\n</thinking>\nmore text"
    block = TextContentBlock(content=text, category=Category.TOOLS)
    populate_content_regions(block)
    # Should still populate — no category gate in populate_content_regions
    assert len(block.content_regions) == 3
    assert block.content_regions[1].kind == "xml_block"


def test_populate_content_regions_no_text():
    """Block with empty text gets no content_regions."""
    block = TextContentBlock(content="", category=Category.ASSISTANT)
    populate_content_regions(block)
    assert block.content_regions == []


def test_populate_content_regions_idempotent():
    """Calling populate_content_regions twice preserves existing regions."""
    text = "Some text\n<thinking>\ninner content\n</thinking>\nmore text"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)
    # Capture region identity
    original_regions = list(block.content_regions)
    # Call again — should not overwrite
    populate_content_regions(block)
    assert block.content_regions == original_regions


def test_populate_all_segments():
    """Text with MD + XML + CODE_FENCE → correct kinds and tags."""
    text = "Intro\n<thinking>\nthought\n</thinking>\n```python\nprint('hi')\n```\nEnd"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)
    kinds = [r.kind for r in block.content_regions]
    assert "md" in kinds
    assert "xml_block" in kinds
    assert "code_fence" in kinds
    # XML region should have tag name
    xml_regions = [r for r in block.content_regions if r.kind == "xml_block"]
    assert xml_regions[0].tags == ["thinking"]
    # Code fence region should have language tag
    code_regions = [r for r in block.content_regions if r.kind == "code_fence"]
    assert code_regions[0].tags == ["python"]


def test_populate_tag_values():
    """XML tag names and code fence info are extracted correctly."""
    text = "<system-reminder>\nHello\n</system-reminder>\n```javascript\nconsole.log();\n```"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)
    xml_regions = [r for r in block.content_regions if r.kind == "xml_block"]
    code_regions = [r for r in block.content_regions if r.kind == "code_fence"]
    assert xml_regions[0].tags == ["system-reminder"]
    assert code_regions[0].tags == ["javascript"]


def test_populate_content_regions_derives_claude_md_tag():
    """Content-derived tags include CLAUDE.md marker for MD regions."""
    text = "Please read CLAUDE.md before running this workflow."
    block = TextContentBlock(content=text, category=Category.USER)
    populate_content_regions(block)

    assert len(block.content_regions) == 1
    assert block.content_regions[0].kind == "md"
    assert "claude_md" in block.content_regions[0].tags


def test_populate_content_regions_merges_xml_and_derived_tags():
    """XML regions keep structural tag names and append derived semantic tags."""
    text = (
        "<system-reminder>\n"
        "The following skills are available for use with the Skill tool.\n"
        "The following tools are available.\n"
        "</system-reminder>\n"
    )
    block = TextContentBlock(content=text, category=Category.SYSTEM)
    populate_content_regions(block)

    xml_regions = [r for r in block.content_regions if r.kind == "xml_block"]
    assert len(xml_regions) == 1
    tags = set(xml_regions[0].tags)
    assert "system-reminder" in tags
    assert "skill_consideration" in tags
    assert "tool_use_list" in tags


# ─── _render_region_parts ─────────────────────────────────────────────────


def test_region_parts_no_xml():
    """Text without XML returns single part with region index (MD region)."""
    _setup_theme()
    block = TextContentBlock(content="Hello world", category=Category.ASSISTANT)
    populate_content_regions(block)
    parts = _render_region_parts(block)
    assert len(parts) == 1
    renderable, idx = parts[0]
    # MD region gets index 0 (not None — all segments have region_idx)
    assert idx == 0


def test_region_parts_no_regions_fallback():
    """Text with no regions at all returns fallback with None index."""
    _setup_theme()
    block = TextContentBlock(content="Hello world", category=Category.ASSISTANT)
    block.content_regions = []  # explicitly empty
    parts = _render_region_parts(block)
    assert len(parts) == 1
    renderable, idx = parts[0]
    assert idx is None  # fallback path


def test_region_parts_with_xml_expanded():
    """Text with XML returns parts including XML with correct index, all expanded by default."""
    _setup_theme()
    text = "Intro text\n<thinking>\nI need to think about this\n</thinking>\nConclusion"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)
    parts = _render_region_parts(block)

    # Should have 3 parts: MD before (idx=0), XML block (idx=1), MD after (idx=2)
    assert len(parts) >= 2  # at least intro+xml or xml+conclusion

    # Find the XML part — it's at index 1 in the segment sequence
    xml_parts = [(r, idx) for r, idx in parts if idx == 1]
    assert len(xml_parts) == 1, f"Expected 1 XML part at index 1, got {len(xml_parts)}"


def test_region_parts_xml_collapsed():
    """Collapsed XML sub-block renders with preview text."""
    _setup_theme()
    text = "Intro text\n<thinking>\nLine 1\nLine 2\nLine 3\n</thinking>\nConclusion"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)
    # Collapse the XML region (index 1) via ViewOverrides
    overrides = ViewOverrides()
    overrides.get_region(block.block_id, 1).expanded = False
    parts = _render_region_parts(block, overrides=overrides)

    # Find the XML part at segment index 1
    xml_parts = [(r, idx) for r, idx in parts if idx == 1]
    assert len(xml_parts) == 1
    renderable, _ = xml_parts[0]

    # Collapsed XML should show arrow, both tags, and preview content
    plain = _render_to_text(renderable)
    assert "▷" in plain
    assert "<thinking>" in plain
    assert "</thinking>" in plain
    assert "Line 1" in plain


def test_region_parts_code_fence_collapsed():
    """Collapsed code_fence region renders compact preview text."""
    _setup_theme()
    text = "```python\nprint('a')\nprint('b')\n```"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)

    code_idx = next(i for i, r in enumerate(block.content_regions) if r.kind == "code_fence")
    overrides = ViewOverrides()
    overrides.get_region(block.block_id, code_idx).expanded = False
    parts = _render_region_parts(block, overrides=overrides)

    assert len(parts) == 1
    renderable, idx = parts[0]
    assert idx == code_idx
    plain = _render_to_text(renderable)
    assert "▷ ```python```" in plain
    assert "2 lines" in plain


def test_region_parts_code_fence_long_defaults_collapsed():
    """Long code fences default to collapsed without explicit override."""
    _setup_theme()
    long_code = "\n".join(f"line_{i}" for i in range(20))
    text = f"```python\n{long_code}\n```"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)

    parts = _render_region_parts(block)
    assert len(parts) == 1
    renderable, _ = parts[0]
    plain = _render_to_text(renderable)
    assert "▷ ```python```" in plain
    assert "20 lines" in plain


def test_region_parts_code_fence_short_defaults_expanded():
    """Short code fences remain expanded by default."""
    _setup_theme()
    text = "```python\nprint('a')\nprint('b')\n```"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)

    parts = _render_region_parts(block)
    assert len(parts) == 1
    renderable, _ = parts[0]
    plain = _render_to_text(renderable)
    assert "▷ ```python```" not in plain
    assert "print('a')" in plain


def test_region_parts_code_fence_default_threshold_from_env(monkeypatch):
    """Code fence default expansion threshold can be tuned via env."""
    _setup_theme()
    monkeypatch.setenv("CC_DUMP_CODE_FENCE_DEFAULT_EXPANDED_MAX_LINES", "1")
    text = "```python\nprint('a')\nprint('b')\n```"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)

    parts = _render_region_parts(block)
    assert len(parts) == 1
    plain = _render_to_text(parts[0][0])
    assert "▷ ```python```" in plain


def test_region_parts_md_fence_long_defaults_collapsed():
    """Long markdown fences default to collapsed."""
    _setup_theme()
    long_md = "\n".join(f"line_{i}" for i in range(20))
    text = f"```\n{long_md}\n```"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)

    parts = _render_region_parts(block)
    assert len(parts) == 1
    plain = _render_to_text(parts[0][0])
    assert "▷ ```md```" in plain
    assert "20 lines" in plain


def test_region_parts_md_fence_short_defaults_expanded():
    """Short markdown fences remain expanded by default."""
    _setup_theme()
    text = "```\nline_1\nline_2\n```"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)

    parts = _render_region_parts(block)
    assert len(parts) == 1
    plain = _render_to_text(parts[0][0])
    assert "▷ ```md```" not in plain
    assert "line_1" in plain


def test_region_parts_md_fence_default_threshold_from_env(monkeypatch):
    """Markdown fence default expansion threshold can be tuned via env."""
    _setup_theme()
    monkeypatch.setenv("CC_DUMP_MD_FENCE_DEFAULT_EXPANDED_MAX_LINES", "1")
    text = "```\nline_1\nline_2\n```"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)

    parts = _render_region_parts(block)
    assert len(parts) == 1
    plain = _render_to_text(parts[0][0])
    assert "▷ ```md```" in plain


def test_region_parts_xml_long_defaults_collapsed():
    """Long XML blocks default to collapsed without explicit override."""
    _setup_theme()
    inner = "\n".join(f"line_{i}" for i in range(14))
    text = f"<thinking>\n{inner}\n</thinking>"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)

    parts = _render_region_parts(block)
    assert len(parts) == 1
    renderable, _ = parts[0]
    plain = _render_to_text(renderable)
    assert "▷" in plain
    assert "<thinking>" in plain


def test_region_parts_xml_short_defaults_expanded():
    """Short XML blocks remain expanded by default."""
    _setup_theme()
    text = "<thinking>\nline_1\nline_2\n</thinking>"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)

    parts = _render_region_parts(block)
    assert len(parts) == 1
    renderable, _ = parts[0]
    plain = _render_to_text(renderable)
    assert "▷" not in plain
    assert "▽ <thinking>" in plain
    assert "line_1" in plain


def test_region_parts_xml_default_threshold_from_env(monkeypatch):
    """XML default expansion threshold can be tuned via env."""
    _setup_theme()
    monkeypatch.setenv("CC_DUMP_XML_BLOCK_DEFAULT_EXPANDED_MAX_LINES", "1")
    text = "<thinking>\nline_1\nline_2\n</thinking>"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)

    parts = _render_region_parts(block)
    assert len(parts) == 1
    plain = _render_to_text(parts[0][0])
    assert "▷" in plain
    assert "<thinking>" in plain


def test_region_parts_form_a_collapsed():
    """Form A collapsed: shows content preview from after open tag."""
    _setup_theme()
    text = "Intro\n<thinking>I need to think\nabout something\n</thinking>\nEnd"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)
    overrides = ViewOverrides()
    overrides.get_region(block.block_id, 1).expanded = False
    parts = _render_region_parts(block, overrides=overrides)

    xml_parts = [(r, idx) for r, idx in parts if idx == 1]
    assert len(xml_parts) == 1
    plain = _render_to_text(xml_parts[0][0])
    assert "▷" in plain
    assert "I need to think" in plain


def test_region_parts_form_c_collapsed():
    """Form C collapsed: single-line XML shows content."""
    _setup_theme()
    text = "Intro\n<note>short note</note>\nEnd"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)
    overrides = ViewOverrides()
    overrides.get_region(block.block_id, 1).expanded = False
    parts = _render_region_parts(block, overrides=overrides)

    xml_parts = [(r, idx) for r, idx in parts if idx == 1]
    assert len(xml_parts) == 1
    plain = _render_to_text(xml_parts[0][0])
    assert "▷" in plain
    assert "short note" in plain


def test_region_parts_multiple_xml_blocks():
    """Multiple XML blocks get their actual segment indices."""
    _setup_theme()
    text = (
        "Before\n"
        "<thinking>\nThought 1\n</thinking>\n"
        "Middle\n"
        "<search_results>\nResult 1\n</search_results>\n"
        "After"
    )
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)
    parts = _render_region_parts(block)

    # All parts have region indices now
    xml_parts = [(r, idx) for r, idx in parts if idx is not None and block.content_regions[idx].kind == "xml_block"]
    assert len(xml_parts) == 2
    # First XML at segment index 1, second at segment index 3
    assert xml_parts[0][1] == 1
    assert xml_parts[1][1] == 3


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
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)
    # Collapse thinking (index 1), leave search expanded (index 3)
    overrides = ViewOverrides()
    overrides.get_region(block.block_id, 1).expanded = False
    # content_regions[3] stays default (None = expanded)
    parts = _render_region_parts(block, overrides=overrides)

    xml_parts = [(r, idx) for r, idx in parts if idx is not None and block.content_regions[idx].kind == "xml_block"]
    assert len(xml_parts) == 2

    # First XML (thinking) should be collapsed (renderable with ▷)
    plain = _render_to_text(xml_parts[0][0])
    assert "▷" in plain

    # Second XML (search_results) should be expanded (renderable with ▽)
    plain2 = _render_to_text(xml_parts[1][0])
    assert "▽" in plain2


# ─── render_turn_to_strips with XML ────────────────────────────────────────


def test_xml_block_renders_with_content_regions():
    """TextContentBlock with XML sets strip_range in ViewOverrides for XML region."""
    _setup_theme()
    text = "Intro\n<thinking>\nLine 1\nLine 2\nLine 3\n</thinking>\nEnd"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)

    console = Console()
    filters = {"assistant": ALWAYS_VISIBLE}
    overrides = ViewOverrides()

    strips, _, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
        overrides=overrides,
    )

    # Block should have content_regions populated (3 segments: MD, XML, MD)
    assert len(block.content_regions) == 3
    # XML region at index 1 should have strip range set in overrides
    xml_region = block.content_regions[1]
    assert xml_region.kind == "xml_block"
    rvs = overrides.get_region(block.block_id, 1)
    assert rvs.strip_range is not None, "XML region should have strip range in overrides"

    # Range should be valid
    start, end = rvs.strip_range
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

    # Expanded (explicit override)
    block_expanded = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block_expanded)
    xml_idx_expanded = next(
        i for i, r in enumerate(block_expanded.content_regions) if r.kind == "xml_block"
    )
    expanded_overrides = ViewOverrides()
    expanded_overrides.get_region(block_expanded.block_id, xml_idx_expanded).expanded = True
    strips_expanded, _, _ = render_turn_to_strips(
        blocks=[block_expanded],
        filters=filters,
        console=console,
        width=80,
        overrides=expanded_overrides,
    )

    # Collapsed — populate regions then collapse XML via ViewOverrides
    block_collapsed = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block_collapsed)
    # Find the XML region and collapse it via overrides
    xml_idx = next(i for i, r in enumerate(block_collapsed.content_regions) if r.kind == "xml_block")
    overrides = ViewOverrides()
    overrides.get_region(block_collapsed.block_id, xml_idx).expanded = False
    strips_collapsed, _, _ = render_turn_to_strips(
        blocks=[block_collapsed],
        filters=filters,
        console=console,
        width=80,
        overrides=overrides,
    )

    # Collapsed should have significantly fewer strips
    assert len(strips_collapsed) < len(strips_expanded), (
        f"Collapsed ({len(strips_collapsed)}) should have fewer strips "
        f"than expanded ({len(strips_expanded)})"
    )


def test_plain_text_gets_md_regions():
    """TextContentBlock without XML gets MD regions from populate_content_regions."""
    block = TextContentBlock(content="Just plain text", category=Category.ASSISTANT)
    populate_content_regions(block)

    # Should have 1 MD region
    assert len(block.content_regions) == 1
    assert block.content_regions[0].kind == "md"


def test_xml_expanded_survives_rerender():
    """ViewOverrides state persists across re-renders (same overrides object)."""
    _setup_theme()
    text = "Intro\n<thinking>\nLine 1\nLine 2\n</thinking>\nEnd"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)
    overrides = ViewOverrides()
    overrides.get_region(block.block_id, 1).expanded = False

    console = Console()
    filters = {"assistant": ALWAYS_VISIBLE}

    # First render
    strips1, _, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
        overrides=overrides,
    )

    # Verify state preserved in overrides
    assert overrides.get_region(block.block_id, 1).expanded is False

    # Second render (same overrides, should produce same result)
    strips2, _, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
        overrides=overrides,
    )

    # Strip counts should be the same
    assert len(strips1) == len(strips2)


def test_text_summary_state_with_regions_renders_without_crashing():
    """Summary renderer for regioned TextContentBlock should always emit strips.

    Regression for UnboundLocalError in _render_block_tree when:
    - has_regions=True
    - state_override=True (TextContentBlock SUMMARY renderer)
    """
    _setup_theme()
    text = "Intro\n<thinking>\nLine 1\nLine 2\n</thinking>\nTail"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)
    assert len(block.content_regions) >= 2

    console = Console()
    # SUMMARY collapsed selects BLOCK_STATE_RENDERERS for TextContentBlock.
    filters = {"assistant": VisState(visible=True, full=False, expanded=False)}

    strips, _, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
    )

    assert len(strips) > 0


# ─── Gutter width with XML ────────────────────────────────────────────────


def test_xml_strips_have_gutter():
    """XML sub-block strips should have the standard gutter."""
    _setup_theme()
    text = "Intro\n<thinking>\nThought\n</thinking>\nEnd"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)

    console = Console()
    filters = {"assistant": ALWAYS_VISIBLE}

    strips, _, _ = render_turn_to_strips(
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
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)

    console = Console()
    filters = {"assistant": ALWAYS_VISIBLE}

    strips, _, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
    )

    # Should have content_regions with XML detected
    xml_regions = [r for r in block.content_regions if r.kind == "xml_block"]
    assert len(xml_regions) == 1


def test_form_c_renders_as_xml_block():
    """Form C single-line renders with syntax-highlighted tags."""
    _setup_theme()
    text = "<note>short note</note>"
    block = TextContentBlock(content=text, category=Category.ASSISTANT)
    populate_content_regions(block)

    console = Console()
    filters = {"assistant": ALWAYS_VISIBLE}

    strips, _, _ = render_turn_to_strips(
        blocks=[block],
        filters=filters,
        console=console,
        width=80,
    )

    # Should have content_regions with XML detected
    xml_regions = [r for r in block.content_regions if r.kind == "xml_block"]
    assert len(xml_regions) == 1


# ─── Collapsibility guard ─────────────────────────────────────────────────


def test_collapsibility_guard_xml_is_collapsible():
    """xml_block kind is in COLLAPSIBLE_REGION_KINDS."""
    assert "xml_block" in COLLAPSIBLE_REGION_KINDS


def test_collapsibility_guard_tool_def_is_collapsible():
    """tool_def kind is in COLLAPSIBLE_REGION_KINDS."""
    assert "tool_def" in COLLAPSIBLE_REGION_KINDS


def test_collapsibility_guard_md_not_collapsible():
    """md kind is NOT in COLLAPSIBLE_REGION_KINDS."""
    assert "md" not in COLLAPSIBLE_REGION_KINDS


def test_collapsibility_guard_code_fence_is_collapsible():
    """code_fence kind is in COLLAPSIBLE_REGION_KINDS."""
    assert "code_fence" in COLLAPSIBLE_REGION_KINDS


def test_collapsibility_guard_md_fence_is_collapsible():
    """md_fence kind is in COLLAPSIBLE_REGION_KINDS."""
    assert "md_fence" in COLLAPSIBLE_REGION_KINDS
