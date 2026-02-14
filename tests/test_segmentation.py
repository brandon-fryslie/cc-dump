"""Tests for cc_dump.segmentation — SubBlock segmentation pipeline."""

import pytest

from cc_dump.segmentation import (
    FenceMeta,
    ParseErrorKind,
    SegmentResult,
    Span,
    SubBlock,
    SubBlockKind,
    XmlBlockMeta,
    segment,
    wrap_tags_in_backticks,
    wrap_tags_outside_fences,
)


def kinds(result: SegmentResult) -> list[str]:
    """Extract SubBlock kind values as a list of strings."""
    return [sb.kind.value for sb in result.sub_blocks]


def error_kinds(result: SegmentResult) -> list[str]:
    """Extract ParseError kind values as a list of strings."""
    return [e.kind.value for e in result.errors]


def text_of(raw: str, sb: SubBlock) -> str:
    """Extract the text for a SubBlock from raw text."""
    return raw[sb.span.start : sb.span.end]


def inner_text(raw: str, sb: SubBlock) -> str:
    """Extract inner content text from a SubBlock with meta."""
    assert sb.meta is not None
    return raw[sb.meta.inner_span.start : sb.meta.inner_span.end]


# ─── Test 1: Plain markdown with inline tags ─────────────────────────────────


class TestPlainMarkdown:
    def test_inline_tags_produce_single_md(self):
        text = "Hello <world> and <foo bar> stuff"
        result = segment(text)
        assert kinds(result) == ["md"]
        assert result.errors == ()

    def test_no_structure(self):
        text = "Just some **bold** and _italic_ text."
        result = segment(text)
        assert kinds(result) == ["md"]
        assert text_of(text, result.sub_blocks[0]) == text


# ─── Test 2: md_fence (empty-info fence) ─────────────────────────────────────


class TestMdFence:
    def test_empty_info_fence_is_md_fence(self):
        text = "before\n```\nsome *markdown* content\n```\nafter"
        result = segment(text)
        assert kinds(result) == ["md", "md_fence", "md"]
        assert result.errors == ()

        fence = result.sub_blocks[1]
        assert fence.kind == SubBlockKind.MD_FENCE
        assert fence.meta.info is None
        assert fence.meta.marker_char == "`"
        assert fence.meta.marker_len == 3
        assert inner_text(text, fence) == "some *markdown* content\n"


# ─── Test 3: code_fence with language ────────────────────────────────────────


class TestCodeFence:
    def test_language_fence_is_code_fence(self):
        text = "```python\nprint('hello')\n```"
        result = segment(text)
        assert kinds(result) == ["code_fence"]
        assert result.errors == ()

        fence = result.sub_blocks[0]
        assert fence.kind == SubBlockKind.CODE_FENCE
        assert fence.meta.info == "python"
        assert inner_text(text, fence) == "print('hello')\n"

    def test_tilde_fence(self):
        text = "~~~js\nconsole.log('hi')\n~~~"
        result = segment(text)
        assert kinds(result) == ["code_fence"]
        fence = result.sub_blocks[0]
        assert fence.meta.marker_char == "~"
        assert fence.meta.info == "js"


# ─── Test 4: xml_block ──────────────────────────────────────────────────────


class TestXmlBlock:
    def test_thinking_block(self):
        text = "<thinking>\nI need to consider this.\n</thinking>"
        result = segment(text)
        assert kinds(result) == ["xml_block"]
        assert result.errors == ()

        xb = result.sub_blocks[0]
        assert xb.meta.tag_name == "thinking"
        assert inner_text(text, xb) == "\nI need to consider this.\n"

    def test_system_reminder(self):
        text = "<system-reminder>\nSome reminder text.\n</system-reminder>"
        result = segment(text)
        assert kinds(result) == ["xml_block"]
        assert result.sub_blocks[0].meta.tag_name == "system-reminder"


# ─── Test 5: Unclosed fence ─────────────────────────────────────────────────


