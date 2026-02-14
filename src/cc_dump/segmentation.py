"""Segment raw text content into typed SubBlocks for rendering.

Parses USER/ASSISTANT message text into structural regions:
- MD: plain markdown (default gap-fill)
- MD_FENCE: fenced block with no info string (render as markdown, not code)
- CODE_FENCE: fenced block with language info (render with syntax highlighting)
- XML_BLOCK: <tag>...</tag> block (render with visible tags)

Single linear scan with document-order precedence: at each position,
whichever structure (XML open or fence open) starts earliest wins.
Its span is opaque — content inside is not re-scanned for structure.

// [LAW:dataflow-not-control-flow] segment() is a pure function: text in, SubBlocks out.
// [LAW:one-source-of-truth] All text segmentation logic lives here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


# ─── Data model ──────────────────────────────────────────────────────────────


class SubBlockKind(Enum):
    MD = "md"
    MD_FENCE = "md_fence"
    CODE_FENCE = "code_fence"
    XML_BLOCK = "xml_block"


class ParseErrorKind(Enum):
    UNCLOSED_FENCE = "unclosed_fence"
    UNCLOSED_XML = "unclosed_xml"


@dataclass(frozen=True)
class Span:
    start: int
    end: int  # exclusive


@dataclass(frozen=True)
class FenceMeta:
    marker_char: str  # "`" or "~"
    marker_len: int  # 3 or more
    info: str | None  # None for md_fence, first token for code_fence
    inner_span: Span  # content between opening and closing fence lines


@dataclass(frozen=True)
class XmlBlockMeta:
    tag_name: str
    start_tag_span: Span
    end_tag_span: Span
    inner_span: Span


@dataclass(frozen=True)
class SubBlock:
    kind: SubBlockKind
    span: Span
    meta: FenceMeta | XmlBlockMeta | None = None


@dataclass(frozen=True)
class ParseError:
    kind: ParseErrorKind
    span: Span
    details: str


@dataclass(frozen=True)
class SegmentResult:
    sub_blocks: tuple[SubBlock, ...]
    errors: tuple[ParseError, ...]


# ─── Regex patterns ──────────────────────────────────────────────────────────

# Fence open: optional indent, 3+ backticks or tildes, optional info string
FENCE_OPEN_RE = re.compile(r"^([ \t]*)((`{3,})|(~{3,}))(.*)", re.MULTILINE)

# XML open tag at line start (may have content after > on same line)
XML_OPEN_RE = re.compile(
    r"^[ \t]*<([A-Za-z_][\w:.\-]*)(\s[^>]*)?>", re.MULTILINE
)

# Match tags NOT already inside backticks — for wrapping in backticks
TAG_RE = re.compile(r"(?<!`)<(/?[A-Za-z_][\w:.\-]*(?:\s[^>]*)?)>(?!`)")


# ─── Segmentation algorithm ─────────────────────────────────────────────────


def segment(raw_text: str) -> SegmentResult:
    """Segment raw text into typed SubBlocks.

    Single linear scan, document-order precedence. Each structure's span
    is opaque — content inside is not re-scanned.
    """
    if not raw_text:
        return SegmentResult((), ())

    errors: list[ParseError] = []
    claimed: list[SubBlock] = []
    pos = 0

    while pos < len(raw_text):
        xml_m = XML_OPEN_RE.search(raw_text, pos)
        fence_m = FENCE_OPEN_RE.search(raw_text, pos)

        if not xml_m and not fence_m:
            break

        # Pick whichever starts first (document order). Same position: prefer XML.
        candidates: list[tuple[str, int, re.Match]] = []
        if xml_m:
            candidates.append(("xml", xml_m.start(), xml_m))
        if fence_m:
            candidates.append(("fence", fence_m.start(), fence_m))
        candidates.sort(key=lambda c: (c[1], 0 if c[0] == "xml" else 1))

        kind, _, m = candidates[0]

        if kind == "xml":
            result = _try_xml_block(raw_text, m, errors)
            if result:
                claimed.append(result)
                pos = result.span.end
            else:
                pos = _end_of_line(raw_text, m.start())
        else:
            result = _process_fence(raw_text, m, errors)
            claimed.append(result)
            pos = result.span.end

    claimed.sort(key=lambda sb: sb.span.start)
    md_blocks = _fill_md_gaps(claimed, len(raw_text))
    all_blocks = sorted(claimed + md_blocks, key=lambda sb: sb.span.start)
    return SegmentResult(tuple(all_blocks), tuple(errors))


def _end_of_line(text: str, pos: int) -> int:
    """Return position just past the next newline from pos, or len(text)."""
    nl = text.find("\n", pos)
    return (nl + 1) if nl != -1 else len(text)


def _process_fence(
    text: str, m: re.Match, errors: list[ParseError]
) -> SubBlock:
    """Process a fence opening match into a SubBlock."""
    marker_str = m.group(3) or m.group(4)
    marker_char = marker_str[0]
    marker_len = len(marker_str)
    info_raw = m.group(5).strip()
    fence_start = m.start()

    opening_end = text.find("\n", m.start())
    content_start = (opening_end + 1) if opening_end != -1 else len(text)

    kind = SubBlockKind.CODE_FENCE if info_raw else SubBlockKind.MD_FENCE
    info = info_raw.split()[0] if info_raw else None

    # Close: same char, length >= opening, on its own line
    close_pat = (
        r"^[ \t]*"
        + re.escape(marker_char)
        + "{"
        + str(marker_len)
        + r",}[ \t]*$"
    )
    close_re = re.compile(close_pat, re.MULTILINE)
    cm = close_re.search(text, content_start)

    if cm:
        close_end = text.find("\n", cm.start())
        fence_end = (close_end + 1) if close_end != -1 else len(text)
        inner = Span(content_start, cm.start())
    else:
        fence_end = len(text)
        inner = Span(content_start, fence_end)
        errors.append(
            ParseError(
                ParseErrorKind.UNCLOSED_FENCE,
                Span(fence_start, fence_end),
                f"Unclosed {marker_char * marker_len} fence",
            )
        )

    return SubBlock(
        kind,
        Span(fence_start, fence_end),
        FenceMeta(marker_char, marker_len, info, inner),
    )


def _try_xml_block(
    text: str, m: re.Match, errors: list[ParseError]
) -> SubBlock | None:
    """Try to parse an XML block from an opening tag match. Returns None on failure.

    Handles three forms:
      Form A: <tag>content after open tag\\n...\\n</tag>
      Form B: <tag>\\ncontent\\n</tag>  (tags on own lines)
      Form C: <tag>content</tag>  (single line)
    """
    stripped = text[m.start() : m.end()].lstrip()

    # Exclude comments, processing instructions, CDATA, closing tags, self-closing
    if (
        stripped.startswith("<!--")
        or stripped.startswith("<?")
        or stripped.startswith("<!")
        or stripped.startswith("</")
        or stripped.rstrip().endswith("/>")
    ):
        return None

    tag_name = m.group(1)
    tag_end = m.end()  # position right after '>'
    close_str = "</" + tag_name + ">"

    # Pass 1: Same-line close tag (Form C: <tag>content</tag>)
    line_end = text.find("\n", m.start())
    if line_end == -1:
        line_end = len(text)
    same_line_rest = text[tag_end:line_end]
    close_pos = same_line_rest.find(close_str)
    if close_pos != -1:
        abs_close_start = tag_end + close_pos
        abs_close_end = abs_close_start + len(close_str)
        block_end = _end_of_line(text, abs_close_start)
        return SubBlock(
            SubBlockKind.XML_BLOCK,
            Span(m.start(), block_end),
            XmlBlockMeta(
                tag_name=tag_name,
                start_tag_span=Span(m.start(), tag_end),
                end_tag_span=Span(abs_close_start, abs_close_end),
                inner_span=Span(tag_end, abs_close_start),
            ),
        )

    # Pass 2: Multi-line close tag (Forms A & B)
    # Try strict first: </tag> on its own line
    end_re_strict = re.compile(
        r"^[ \t]*</" + re.escape(tag_name) + r">[ \t]*$", re.MULTILINE
    )
    em = end_re_strict.search(text, tag_end)
    if not em:
        # Fallback: </tag> anywhere after the open tag
        end_re_loose = re.compile(r"</" + re.escape(tag_name) + r">")
        em = end_re_loose.search(text, tag_end)

    if em:
        close_end = em.start() + len(close_str)
        block_end = _end_of_line(text, em.start())
        return SubBlock(
            SubBlockKind.XML_BLOCK,
            Span(m.start(), block_end),
            XmlBlockMeta(
                tag_name=tag_name,
                start_tag_span=Span(m.start(), tag_end),
                end_tag_span=Span(em.start(), close_end),
                inner_span=Span(tag_end, em.start()),
            ),
        )

    stl_end = _end_of_line(text, m.start())
    errors.append(
        ParseError(
            ParseErrorKind.UNCLOSED_XML,
            Span(m.start(), stl_end),
            f"Unclosed <{tag_name}> tag",
        )
    )
    return None


def _fill_md_gaps(
    claimed_sorted: list[SubBlock], text_length: int
) -> list[SubBlock]:
    """Fill gaps between claimed spans with MD SubBlocks."""
    md_blocks: list[SubBlock] = []
    pos = 0
    for sb in claimed_sorted:
        if sb.span.start > pos:
            md_blocks.append(SubBlock(SubBlockKind.MD, Span(pos, sb.span.start)))
        pos = sb.span.end
    if pos < text_length:
        md_blocks.append(SubBlock(SubBlockKind.MD, Span(pos, text_length)))
    return md_blocks


# ─── Tag visibility rewrite ─────────────────────────────────────────────────


def wrap_tags_in_backticks(text: str) -> str:
    """Wrap bare XML/HTML tags in backticks so they render visibly in Markdown."""
    return TAG_RE.sub(r"`<\1>`", text)


def wrap_tags_outside_fences(text: str) -> str:
    """Wrap tags in backticks, but skip content inside fenced code regions.

    Used for xml_block inner content which may contain code fences.
    Rich's Markdown handles fences natively, so we only wrap tags in
    the non-fence regions.
    """
    # Find fenced regions within this text
    fence_regions: list[tuple[int, int]] = []
    for m in re.finditer(
        r"^[ \t]*(```|~~~).*?\n.*?^[ \t]*\1[ \t]*$",
        text,
        re.MULTILINE | re.DOTALL,
    ):
        fence_regions.append((m.start(), m.end()))

    if not fence_regions:
        return wrap_tags_in_backticks(text)

    parts: list[str] = []
    pos = 0
    for fs, fe in fence_regions:
        parts.append(wrap_tags_in_backticks(text[pos:fs]))
        parts.append(text[fs:fe])
        pos = fe
    parts.append(wrap_tags_in_backticks(text[pos:]))
    return "".join(parts)