class TestUnclosedFence:
    def test_unclosed_fence_consumes_to_end(self):
        text = "```python\nsome code without closing"
        result = segment(text)
        assert kinds(result) == ["code_fence"]
        assert error_kinds(result) == ["unclosed_fence"]
        # Entire text is consumed
        assert result.sub_blocks[0].span == Span(0, len(text))


# ─── Test 6: Unclosed XML ───────────────────────────────────────────────────


class TestUnclosedXml:
    def test_unclosed_xml_becomes_md(self):
        text = "<unclosed>\nsome content without closing tag"
        result = segment(text)
        # Unclosed XML: open tag skipped, rest becomes md
        assert kinds(result) == ["md"]
        assert error_kinds(result) == ["unclosed_xml"]


# ─── Test 7: Fence containing XML-like text (opaque) ────────────────────────


class TestFenceContainingXml:
    def test_xml_inside_fence_is_opaque(self):
        text = "```\n<thinking>\nthis is just content\n</thinking>\n```"
        result = segment(text)
        assert kinds(result) == ["md_fence"]
        assert result.errors == ()
        # The XML tags inside are just content, not parsed
        assert inner_text(text, result.sub_blocks[0]).startswith("<thinking>")


# ─── Test 8: XML block containing code fences (key test!) ───────────────────


class TestXmlContainingFences:
    def test_fences_inside_xml_are_content(self):
        text = (
            "<system-reminder>\n"
            "Run with:\n"
            "```bash\n"
            "just run\n"
            "```\n"
            "End of reminder.\n"
            "</system-reminder>\n"
        )
        result = segment(text)
        assert kinds(result) == ["xml_block"]
        assert result.errors == ()

        xb = result.sub_blocks[0]
        assert xb.meta.tag_name == "system-reminder"
        # The fence inside is absorbed as content
        inner = inner_text(text, xb)
        assert "```bash" in inner
        assert "just run" in inner


# ─── Test 9: Adjacent mixed content ─────────────────────────────────────────


class TestAdjacentMixed:
    def test_md_fence_xml_md(self):
        text = (
            "Some intro text.\n"
            "```python\ncode()\n```\n"
            "<thinking>\nthought\n</thinking>\n"
            "Outro text."
        )
        result = segment(text)
        assert kinds(result) == ["md", "code_fence", "xml_block", "md"]
        assert result.errors == ()


# ─── Test 10: Mismatched fence closers ───────────────────────────────────────


class TestMismatchedFenceClosers:
    def test_tilde_ignored_for_backtick_fence(self):
        text = "```\nsome content\n~~~\nmore content\n```"
        result = segment(text)
        assert kinds(result) == ["md_fence"]
        assert result.errors == ()
        # ~~~ is NOT a valid closer for ```, so content includes it
        inner = inner_text(text, result.sub_blocks[0])
        assert "~~~" in inner


# ─── Test 11: Interleaved types ──────────────────────────────────────────────


class TestInterleaved:
    def test_md_mdfence_xml_codefence(self):
        text = (
            "Intro.\n"
            "```\nmarkdown fence\n```\n"
            "<note>\nnote content\n</note>\n"
            "```rust\nfn main() {}\n```\n"
        )
        result = segment(text)
        assert kinds(result) == ["md", "md_fence", "xml_block", "code_fence"]
        assert result.errors == ()


# ─── Test 12: Self-closing tags (excluded) ───────────────────────────────────


class TestSelfClosingTags:
    def test_self_closing_not_xml_block(self):
        text = "Some text with\n<br/>\nand more text"
        result = segment(text)
        # <br/> is self-closing, not treated as xml_block opener
        assert kinds(result) == ["md"]
        assert result.errors == ()


# ─── Test 13: Empty input ───────────────────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        result = segment("")
        assert result.sub_blocks == ()
        assert result.errors == ()


# ─── Test 14: Fence before XML (document order) ─────────────────────────────


class TestFenceBeforeXml:
    def test_fence_first_when_earlier(self):
        text = (
            "```python\ncode\n```\n"
            "<thinking>\nthought\n</thinking>\n"
        )
        result = segment(text)
        assert kinds(result) == ["code_fence", "xml_block"]
        assert result.errors == ()


# ─── Edge cases ──────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_4plus_backtick_fence(self):
        text = "````\ncontent\n````"
        result = segment(text)
        assert kinds(result) == ["md_fence"]
        assert result.sub_blocks[0].meta.marker_len == 4

    def test_4_backtick_needs_4_to_close(self):
        # 3 backticks can't close a 4-backtick fence
        text = "````\ncontent\n```\nmore\n````"
        result = segment(text)
        assert kinds(result) == ["md_fence"]
        inner = inner_text(text, result.sub_blocks[0])
        assert "```" in inner  # 3-backtick line is content, not closer

    def test_nested_same_name_xml_first_close_wins(self):
        text = "<div>\n<div>\nx\n</div>\n</div>\n"
        result = segment(text)
        # First </div> closes the outer <div>
        assert kinds(result) == ["xml_block", "md"]
        xb = result.sub_blocks[0]
        assert xb.meta.tag_name == "div"
        # Inner ends at first </div>
        inner = inner_text(text, xb)
        assert "<div>" in inner

    def test_multiple_thinking_blocks(self):
        text = (
            "<thinking>\nfirst thought\n</thinking>\n"
            "middle\n"
            "<thinking>\nsecond thought\n</thinking>\n"
        )
        result = segment(text)
        assert kinds(result) == ["xml_block", "md", "xml_block"]

    def test_coverage_invariant_no_overlaps(self):
        """SubBlocks are non-overlapping and cover [0, len)."""
        text = (
            "Hello\n"
            "```python\ncode\n```\n"
            "<thinking>\nthought\n</thinking>\n"
            "bye\n"
        )
        result = segment(text)
        # Check non-overlapping
        for i in range(len(result.sub_blocks) - 1):
            assert result.sub_blocks[i].span.end <= result.sub_blocks[i + 1].span.start
        # Check full coverage
        if result.sub_blocks:
            assert result.sub_blocks[0].span.start == 0
            assert result.sub_blocks[-1].span.end == len(text)


# ─── Tag wrapping tests ─────────────────────────────────────────────────────


class TestWrapTagsInBackticks:
    def test_simple_tag(self):
        assert wrap_tags_in_backticks("Hello <world>") == "Hello `<world>`"

    def test_closing_tag(self):
        assert wrap_tags_in_backticks("</thinking>") == "`</thinking>`"

    def test_tag_with_attributes(self):
        result = wrap_tags_in_backticks('<div class="foo">')
        assert result == '`<div class="foo">`'

    def test_already_backticked_not_doubled(self):
        text = "Already `<tagged>` here"
        assert wrap_tags_in_backticks(text) == text

    def test_no_tags(self):
        text = "No tags here"
        assert wrap_tags_in_backticks(text) == text

    def test_multiple_tags(self):
        text = "A <foo> and <bar> end"
        assert wrap_tags_in_backticks(text) == "A `<foo>` and `<bar>` end"


class TestWrapTagsOutsideFences:
    def test_tags_outside_fence_wrapped(self):
        text = "Before <tag>\n```\n<inside>\n```\nAfter <other>"
        result = wrap_tags_outside_fences(text)
        assert "`<tag>`" in result
        assert "`<other>`" in result
        # Inside fence should NOT be wrapped
        assert "<inside>" in result
        assert "`<inside>`" not in result

    def test_no_fences_wraps_all(self):
        text = "Hello <world> and <foo>"
        assert wrap_tags_outside_fences(text) == "Hello `<world>` and `<foo>`"

    def test_only_fence_region(self):
        text = "```\n<tag>\n```"
        result = wrap_tags_outside_fences(text)
        assert "`<tag>`" not in result
