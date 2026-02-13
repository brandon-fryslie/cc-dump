"""Rich rendering for FormattedBlock structures in the TUI.

Converts structured IR from formatting.py into Rich Text objects for display.

Two-tier dispatch:
1. BLOCK_STATE_RENDERERS[(type_name, Level, expanded)] — custom per-state output
2. BLOCK_RENDERERS[type_name] — full content, then generic truncation via TRUNCATION_LIMITS

# [LAW:single-enforcer] All visibility logic is enforced in render_turn_to_strips().
# Individual renderers never check filters or collapsed state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from rich.text import Text
from rich.markdown import Markdown
from rich.console import ConsoleRenderable, Group
from rich.syntax import Syntax
from rich.theme import Theme as RichTheme

from collections import Counter

# Click-target meta keys — the sole identifiers for interactive segments.
# // [LAW:one-source-of-truth] Canonical constants; widget_factory reads these via module import.
META_TOGGLE_BLOCK = "toggle_block"
META_TOGGLE_REGION = "toggle_region"

from cc_dump.formatting import (
    ContentRegion,
    FormattedBlock,
    SeparatorBlock,
    HeaderBlock,
    HttpHeadersBlock,
    MetadataBlock,
    NewSessionBlock,
    SystemLabelBlock,
    TrackedContentBlock,
    RoleBlock,
    TextContentBlock,
    ToolDefinitionsBlock,
    ToolUseBlock,
    ToolResultBlock,
    ToolUseSummaryBlock,
    ImageBlock,
    UnknownTypeBlock,
    StreamInfoBlock,
    StreamToolUseBlock,
    TextDeltaBlock,
    StopReasonBlock,
    ErrorBlock,
    ProxyErrorBlock,
    NewlineBlock,
    TurnBudgetBlock,
    make_diff_lines,
    Category,
    VisState,
    HIDDEN,
    ALWAYS_VISIBLE,
)

import cc_dump.palette


# ─── Theme Colors ────────────────────────────────────────────────────────────
# [LAW:one-source-of-truth] All theme-derived colors live in ThemeColors.
# set_theme() is the sole entry point for rebuilding.


@dataclass(frozen=True)
class ThemeColors:
    """All colors the rendering pipeline needs, derived from a Textual Theme."""

    # Semantic colors from theme
    primary: str
    secondary: str
    accent: str
    warning: str
    error: str
    success: str
    surface: str
    foreground: str
    background: str
    dark: bool

    # Role colors (derived from theme)
    user: str  # theme.primary
    assistant: str  # theme.secondary
    system: str  # theme.accent

    # Functional aliases
    info: str  # theme.primary

    # Code rendering
    code_theme: str  # "github-dark" or "friendly"

    # Search
    search_all_bg: str  # surface
    search_current_style: str  # accent-based

    # Footer
    follow_active_style: str

    # Search bar styles
    search_prompt_style: str
    search_active_style: str
    search_error_style: str
    search_keys_style: str

    # Markdown theme dict (for Rich console.push_theme)
    markdown_theme_dict: dict


def build_theme_colors(textual_theme) -> ThemeColors:
    """Map a Textual Theme to ThemeColors.

    Handles None fields on Theme objects with sensible derivations.
    """
    dark = textual_theme.dark

    primary = textual_theme.primary or "#0178D4"
    secondary = textual_theme.secondary or primary
    accent = textual_theme.accent or primary
    warning = textual_theme.warning or "#ffa62b"
    error = textual_theme.error or "#ba3c5b"
    success = textual_theme.success or "#4EBF71"
    foreground = textual_theme.foreground or ("#e0e0e0" if dark else "#1e1e1e")
    background = textual_theme.background or ("#1e1e1e" if dark else "#e0e0e0")
    surface = textual_theme.surface or ("#2b2b2b" if dark else "#d0d0d0")

    code_theme = "github-dark" if dark else "friendly"

    # Search highlight: current match uses accent with inverted fg
    search_current_fg = "#000000" if dark else "#ffffff"
    search_current_style = f"bold {search_current_fg} on {accent}"

    # Markdown theme: adapt to dark/light mode
    # [LAW:one-source-of-truth] markdown styling defined here
    if dark:
        md_code_style = f"{foreground} on {surface}"
        md_h_dim = "dim italic"
    else:
        md_code_style = f"{foreground} on {surface}"
        md_h_dim = "dim italic"

    markdown_theme_dict = {
        "markdown.code": md_code_style,
        "markdown.code_block": f"on {surface}",
        "markdown.h1": f"bold underline {primary}",
        "markdown.h2": f"bold {primary}",
        "markdown.h3": f"bold {secondary}",
        "markdown.h4": f"italic {secondary}",
        "markdown.h5": f"italic {foreground}",
        "markdown.h6": md_h_dim,
        "markdown.link": f"underline {primary}",
        "markdown.link_url": f"dim underline {primary}",
        "markdown.block_quote": f"italic {foreground}",
        "markdown.table.border": "dim",
        "markdown.table.header": f"bold {primary}",
        "markdown.hr": "dim",
    }

    return ThemeColors(
        primary=primary,
        secondary=secondary,
        accent=accent,
        warning=warning,
        error=error,
        success=success,
        surface=surface,
        foreground=foreground,
        background=background,
        dark=dark,
        user=primary,
        assistant=secondary,
        system=accent,
        info=primary,
        code_theme=code_theme,
        search_all_bg=surface,
        search_current_style=search_current_style,
        follow_active_style=f"bold reverse {success}",
        search_prompt_style=f"bold {primary}",
        search_active_style=f"bold {success}",
        search_error_style=f"bold {error}",
        search_keys_style=f"bold {warning}",
        markdown_theme_dict=markdown_theme_dict,
    )


# Module-level theme state — starts as None, set by set_theme().
_theme_colors: ThemeColors | None = None


def get_theme_colors() -> ThemeColors:
    """Get the current ThemeColors. Raises RuntimeError if set_theme() not called."""
    if _theme_colors is None:
        raise RuntimeError("Theme not initialized. Call set_theme() before rendering.")
    return _theme_colors


def set_theme(textual_theme) -> None:
    """Rebuild all theme-derived module state from a Textual Theme.

    Called by app on_mount, watch_theme, and after hot-reload.
    // [LAW:single-enforcer] Sole entry point for theme changes.
    """
    global _theme_colors, ROLE_STYLES, TAG_STYLES, MSG_COLORS

    _theme_colors = build_theme_colors(textual_theme)
    tc = _theme_colors

    # Rebuild module-level style vars
    ROLE_STYLES = {
        "user": f"bold {tc.user}",
        "assistant": f"bold {tc.assistant}",
        "system": f"bold {tc.system}",
    }

    p = cc_dump.palette.PALETTE
    TAG_STYLES = [p.fg_on_bg_for_mode(i, tc.dark) for i in range(min(p.count, 12))]
    MSG_COLORS = [p.msg_color_for_mode(i, tc.dark) for i in range(6)]


# ─── Visibility model constants ───────────────────────────────────────────────

# [LAW:one-source-of-truth] [LAW:dataflow-not-control-flow]
# VisState is THE representation. Single lookup per question.
TRUNCATION_LIMITS: dict[VisState, int | None] = {
    # Hidden states (visible=False) — all produce 0 lines
    VisState(False, False, False): 0,
    VisState(False, False, True): 0,
    VisState(False, True, False): 0,
    VisState(False, True, True): 0,
    # Summary level (visible=True, full=False)
    VisState(True, False, False): 4,  # summary collapsed
    VisState(True, False, True): None,  # summary expanded
    # Full level (visible=True, full=True)
    VisState(True, True, False): 4,  # full collapsed
    VisState(True, True, True): None,  # full expanded (unlimited)
}

# Categories that should render as Markdown instead of plain text
_MARKDOWN_CATEGORIES = {Category.USER, Category.ASSISTANT, Category.SYSTEM}


# ─── Category resolution ──────────────────────────────────────────────────────

# Static mapping: block type name → category (or None for context-dependent/always-visible).
# [LAW:one-source-of-truth] Replaces BLOCK_FILTER_KEY.
BLOCK_CATEGORY: dict[str, Category | None] = {
    "SeparatorBlock": Category.HEADERS,
    "HeaderBlock": Category.HEADERS,
    "HttpHeadersBlock": Category.HEADERS,
    "MetadataBlock": Category.METADATA,
    "NewSessionBlock": Category.METADATA,
    "TurnBudgetBlock": Category.BUDGET,
    "SystemLabelBlock": Category.SYSTEM,
    "TrackedContentBlock": Category.SYSTEM,
    "ToolDefinitionsBlock": Category.TOOLS,
    "ToolUseBlock": Category.TOOLS,
    "ToolResultBlock": Category.TOOLS,
    "ToolUseSummaryBlock": Category.TOOLS,
    "StreamInfoBlock": Category.METADATA,
    "StreamToolUseBlock": Category.TOOLS,
    "StopReasonBlock": Category.METADATA,
    # Context-dependent (use block.category field):
    "RoleBlock": None,
    "TextContentBlock": None,
    "TextDeltaBlock": None,
    "ImageBlock": None,
    # Always visible (no category — always FULL+expanded):
    "ErrorBlock": None,
    "ProxyErrorBlock": None,
    "NewlineBlock": None,
    "UnknownTypeBlock": None,
}


def get_category(block: FormattedBlock) -> Category | None:
    """Resolve the category for a block.

    Returns block.category if set, else falls back to BLOCK_CATEGORY static mapping.
    None means always visible (no category control).
    """
    if block.category is not None:
        return block.category
    return BLOCK_CATEGORY.get(type(block).__name__)


def _resolve_visibility(block: FormattedBlock, filters: dict) -> VisState:
    """Determine VisState for a block given current filter state.

    // [LAW:one-source-of-truth] Returns THE visibility representation.
    // [LAW:dataflow-not-control-flow] Value coalescing, not branching.

    Filters contain VisState values keyed by category name.
    Runtime `_force_vis` attribute overrides all filters (search mode).
    Per-block `block.expanded` overrides category-level expansion.
    Returns ALWAYS_VISIBLE for blocks with no category.
    """
    # Check for runtime override (search mode)
    force_vis = getattr(block, "_force_vis", None)
    if force_vis is not None:
        return force_vis

    cat = get_category(block)
    if cat is None:
        return ALWAYS_VISIBLE  # always fully visible

    vis = filters.get(cat.value, ALWAYS_VISIBLE)
    # Per-block override: None → use category default, else use block value
    expanded = block.expanded if block.expanded is not None else vis.expanded

    return VisState(vis.visible, vis.full, expanded)


# ─── Style helpers ─────────────────────────────────────────────────────────────

# Initial values — rebuilt by set_theme()
ROLE_STYLES: dict[str, str] = {}
TAG_STYLES: list[tuple[str, str]] = []
# Default MSG_COLORS to avoid division by zero in tests that don't call set_theme()
MSG_COLORS: list[str] = ["cyan", "magenta", "yellow", "blue", "green", "red"]


def _build_filter_indicators() -> dict[str, tuple[str, str]]:
    """Filter indicators use the fixed indicator palette (excluded from theme).

    // [LAW:one-source-of-truth] Filter indicator colors are intentionally
    // independent of the Textual theme per user request.
    """
    p = cc_dump.palette.PALETTE
    return {
        "headers": ("\u258c", p.filter_color("headers")),
        "tools": ("\u258c", p.filter_color("tools")),
        "system": ("\u258c", p.filter_color("system")),
        "budget": ("\u258c", p.filter_color("budget")),
        "metadata": ("\u258c", p.filter_color("metadata")),
        "user": ("\u258c", p.filter_color("user")),
        "assistant": ("\u258c", p.filter_color("assistant")),
    }


FILTER_INDICATORS = _build_filter_indicators()


def _add_filter_indicator(
    text: ConsoleRenderable, filter_name: str
) -> ConsoleRenderable:
    """Add a colored indicator to show which filter controls this content.

    Only works for Text objects. Non-Text renderables (like Markdown) are returned unchanged.
    For strip-based rendering, use _add_gutter_to_strips() instead.
    """
    # Guard: only Text objects can be modified this way
    if not isinstance(text, Text):
        return text

    if filter_name not in FILTER_INDICATORS:
        return text

    symbol, color = FILTER_INDICATORS[filter_name]
    indicator = Text()
    indicator.append(symbol, style=f"bold {color}")
    indicator.append(text)
    return indicator


def _category_indicator_name(block: FormattedBlock) -> str | None:
    """Get the filter indicator name for a block's category."""
    cat = get_category(block)
    if cat is None:
        return None
    return cat.value


def _render_xml_tag(tag_text: str) -> Syntax:
    """Render an XML open/close tag with syntax highlighting.

    Uses the html lexer for proper token-level colorization:
    angle brackets, tag names, attributes each get distinct colors.

    // [LAW:one-source-of-truth] Single function for all XML tag rendering.
    // [LAW:one-type-per-behavior] All XML tags render identically — one function.
    """
    tc = get_theme_colors()
    return Syntax(tag_text, "html", theme=tc.code_theme, background_color="default")


# ─── Full-content renderers (BLOCK_RENDERERS) ─────────────────────────────────
# [LAW:single-enforcer] These render FULL content only. No filter checks.
# Signature: (block) -> Text | None


def _render_separator(block: SeparatorBlock) -> Text | None:
    char = "\u2500" if block.style == "heavy" else "\u2504"
    return Text(char * 70, style="dim")


def _render_header(block: HeaderBlock) -> Text | None:
    tc = get_theme_colors()
    # [LAW:dataflow-not-control-flow] Header type dispatch via dict
    specs = {
        "request": (lambda b: b.label, f"bold {tc.info}"),
        "response": (lambda b: "RESPONSE", f"bold {tc.success}"),
    }
    label_fn, style = specs.get(block.header_type, (lambda b: "UNKNOWN", "bold"))
    t = Text()
    t.append(" {} ".format(label_fn(block)), style=style)
    t.append(" ({})".format(block.timestamp), style="dim")
    return t


def _render_http_headers(block: HttpHeadersBlock) -> Text | None:
    tc = get_theme_colors()
    t = Text()
    # [LAW:dataflow-not-control-flow] Label dispatch via dict
    labels = {
        "response": "  Response HTTP {} ".format(block.status_code),
        "request": "  Request Headers ",
    }
    t.append(labels.get(block.header_type, "  Headers "), style=f"bold {tc.info}")

    for key in sorted(block.headers.keys()):
        value = block.headers[key]
        t.append("\n    {}: ".format(key), style=f"dim {tc.info}")
        t.append(value, style="dim")

    return t


def _render_http_headers_summary(block: HttpHeadersBlock) -> Text | None:
    """One-liner summary for HttpHeadersBlock at SUMMARY level."""
    tc = get_theme_colors()
    t = Text("  ")
    n = len(block.headers)
    # [LAW:dataflow-not-control-flow] Label dispatch via dict
    labels = {
        "response": ("HTTP {}".format(block.status_code), f"bold {tc.success}"),
        "request": ("Request Headers", f"bold {tc.info}"),
    }
    label, style = labels.get(block.header_type, ("Headers", "bold"))
    t.append(label, style=style)
    t.append("  ({} header{})".format(n, "s" if n != 1 else ""), style="dim")
    # Show content-type inline when present
    ct = block.headers.get("content-type", "")
    if ct:
        t.append("  content-type: {}".format(ct), style="dim")
    return t


def _render_metadata(block: MetadataBlock) -> Text | None:
    parts = [
        "model: ",
        ("{}".format(block.model), "bold"),
        " | max_tokens: {}".format(block.max_tokens),
        " | stream: {}".format(block.stream),
    ]
    if block.tool_count:
        parts.append(" | tools: {}".format(block.tool_count))
    # API metadata from metadata.user_id field (truncate for readability)
    if block.user_hash:
        parts.append(" | user: {}..".format(block.user_hash[:6]))
    if block.account_id:
        parts.append(" | account: {}".format(block.account_id[:8]))
    if block.session_id:
        parts.append(" | session: {}".format(block.session_id[:8]))

    t = Text()
    t.append("  ", style="dim")
    for part in parts:
        if isinstance(part, tuple):
            t.append(part[0], style=part[1])
        else:
            t.append(part)
    t.stylize("dim")
    return t


def _render_new_session(block: NewSessionBlock) -> Text | None:
    """Render a NewSessionBlock - prominent session boundary indicator."""
    tc = get_theme_colors()
    t = Text()
    t.append("═" * 40, style=f"bold {tc.info}")
    t.append("\n")
    t.append(" NEW SESSION: ", style=f"bold {tc.info}")
    t.append(block.session_id, style="bold")
    t.append("\n")
    t.append("═" * 40, style=f"bold {tc.info}")
    return t


def _render_system_label(block: SystemLabelBlock) -> Text | None:
    tc = get_theme_colors()
    return Text("SYSTEM:", style=f"bold {tc.system}")


def _render_tracked_new(
    block: TrackedContentBlock, tag_style: str
) -> ConsoleRenderable:
    """Render a TrackedContentBlock with status='new'."""
    content_len = len(block.content)
    header = Text(block.indent + "  ")
    header.append(" {} ".format(block.tag_id), style=tag_style)
    header.append(" NEW ({} chars):".format(content_len))

    # Render content as Markdown
    content_md = _render_text_as_markdown(block.content)

    return Group(header, content_md)


def _render_tracked_ref(block: TrackedContentBlock, tag_style: str) -> Text:
    """Render a TrackedContentBlock with status='ref'."""
    t = Text(block.indent + "  ")
    t.append(" {} ".format(block.tag_id), style=tag_style)
    t.append(" (unchanged)")
    return t


def _render_tracked_changed(block: TrackedContentBlock, tag_style: str) -> Text:
    """Render a TrackedContentBlock with status='changed'."""
    old_len = len(block.old_content)
    new_len = len(block.new_content)
    t = Text(block.indent + "  ")
    t.append(" {} ".format(block.tag_id), style=tag_style)
    t.append(" CHANGED ({} -> {} chars):\n".format(old_len, new_len))
    diff_lines = make_diff_lines(block.old_content, block.new_content)
    t.append(_render_diff(diff_lines, block.indent + "    "))
    return t


# [LAW:dataflow-not-control-flow] TrackedContentBlock status dispatch
_TRACKED_STATUS_RENDERERS = {
    "new": _render_tracked_new,
    "ref": _render_tracked_ref,
    "changed": _render_tracked_changed,
}


def _render_tracked_content_summary(
    block: TrackedContentBlock,
) -> ConsoleRenderable | None:
    """Render a TrackedContentBlock at SUMMARY level — tag colors + diff-aware display."""
    fg, bg = TAG_STYLES[block.color_idx % len(TAG_STYLES)]
    tag_style = "bold {} on {}".format(fg, bg)

    renderer = _TRACKED_STATUS_RENDERERS.get(block.status)
    if renderer:
        return renderer(block, tag_style)
    return Text("")


def _render_tracked_content_full(
    block: TrackedContentBlock,
) -> ConsoleRenderable | None:
    """Render TrackedContentBlock at FULL level — just the content, like any text block.

    // [LAW:one-source-of-truth] block.content is always the current text.
    // No status dispatch, no diff, no tag styling — renderers decide presentation.
    """
    if not block.content:
        return None
    return _render_text_as_markdown(block.content)


def _render_role(block: RoleBlock) -> Text | None:
    role_lower = block.role.lower()
    style = ROLE_STYLES.get(role_lower, "bold magenta")
    label = block.role.upper().replace("_", " ")
    t = Text(label, style=style)
    if block.timestamp:
        t.append(f"  {block.timestamp}", style="dim")
    return t


def _get_or_segment(block):
    """Lazy segmentation, cached on the block object."""
    if not hasattr(block, "_segment_result"):
        from cc_dump.segmentation import segment

        block._segment_result = segment(block.text)
    return block._segment_result


def _render_text_as_markdown(text: str) -> ConsoleRenderable:
    """Render text string as Markdown using SubBlock segmentation.

    // [LAW:dataflow-not-control-flow] Dispatch via SubBlockKind match.

    Extracted from _render_segmented_block to enable reuse for TrackedContentBlock.
    """
    from cc_dump.segmentation import (
        segment,
        SubBlockKind,
        wrap_tags_in_backticks,
        wrap_tags_outside_fences,
    )

    tc = get_theme_colors()
    seg = segment(text)

    # Single SubBlock of kind MD: fast path — just Markdown with tag wrapping
    if len(seg.sub_blocks) == 1 and seg.sub_blocks[0].kind == SubBlockKind.MD:
        return Markdown(wrap_tags_in_backticks(text), code_theme=tc.code_theme)

    parts: list[ConsoleRenderable] = []
    for sb in seg.sub_blocks:
        text_slice = text[sb.span.start : sb.span.end]

        if sb.kind == SubBlockKind.MD:
            wrapped = wrap_tags_in_backticks(text_slice)
            if wrapped.strip():
                parts.append(Markdown(wrapped, code_theme=tc.code_theme))

        elif sb.kind == SubBlockKind.MD_FENCE:
            inner = text[sb.meta.inner_span.start : sb.meta.inner_span.end]
            wrapped = wrap_tags_in_backticks(inner)
            if wrapped.strip():
                parts.append(Markdown(wrapped, code_theme=tc.code_theme))

        elif sb.kind == SubBlockKind.CODE_FENCE:
            inner = text[sb.meta.inner_span.start : sb.meta.inner_span.end]
            parts.append(Syntax(inner, sb.meta.info or "", theme=tc.code_theme))

        elif sb.kind == SubBlockKind.XML_BLOCK:
            m = sb.meta
            start_tag = text[m.start_tag_span.start : m.start_tag_span.end].rstrip("\n")
            end_tag = text[m.end_tag_span.start : m.end_tag_span.end].rstrip("\n")
            inner = text[m.inner_span.start : m.inner_span.end]
            xml_parts: list[ConsoleRenderable] = [_render_xml_tag(start_tag)]
            if inner.strip():
                xml_parts.append(
                    Markdown(
                        wrap_tags_outside_fences(inner),
                        code_theme=tc.code_theme,
                    )
                )
            xml_parts.append(_render_xml_tag(end_tag))
            parts.append(Group(*xml_parts))

    if not parts:
        return Markdown(wrap_tags_in_backticks(text), code_theme=tc.code_theme)
    if len(parts) == 1:
        return parts[0]
    return Group(*parts)


def _render_segmented_block(block) -> ConsoleRenderable:
    """Render a text block using SubBlock segmentation.

    // [LAW:dataflow-not-control-flow] Dispatch via SubBlockKind match.
    """
    # Use cached segmentation on the block object for efficiency
    seg = _get_or_segment(block)
    return _render_text_as_markdown(block.text)


def _render_xml_collapsed(tag_name: str, inner_line_count: int) -> ConsoleRenderable:
    """Render a collapsed XML sub-block indicator with themed syntax colors.

    // [LAW:one-source-of-truth] _render_xml_tag for all XML tag rendering.
    // [LAW:one-source-of-truth] Collapsed XML arrow is ▷ (summary collapsed).
    """
    return _render_xml_tag(f"▷ <{tag_name}> ({inner_line_count} lines)")


def _render_region_parts(
    block,
) -> list[tuple[ConsoleRenderable, int | None]]:
    """Render text into per-part renderables using block.content_regions for state.

    Like _render_text_as_markdown() but returns (renderable, region_index)
    tuples. Non-XML parts have region_index=None. XML sub-blocks have
    their index from the content_regions list.

    // [LAW:dataflow-not-control-flow] content_regions controls the data;
    // region.expanded=None means expanded (default True).

    Args:
        block: A block with .text and .content_regions already populated
            by _ensure_content_regions().

    Returns:
        List of (renderable, region_idx_or_None) tuples.
    """
    from cc_dump.segmentation import (
        SubBlockKind,
        wrap_tags_in_backticks,
        wrap_tags_outside_fences,
    )

    text = block.text
    regions = block.content_regions

    tc = get_theme_colors()
    seg = _get_or_segment(block)

    # Build lookup: region index → expanded state
    # // [LAW:dataflow-not-control-flow] Value lookup, not branch
    region_expanded = {r.index: r.expanded for r in regions}

    parts: list[tuple[ConsoleRenderable, int | None]] = []
    xml_sb_idx = 0

    for sb in seg.sub_blocks:
        text_slice = text[sb.span.start : sb.span.end]

        if sb.kind == SubBlockKind.MD:
            wrapped = wrap_tags_in_backticks(text_slice)
            if wrapped.strip():
                parts.append((Markdown(wrapped, code_theme=tc.code_theme), None))

        elif sb.kind == SubBlockKind.MD_FENCE:
            inner = text[sb.meta.inner_span.start : sb.meta.inner_span.end]
            wrapped = wrap_tags_in_backticks(inner)
            if wrapped.strip():
                parts.append((Markdown(wrapped, code_theme=tc.code_theme), None))

        elif sb.kind == SubBlockKind.CODE_FENCE:
            inner = text[sb.meta.inner_span.start : sb.meta.inner_span.end]
            parts.append(
                (
                    Syntax(inner, sb.meta.info or "", theme=tc.code_theme),
                    None,
                )
            )

        elif sb.kind == SubBlockKind.XML_BLOCK:
            current_xml_idx = xml_sb_idx
            xml_sb_idx += 1

            # expanded=None or True means expanded; False means collapsed
            is_expanded = region_expanded.get(current_xml_idx, None) is not False

            m = sb.meta
            inner = text[m.inner_span.start : m.inner_span.end]
            inner_line_count = inner.count("\n") + (
                1 if inner and not inner.endswith("\n") else 0
            )

            if is_expanded:
                # Full XML rendering with syntax-highlighted tags
                start_tag = text[m.start_tag_span.start : m.start_tag_span.end].rstrip(
                    "\n"
                )
                end_tag = text[m.end_tag_span.start : m.end_tag_span.end].rstrip("\n")
                # Expanded XML: arrow + tag as header, then content, then end tag
                # // [LAW:dataflow-not-control-flow] Group always created,
                # inner content varies by data
                # // [LAW:one-source-of-truth] _render_xml_tag for all XML tag rendering
                xml_parts_with_header: list[ConsoleRenderable] = [
                    _render_xml_tag("▽ " + start_tag)
                ]
                if inner.strip():
                    xml_parts_with_header.append(
                        Markdown(
                            wrap_tags_outside_fences(inner),
                            code_theme=tc.code_theme,
                        )
                    )
                xml_parts_with_header.append(_render_xml_tag(end_tag))
                parts.append((Group(*xml_parts_with_header), current_xml_idx))
            else:
                # Collapsed: one-line indicator
                collapsed = _render_xml_collapsed(m.tag_name, inner_line_count)
                parts.append((collapsed, current_xml_idx))

    if not parts:
        # Fallback: render as plain markdown
        md = _render_text_as_markdown(text)
        return [(md, None)]

    return parts


def _ensure_content_regions(block) -> None:
    """Lazily populate block.content_regions from segmentation if applicable.

    Returns early if content_regions is already populated. Only populates
    for text blocks in markdown categories that contain XML sub-blocks.

    // [LAW:one-source-of-truth] Single place that creates ContentRegion instances.
    // [LAW:dataflow-not-control-flow] Pure data population, not control flow.
    """
    from cc_dump.segmentation import SubBlockKind

    # Already populated — idempotent
    if block.content_regions:
        return

    if not hasattr(block, "text") or not block.text:
        return
    cat = getattr(block, "category", None)
    if cat not in _MARKDOWN_CATEGORIES:
        return
    seg = _get_or_segment(block)
    xml_count = sum(1 for sb in seg.sub_blocks if sb.kind == SubBlockKind.XML_BLOCK)
    if xml_count == 0:
        return

    # Populate content_regions — one per XML sub-block
    block.content_regions = [ContentRegion(index=i) for i in range(xml_count)]


def _render_text_content(block: TextContentBlock) -> ConsoleRenderable | None:
    if not block.text:
        return None
    # Render as segmented Markdown for USER and ASSISTANT categories
    if block.category in _MARKDOWN_CATEGORIES:
        return _render_segmented_block(block)
    return _indent_text(block.text, block.indent)


# ─── Language inference helper ─────────────────────────────────────────────────

# [LAW:one-source-of-truth] Single mapping from file extension to Pygments lexer name.
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "jsx",
    ".rs": "rust",
    ".go": "go",
    ".rb": "ruby",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sql": "sql",
    ".md": "markdown",
    ".swift": "swift",
    ".kt": "kotlin",
    ".lua": "lua",
    ".r": "r",
    ".R": "r",
    ".ex": "elixir",
    ".exs": "elixir",
    ".zig": "zig",
    ".nim": "nim",
    ".dart": "dart",
    ".vue": "vue",
    ".svelte": "svelte",
    ".tf": "terraform",
    ".dockerfile": "docker",
    ".proto": "protobuf",
    ".graphql": "graphql",
    ".gql": "graphql",
}


def _infer_lang_from_path(path: str) -> str:
    """Infer Pygments lexer name from a file path's extension.

    Returns empty string for unknown extensions (Syntax falls back to plain text).
    // [LAW:one-source-of-truth] _EXT_TO_LANG is the sole mapping.
    """
    import os

    _, ext = os.path.splitext(path)
    return _EXT_TO_LANG.get(ext.lower(), "")


def _tool_result_header(block: ToolResultBlock, color: str) -> Text:
    """Build the shared header line for ToolResultBlock rendering.

    // [LAW:one-source-of-truth] Single header builder for all tool result renderers.
    """
    suffix = " ERROR" if block.is_error else ""
    name_part = block.tool_name if block.tool_name else ""
    label = f"[Result: {name_part}{suffix}]" if name_part else f"[Result{suffix}]"
    t = Text("  ")
    t.append(label, style="bold {}".format(color))
    if block.detail:
        t.append(" {}".format(block.detail), style="dim")
    t.append(" ({} bytes)".format(block.size))
    return t


# ─── ToolUseBlock renderers ────────────────────────────────────────────────────


def _render_tool_use_oneliner(block: ToolUseBlock) -> Text | None:
    """One-liner ToolUseBlock renderer (used for summary level).

    // [LAW:one-source-of-truth] Renamed from original _render_tool_use.
    """
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    t = Text("  ")
    t.append("[Use: {}]".format(block.name), style="bold {}".format(color))
    if block.detail:
        t.append(" {}".format(block.detail), style="dim")
    t.append(" ({} bytes)".format(block.input_size))
    return t


def _render_tool_use_bash_full(block: ToolUseBlock) -> ConsoleRenderable | None:
    """Full ToolUseBlock for Bash: header + $ command with syntax highlighting.

    // [LAW:dataflow-not-control-flow] Dispatch via _TOOL_USE_FULL_RENDERERS table.
    """
    tc = get_theme_colors()
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    header = Text("  ")
    header.append("[Use: Bash]", style="bold {}".format(color))
    header.append(" ({} bytes)".format(block.input_size))

    command = block.tool_input.get("command", "")
    if not command:
        return header

    # Render command with bash syntax highlighting
    code = Syntax(
        "$ " + command,
        "bash",
        theme=tc.code_theme,
        background_color="default",
    )
    return Group(header, code)


def _render_tool_use_edit_full(block: ToolUseBlock) -> Text | None:
    """Full ToolUseBlock for Edit: header + old/new line count preview.

    // [LAW:dataflow-not-control-flow] Dispatch via _TOOL_USE_FULL_RENDERERS table.
    """
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    t = Text("  ")
    t.append("[Use: Edit]", style="bold {}".format(color))
    if block.detail:
        t.append(" {}".format(block.detail), style="dim")
    t.append(" ({} bytes)".format(block.input_size))

    old_str = block.tool_input.get("old_string", "")
    new_str = block.tool_input.get("new_string", "")
    old_lines = old_str.count("\n") + (1 if old_str else 0)
    new_lines = new_str.count("\n") + (1 if new_str else 0)

    tc = get_theme_colors()
    t.append("\n    ")
    t.append("- old ({} lines)".format(old_lines), style=tc.error)
    t.append(" / ")
    t.append("+ new ({} lines)".format(new_lines), style=tc.success)
    return t


# [LAW:dataflow-not-control-flow] Tool-specific full renderers for ToolUseBlock
_TOOL_USE_FULL_RENDERERS: dict[str, Callable] = {
    "Bash": _render_tool_use_bash_full,
    "Edit": _render_tool_use_edit_full,
}


def _render_tool_use_full(block: ToolUseBlock) -> ConsoleRenderable | None:
    """Full ToolUseBlock: dispatches to tool-specific or falls back to oneliner.

    // [LAW:dataflow-not-control-flow] Two-level dispatch via table lookup.
    """
    renderer = _TOOL_USE_FULL_RENDERERS.get(block.name)
    if renderer is not None:
        return renderer(block)
    return _render_tool_use_oneliner(block)


def _render_tool_use_full_with_desc(block: ToolUseBlock) -> ConsoleRenderable | None:
    """Full expanded ToolUseBlock: tool-specific rendering + description when available.

    // [LAW:dataflow-not-control-flow] Description is a value; empty string = no extra line.
    """
    base = _render_tool_use_full(block)
    if not block.description or base is None:
        return base
    # Append dim italic first line of description (max 120 chars)
    desc_line = block.description.split("\n", 1)[0]
    if len(desc_line) > 120:
        desc_line = desc_line[:117] + "..."
    desc_text = Text("    ")
    desc_text.append(desc_line, style="dim italic")
    return Group(base, desc_text)


# ─── ToolDefinitionsBlock renderers ────────────────────────────────────────────


def _render_tool_defs_summary_collapsed(block: ToolDefinitionsBlock) -> Text | None:
    """SUMMARY collapsed: one-line count + token total."""
    t = Text("  ")
    t.append(
        "{} tool{} / {} tokens".format(
            len(block.tools),
            "" if len(block.tools) == 1 else "s",
            _fmt_tokens(block.total_tokens),
        ),
        style="dim",
    )
    return t


def _render_tool_defs_summary_expanded(block: ToolDefinitionsBlock) -> Text | None:
    """SUMMARY expanded: two-column list of tool name + token count."""
    tc = get_theme_colors()
    t = Text("  ")
    t.append(
        "Tools ({} / {} tokens):".format(len(block.tools), _fmt_tokens(block.total_tokens)),
        style=f"bold {tc.info}",
    )
    # Find max name length for alignment
    names = [tool.get("name", "?") for tool in block.tools]
    max_name = max((len(n) for n in names), default=0)
    for i, tool in enumerate(block.tools):
        name = tool.get("name", "?")
        tokens = block.tool_tokens[i] if i < len(block.tool_tokens) else 0
        t.append("\n    ")
        t.append("{:<{}}".format(name, max_name + 2))
        t.append("{} tokens".format(_fmt_tokens(tokens)), style="dim")
    return t


def _render_tool_defs_full_collapsed(block: ToolDefinitionsBlock) -> Text | None:
    """FULL collapsed: comma-separated tool names."""
    names = [tool.get("name", "?") for tool in block.tools]
    preview = ", ".join(names)
    if len(preview) > 100:
        preview = preview[:97] + "..."
    t = Text("  ")
    t.append("Tools: ", style="bold")
    t.append(preview, style="dim")
    return t


def _render_tool_def_region_parts(
    block: ToolDefinitionsBlock,
) -> list[tuple[ConsoleRenderable, int | None]]:
    """FULL expanded: per-tool region parts with expand/collapse arrows.

    Returns (renderable, region_index) tuples for the region rendering pipeline.
    // [LAW:dataflow-not-control-flow] content_regions controls the data;
    // region.expanded=None means expanded (default True), False means collapsed.
    """
    tc = get_theme_colors()
    parts: list[tuple[ConsoleRenderable, int | None]] = []

    # Header (non-region)
    header = Text("  ")
    header.append(
        "Tools: {} definitions ({} tokens)".format(
            len(block.tools), _fmt_tokens(block.total_tokens)
        ),
        style=f"bold {tc.info}",
    )
    parts.append((header, None))

    # Build region expanded lookup
    region_expanded = {r.index: r.expanded for r in block.content_regions}

    for i, tool in enumerate(block.tools):
        name = tool.get("name", "?")
        tokens = block.tool_tokens[i] if i < len(block.tool_tokens) else 0
        desc = tool.get("description", "")
        is_expanded = region_expanded.get(i, None) is not False

        if is_expanded:
            # Expanded: arrow + name + full description + params
            t = Text("    ")
            t.append("\u25bd ", style=f"bold {tc.info}")  # ▽
            t.append(name, style="bold")
            t.append(" ({} tok)".format(_fmt_tokens(tokens)), style="dim")
            if desc:
                t.append(":\n      ")
                t.append(desc, style="dim italic")
            # Show required params from input_schema
            schema = tool.get("input_schema", {})
            properties = schema.get("properties", {})
            required = set(schema.get("required", []))
            if properties:
                for pname, pinfo in properties.items():
                    ptype = pinfo.get("type", "")
                    req_marker = "*" if pname in required else ""
                    t.append("\n      ")
                    t.append("{}{}".format(pname, req_marker), style="bold dim")
                    if ptype:
                        t.append(": {}".format(ptype), style="dim")
            parts.append((t, i))
        else:
            # Collapsed: arrow + name + first line of desc
            t = Text("    ")
            t.append("\u25b7 ", style=f"bold {tc.info}")  # ▷
            t.append(name, style="bold")
            t.append(" ({} tok)".format(_fmt_tokens(tokens)), style="dim")
            if desc:
                first_line = desc.split("\n", 1)[0]
                if len(first_line) > 80:
                    first_line = first_line[:77] + "..."
                t.append(": ", style="dim")
                t.append(first_line, style="dim italic")
            parts.append((t, i))

    return parts


# ─── ToolResultBlock renderers ─────────────────────────────────────────────────


def _render_tool_result_summary(block: ToolResultBlock) -> Text | None:
    """Summary ToolResultBlock: header only, no content.

    // [LAW:dataflow-not-control-flow] Registered in BLOCK_STATE_RENDERERS.
    """
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    return _tool_result_header(block, color)


def _render_read_content(block: ToolResultBlock) -> ConsoleRenderable | None:
    """Render Read tool result content with syntax highlighting by file extension.

    // [LAW:dataflow-not-control-flow] Dispatch via _TOOL_RESULT_CONTENT_RENDERERS.
    """
    tc = get_theme_colors()
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    header = _tool_result_header(block, color)

    if not block.content:
        return header

    # Infer language from file path in tool_input or detail
    file_path = block.tool_input.get("file_path", "") or block.detail or ""
    lang = _infer_lang_from_path(file_path)

    code = Syntax(
        block.content,
        lang or "text",
        theme=tc.code_theme,
        background_color="default",
    )
    return Group(header, code)


def _render_confirm_content(block: ToolResultBlock) -> Text | None:
    """Render Write/Edit result: ✓ for success, error content for errors.

    // [LAW:dataflow-not-control-flow] Dispatch via _TOOL_RESULT_CONTENT_RENDERERS.
    """
    tc = get_theme_colors()
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    header = _tool_result_header(block, color)

    if block.is_error and block.content:
        header.append("\n")
        header.append(block.content, style=tc.error)
        return header

    header.append(" ")
    header.append("✓", style=f"bold {tc.success}")
    return header


# [LAW:dataflow-not-control-flow] Tool-specific content renderers for ToolResultBlock
_TOOL_RESULT_CONTENT_RENDERERS: dict[str, Callable] = {
    "Read": _render_read_content,
    "Write": _render_confirm_content,
    "Edit": _render_confirm_content,
}


def _render_tool_result_full(block: ToolResultBlock) -> ConsoleRenderable | None:
    """Full ToolResultBlock: dispatches to tool-specific or falls back to generic.

    // [LAW:dataflow-not-control-flow] Two-level dispatch via table lookup.
    """
    renderer = _TOOL_RESULT_CONTENT_RENDERERS.get(block.tool_name)
    if renderer is not None:
        return renderer(block)

    # Generic fallback: header + dim content
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    header = _tool_result_header(block, color)
    if block.content:
        header.append("\n")
        header.append(block.content, style="dim")
    return header


def _render_tool_use_summary(block: ToolUseSummaryBlock) -> Text | None:
    parts = ["{} {}x".format(name, count) for name, count in block.tool_counts.items()]
    t = Text("  ")
    t.append(
        "[used {} tool{}: {}]".format(
            block.total,
            "" if block.total == 1 else "s",
            ", ".join(parts),
        ),
        style="dim",
    )
    return t


def _render_image(block: ImageBlock) -> Text | None:
    return Text("  [image: {}]".format(block.media_type), style="dim")


def _render_unknown_type(block: UnknownTypeBlock) -> Text | None:
    return Text("  [{}]".format(block.block_type), style="dim")


def _render_stream_info(block: StreamInfoBlock) -> Text | None:
    t = Text("  ", style="dim")
    t.append("model: ")
    t.append(block.model, style="bold")
    return t


def _render_stream_tool_use(block: StreamToolUseBlock) -> Text | None:
    tc = get_theme_colors()
    t = Text("\n  ")
    t.append("[tool_use]", style=f"bold {tc.info}")
    t.append(" " + block.name)
    return t


def _render_text_delta(block: TextDeltaBlock) -> ConsoleRenderable | None:
    # TextDeltaBlock is always ASSISTANT category during streaming
    if block.category in _MARKDOWN_CATEGORIES:
        return _render_segmented_block(block)
    return Text(block.text)


def _render_stop_reason(block: StopReasonBlock) -> Text | None:
    t = Text("\n  stop: " + block.reason, style="dim")
    return t


def _render_error(block: ErrorBlock) -> Text | None:
    tc = get_theme_colors()
    return Text(
        "\n  [HTTP {} {}]".format(block.code, block.reason),
        style=f"bold {tc.error}",
    )


def _render_proxy_error(block: ProxyErrorBlock) -> Text | None:
    tc = get_theme_colors()
    return Text(
        "\n  [PROXY ERROR: {}]".format(block.error),
        style=f"bold {tc.error}",
    )


def _render_newline(block: NewlineBlock) -> Text | None:
    return Text("")


def _render_turn_budget(block: TurnBudgetBlock) -> Text | None:
    """Render TurnBudget as a compact multi-line summary."""
    tc = get_theme_colors()
    b = block.budget
    total = b.total_est

    sys_tok = b.system_tokens_est + b.tool_defs_tokens_est
    conv_tok = b.conversation_tokens_est
    tool_tok = b.tool_use_tokens_est + b.tool_result_tokens_est

    t = Text("  ")
    t.append("Context: ", style="bold")
    t.append("{} tok".format(_fmt_tokens(total)))
    t.append(
        " | sys: {} ({})".format(_fmt_tokens(sys_tok), _pct(sys_tok, total)),
        style=f"dim {tc.info}",
    )
    t.append(
        " | tools: {} ({})".format(_fmt_tokens(tool_tok), _pct(tool_tok, total)),
        style=f"dim {tc.warning}",
    )
    t.append(
        " | conv: {} ({})".format(_fmt_tokens(conv_tok), _pct(conv_tok, total)),
        style=f"dim {tc.success}",
    )

    # Tool result breakdown by name
    if block.tool_result_by_name:
        parts = []
        sorted_tools = sorted(
            block.tool_result_by_name.items(), key=lambda x: x[1], reverse=True
        )
        for name, tokens in sorted_tools[:5]:
            parts.append("{}: {}".format(name, _fmt_tokens(tokens)))
        t.append(
            "\n    tool_use: {} | tool_results: {} ({})".format(
                _fmt_tokens(b.tool_use_tokens_est),
                _fmt_tokens(b.tool_result_tokens_est),
                ", ".join(parts),
            ),
            style="dim",
        )

    # Cache info (if actual data is available)
    if b.actual_input_tokens > 0 or b.actual_cache_read_tokens > 0:
        t.append("\n    ")
        t.append("Cache: ", style="bold")
        t.append(
            "{} read ({})".format(
                _fmt_tokens(b.actual_cache_read_tokens),
                _pct(
                    b.actual_cache_read_tokens,
                    b.actual_input_tokens + b.actual_cache_read_tokens,
                ),
            ),
            style=f"dim {tc.info}",
        )
        if b.actual_cache_creation_tokens > 0:
            t.append(
                " | {} created".format(_fmt_tokens(b.actual_cache_creation_tokens)),
                style=f"dim {tc.warning}",
            )
        t.append(" | {} fresh".format(_fmt_tokens(b.actual_input_tokens)), style="dim")

    return t


# ─── State-specific renderers (BLOCK_STATE_RENDERERS) ─────────────────────────
# Custom renderers for specific (type, level, expanded) combinations.
# When present, output is used as-is (no generic truncation).
# When absent, BLOCK_RENDERERS output is truncated to TRUNCATION_LIMITS.


def _render_tracked_new_title(block: TrackedContentBlock, tag_style: str) -> Text:
    """Render title for TrackedContentBlock with status='new'."""
    t = Text(block.indent + "  ")
    t.append(" {} ".format(block.tag_id), style=tag_style)
    t.append(" NEW ({} chars)".format(len(block.content)))
    return t


def _render_tracked_ref_title(block: TrackedContentBlock, tag_style: str) -> Text:
    """Render title for TrackedContentBlock with status='ref'."""
    t = Text(block.indent + "  ")
    t.append(" {} ".format(block.tag_id), style=tag_style)
    t.append(" (unchanged)")
    return t


def _render_tracked_changed_title(block: TrackedContentBlock, tag_style: str) -> Text:
    """Render title for TrackedContentBlock with status='changed'."""
    t = Text(block.indent + "  ")
    t.append(" {} ".format(block.tag_id), style=tag_style)
    t.append(
        " CHANGED ({} -> {} chars)".format(
            len(block.old_content), len(block.new_content)
        )
    )
    return t


# [LAW:dataflow-not-control-flow] TrackedContentBlock title status dispatch
_TRACKED_STATUS_TITLE_RENDERERS = {
    "new": _render_tracked_new_title,
    "ref": _render_tracked_ref_title,
    "changed": _render_tracked_changed_title,
}


def _render_tracked_content_title(block: TrackedContentBlock) -> Text | None:
    """Title-only for TrackedContentBlock at EXISTENCE level."""
    fg, bg = TAG_STYLES[block.color_idx % len(TAG_STYLES)]
    tag_style = "bold {} on {}".format(fg, bg)
    renderer = _TRACKED_STATUS_TITLE_RENDERERS.get(block.status)
    if renderer:
        return renderer(block, tag_style)
    return Text(block.indent + "  ")


def _render_turn_budget_oneliner(block: TurnBudgetBlock) -> Text | None:
    """One-line context total for TurnBudgetBlock at EXISTENCE level."""
    b = block.budget
    t = Text("  ")
    t.append("Context: ", style="bold")
    t.append("{} tok".format(_fmt_tokens(b.total_est)))
    return t


# ─── Registries ────────────────────────────────────────────────────────────────

# Full content renderers. Signature: (block) -> ConsoleRenderable | None
BLOCK_RENDERERS: dict[str, Callable[[FormattedBlock], ConsoleRenderable | None]] = {
    "SeparatorBlock": _render_separator,
    "HeaderBlock": _render_header,
    "HttpHeadersBlock": _render_http_headers,
    "MetadataBlock": _render_metadata,
    "NewSessionBlock": _render_new_session,
    "TurnBudgetBlock": _render_turn_budget,
    "SystemLabelBlock": _render_system_label,
    "TrackedContentBlock": _render_tracked_content_full,
    "RoleBlock": _render_role,
    "TextContentBlock": _render_text_content,
    "ToolDefinitionsBlock": _render_tool_defs_summary_collapsed,
    "ToolUseBlock": _render_tool_use_full,
    "ToolResultBlock": _render_tool_result_full,
    "ToolUseSummaryBlock": _render_tool_use_summary,
    "ImageBlock": _render_image,
    "UnknownTypeBlock": _render_unknown_type,
    "StreamInfoBlock": _render_stream_info,
    "StreamToolUseBlock": _render_stream_tool_use,
    "TextDeltaBlock": _render_text_delta,
    "StopReasonBlock": _render_stop_reason,
    "ErrorBlock": _render_error,
    "ProxyErrorBlock": _render_proxy_error,
    "NewlineBlock": _render_newline,
}

# State-specific renderers (override full renderers for specific vis_states)
# Keyed by (type_name, visible, full, expanded).
# // [LAW:dataflow-not-control-flow] Registries replace conditional dispatch.
BLOCK_STATE_RENDERERS: dict[
    tuple[str, bool, bool, bool], Callable[[FormattedBlock], ConsoleRenderable | None]
] = {
    # TrackedContentBlock: title-only at summary level collapsed, diff-aware at summary expanded
    ("TrackedContentBlock", True, False, False): _render_tracked_content_title,
    ("TrackedContentBlock", True, False, True): _render_tracked_content_summary,
    # HttpHeadersBlock: one-liner at summary level collapsed
    ("HttpHeadersBlock", True, False, False): _render_http_headers_summary,
    # TurnBudgetBlock: oneliner at summary level
    ("TurnBudgetBlock", True, False, False): _render_turn_budget_oneliner,
    ("TurnBudgetBlock", True, False, True): _render_turn_budget_oneliner,
    # ToolResultBlock: header-only at full collapsed (no raw content dump)
    ("ToolResultBlock", True, True, False): _render_tool_result_summary,
    # ToolUseBlock: one-liner at full collapsed, description at full expanded
    ("ToolUseBlock", True, True, False): _render_tool_use_oneliner,
    ("ToolUseBlock", True, True, True): _render_tool_use_full_with_desc,
    # ToolDefinitionsBlock: 3 state-specific renderers (FULL expanded falls through to regions)
    ("ToolDefinitionsBlock", True, False, False): _render_tool_defs_summary_collapsed,
    ("ToolDefinitionsBlock", True, False, True): _render_tool_defs_summary_expanded,
    ("ToolDefinitionsBlock", True, True, False): _render_tool_defs_full_collapsed,
    # No entry for (True, True, True) → falls through to region rendering
}


def _build_renderer_registry() -> dict[tuple[str, bool, bool, bool], Callable]:
    """Build unified renderer registry. Every (type, vis_state) has one renderer.

    // [LAW:dataflow-not-control-flow] Single lookup replaces conditional dispatch.
    """
    registry: dict[tuple[str, bool, bool, bool], Callable] = {}
    visible_states = [
        (True, False, False),
        (True, False, True),
        (True, True, False),
        (True, True, True),
    ]
    # Populate all visible states with the full renderer
    for type_name, fn in BLOCK_RENDERERS.items():
        for vis in visible_states:
            registry[(type_name, *vis)] = fn
    # State-specific overrides replace full renderers for specific states
    registry.update(BLOCK_STATE_RENDERERS)
    return registry


RENDERERS = _build_renderer_registry()


# ─── Tool pre-pass ─────────────────────────────────────────────────────────────


def collapse_tool_runs(
    blocks: list, tools_on: bool
) -> list[tuple[int, FormattedBlock]]:
    """Pre-pass: collapse consecutive ToolUseBlock runs into ToolUseSummaryBlock.

    When tools_on=True, returns blocks with their original indices unchanged.
    When tools_on=False, consecutive ToolUseBlock+ToolResultBlock runs are replaced
    with a single ToolUseSummaryBlock containing the aggregated counts.

    Returns list of (original_block_index, block) tuples.
    """
    if tools_on:
        return [(i, block) for i, block in enumerate(blocks)]

    _tool_types = {"ToolUseBlock", "ToolResultBlock"}
    result: list[tuple[int, FormattedBlock]] = []
    pending: list[tuple[int, FormattedBlock]] = []

    def flush():
        if not pending:
            return
        # Check if any pending block has _force_vis override (search mode)
        # If so, emit individual blocks instead of collapsing
        if any(getattr(b, "_force_vis", None) is not None for _, b in pending):
            result.extend(pending)
            pending.clear()
            return
        first_idx = pending[0][0]
        # Count only ToolUseBlocks for the summary counts
        use_blocks = [b for _, b in pending if type(b).__name__ == "ToolUseBlock"]
        # [LAW:dataflow-not-control-flow] No tool uses = no summary to create;
        # orphaned ToolResultBlocks without a preceding ToolUseBlock are dropped
        if not use_blocks:
            pending.clear()
            return
        counts = Counter(b.name for b in use_blocks)
        result.append(
            (
                first_idx,
                ToolUseSummaryBlock(
                    tool_counts=dict(counts),
                    total=len(use_blocks),
                    first_block_index=first_idx,
                ),
            )
        )
        pending.clear()

    for i, block in enumerate(blocks):
        if type(block).__name__ in _tool_types:
            pending.append((i, block))
        else:
            flush()
            result.append((i, block))

    flush()
    return result


def _prepare_blocks(blocks: list, filters: dict) -> list[tuple[int, FormattedBlock]]:
    """Pre-pass: apply tool summarization based on tools level.

    // [LAW:dataflow-not-control-flow] tools_on is a value, not a branch.
    """
    tools_filter = filters.get("tools", ALWAYS_VISIBLE)
    tools_on = tools_filter.full  # individual tools at FULL level
    return collapse_tool_runs(blocks, tools_on)


# ─── Truncation and collapse indicator ─────────────────────────────────────────


def _make_collapse_indicator(hidden_lines: int, content_width: int):
    """Create a dim '... N more lines' strip at content width (gutter added separately)."""
    from rich.segment import Segment
    from rich.style import Style
    from textual.strip import Strip

    text = "    \u00b7\u00b7\u00b7 {} more lines".format(hidden_lines)
    seg = Segment(text, style=Style(dim=True))
    # // [LAW:no-shared-mutable-globals] adjust_cell_length returns a NEW Strip
    return Strip([seg]).adjust_cell_length(content_width)


# ─── Gutter constants ──────────────────────────────────────────────────────────
# [LAW:one-source-of-truth] Single constant controls gutter sizing for all blocks
GUTTER_WIDTH = 4  # "▌▶  " or "▌   " — tweak this one value to resize all gutters
RIGHT_GUTTER_WIDTH = 1  # "▐"
MIN_WIDTH_FOR_RIGHT_GUTTER = 40  # hide right gutter below this width

# [LAW:one-source-of-truth] Arrow icons by vis state (mirrors _VIS_ICONS in custom_footer.py)
# Key: (full, expanded) where expanded is the gutter's actual expanded state
GUTTER_ARROWS: dict[tuple[bool, bool], str] = {
    (False, False): "\u25b7",  # ▷ summary collapsed
    (False, True): "\u25bd",  # ▽ summary expanded
    (True, False): "\u25b6",  # ▶ full collapsed
    (True, True): "\u25bc",  # ▼ full expanded
}


def _add_gutter_to_strips(
    block_strips,
    indicator_name: str | None,
    is_expandable: bool,
    arrow_char: str,
    width: int,
    neutral: bool = False,
    show_right: bool = True,
):
    """Add gutter columns (left + optional right) to ALL strips.

    Strip 0: [▌][arrow_char + "  "] + content + [▐]
    Strip 1+: [▌]["   "] + content + [▐]

    Content is assumed to be rendered at (width - GUTTER_WIDTH - RIGHT_GUTTER_WIDTH).
    This function prepends the left gutter, appends the right gutter, and adjusts final width.

    // [LAW:one-source-of-truth] GUTTER_WIDTH and RIGHT_GUTTER_WIDTH define all sizing.

    Args:
        block_strips: Pre-rendered content strips at content width
        indicator_name: Category name for color lookup (None for neutral mode)
        is_expandable: Whether block can be toggled
        arrow_char: Arrow character from GUTTER_ARROWS (empty string if not expandable)
        width: Final target width (includes gutters)
        neutral: If True, use dim style instead of category color (for NewlineBlock, etc.)
        show_right: If True, append right gutter segment
    """
    if not block_strips:
        return block_strips

    from rich.segment import Segment
    from rich.style import Style
    from textual.strip import Strip

    # Neutral mode: dim gutters, no arrow
    if neutral:
        left_seg = Segment("\u258c", Style(dim=True))  # ▌
        arrow_seg = Segment("   ", Style())  # three spaces
        continuation_seg = Segment("   ", Style())
        right_seg = Segment("\u2590", Style(dim=True)) if show_right else None  # ▐
    # Category mode: colored gutters + arrow
    elif indicator_name and indicator_name in FILTER_INDICATORS:
        symbol, color = FILTER_INDICATORS[indicator_name]
        left_seg = Segment(symbol, Style(bold=True, color=color))

        # First strip: arrow (if expandable) or spaces
        # // [LAW:single-enforcer] Meta on arrow segment is the sole toggle trigger
        if is_expandable and arrow_char:
            arrow_style = Style(color=color, bold=True) + Style.from_meta(
                {META_TOGGLE_BLOCK: True}
            )
            arrow_seg = Segment(arrow_char + "  ", arrow_style)
        else:
            arrow_seg = Segment("   ", Style())

        # Continuation strips: spaces
        continuation_seg = Segment("   ", Style())
        right_seg = (
            Segment("\u2590", Style(bold=True, color=color)) if show_right else None
        )  # ▐
    else:
        # No gutter mode
        return block_strips

    # Width for content + left gutter (everything except right gutter).
    # Pad to this first so the right gutter lands at the terminal edge.
    inner_width = width - (RIGHT_GUTTER_WIDTH if right_seg is not None else 0)

    result_strips = []
    for i, strip in enumerate(block_strips):
        segments = list(strip)

        # Prepend left gutter
        if i == 0:
            new_segments = [left_seg, arrow_seg] + segments
        else:
            new_segments = [left_seg, continuation_seg] + segments

        # Pad content area to fill up to the right gutter column
        # // [LAW:no-shared-mutable-globals] adjust_cell_length returns a NEW Strip
        padded = Strip(new_segments).adjust_cell_length(inner_width)

        # Append right gutter AFTER padding so it sits at the right edge
        if right_seg is not None:
            padded = Strip(list(padded) + [right_seg])

        result_strips.append(padded)

    return result_strips


# ─── Region-part renderer dispatch ─────────────────────────────────────────────
# // [LAW:dataflow-not-control-flow] Dispatch table for block-type-specific region renderers.
# Blocks not in this table use the default _render_region_parts (XML-based).
_REGION_PART_RENDERERS: dict[str, Callable] = {
    "ToolDefinitionsBlock": _render_tool_def_region_parts,
}


# ─── Core rendering ───────────────────────────────────────────────────────────


def render_block(block: FormattedBlock) -> ConsoleRenderable | None:
    """Render a FormattedBlock to a Rich renderable object (full content).

    This is the public API for rendering a single block. Used by streaming code.
    No filter checks — returns full content always.
    Returns Text, Markdown, or other ConsoleRenderable.
    """
    renderer = BLOCK_RENDERERS.get(type(block).__name__)
    if renderer is None:
        return None
    return renderer(block)


def render_blocks(
    blocks: list[FormattedBlock],
    filters: dict,
) -> list[tuple[int, Text]]:
    """Render a list of FormattedBlock to indexed Rich Text objects, applying filters.

    When tools level is not FULL, consecutive ToolUse/ResultBlocks are collapsed
    into a single summary line like '[used 3 tools: Bash 2x, Read 1x]'.

    Returns:
        List of (block_index, Text) pairs.
    """
    prepared = _prepare_blocks(blocks, filters)

    rendered: list[tuple[int, Text]] = []
    for orig_idx, block in prepared:
        vis = _resolve_visibility(block, filters)
        max_lines = TRUNCATION_LIMITS[vis]

        if max_lines == 0:
            continue  # hidden

        type_name = type(block).__name__

        # Single unified renderer lookup
        renderer = RENDERERS.get((type_name, vis.visible, vis.full, vis.expanded))
        text = renderer(block) if renderer else None

        if text is not None:
            # Add category indicator
            indicator_name = _category_indicator_name(block)
            if indicator_name:
                text = _add_filter_indicator(text, indicator_name)
            rendered.append((orig_idx, text))

    return rendered


def render_turn_to_strips(
    blocks: list[FormattedBlock],
    filters: dict,
    console,
    width: int,
    wrap: bool = True,
    block_cache=None,
    is_streaming: bool = False,
    search_ctx=None,
    turn_index: int = -1,
) -> tuple[list, dict[int, int]]:
    """Render blocks to Strip objects for Line API storage.

    # [LAW:single-enforcer] All visibility logic happens here.

    Args:
        blocks: FormattedBlock list for one turn
        filters: Current filter state (category name -> Level)
        console: Rich Console instance
        width: Render width in cells
        wrap: Enable word wrapping
        block_cache: Optional LRUCache for caching rendered strips per block
        is_streaming: If True, skip truncation (show all content during stream)
        search_ctx: Optional SearchContext for highlighting matches
        turn_index: Turn index for search match correlation

    Returns:
        (strips, block_strip_map) — pre-rendered lines and a dict mapping
        block index to its first strip line index.
    """
    from rich.segment import Segment
    from rich.style import Style
    from textual.strip import Strip

    base_render_options = console.options
    if not wrap:
        base_render_options = base_render_options.update(
            overflow="ignore", no_wrap=True
        )

    # // [LAW:dataflow-not-control-flow] Compute gutter config once for all blocks
    show_right = width >= MIN_WIDTH_FOR_RIGHT_GUTTER
    total_gutter = GUTTER_WIDTH + (RIGHT_GUTTER_WIDTH if show_right else 0)
    render_width = max(1, width - total_gutter)
    base_render_options = base_render_options.update_width(render_width)

    all_strips: list[Strip] = []
    block_strip_map: dict[int, int] = {}

    prepared = _prepare_blocks(blocks, filters)

    for orig_idx, block in prepared:
        vis = _resolve_visibility(block, filters)
        max_lines = TRUNCATION_LIMITS[vis]

        # Hidden blocks produce 0 lines — skip early
        # // [LAW:dataflow-not-control-flow] 0 is the value; skipping is the operation for 0
        if max_lines == 0:
            continue

        type_name = type(block).__name__

        # Check if this block has search matches
        block_has_matches = False
        search_hash = None
        if search_ctx is not None:
            block_matches = search_ctx.matches_in_block(turn_index, orig_idx)
            block_has_matches = bool(block_matches)
            search_hash = search_ctx.pattern_str if block_has_matches else None

        # Resolve category indicator name
        indicator_name = _category_indicator_name(block)

        # Single unified renderer lookup
        # // [LAW:dataflow-not-control-flow] One lookup replaces conditional dispatch
        state_key = (type_name, vis.visible, vis.full, vis.expanded)
        renderer = RENDERERS.get(state_key)
        state_override = state_key in BLOCK_STATE_RENDERERS

        # Detect blocks with content regions for per-part rendering
        # // [LAW:dataflow-not-control-flow] Never parse XML on streaming blocks —
        # TextDeltaBlock text is incomplete fragments, segmentation would break.
        # // [LAW:one-source-of-truth] _ensure_content_regions populates block.content_regions
        if not is_streaming and not block_has_matches:
            _ensure_content_regions(block)
        has_regions = bool(block.content_regions)

        # Precedence: state-specific renderer > region rendering > default renderer
        # // [LAW:dataflow-not-control-flow] state_override is a value, not a branch
        if has_regions and not state_override:
            # Per-part region rendering path: render each segment separately
            # so we can track strip ranges for click-to-collapse
            region_renderer = _REGION_PART_RENDERERS.get(type_name, _render_region_parts)
            region_parts = region_renderer(block)

            # Include region expanded state in cache key
            region_cache_state = tuple(
                (r.index, r.expanded) for r in block.content_regions
            )
            cache_key = (
                id(block),
                render_width,
                vis,
                search_hash,
                region_cache_state,
            )

            if block_cache is not None and cache_key in block_cache:
                block_strips = block_cache[cache_key]
            else:
                # Render each part and assemble strips with range tracking
                block_strips = []

                for part_renderable, region_idx in region_parts:
                    part_start = len(block_strips)
                    part_segments = console.render(part_renderable, base_render_options)
                    part_lines = list(Segment.split_lines(part_segments))
                    if part_lines:
                        part_strips = [
                            s.adjust_cell_length(render_width)
                            for s in Strip.from_lines(part_lines)
                        ]
                        block_strips.extend(part_strips)

                    # Track region strip ranges and apply toggle meta
                    # // [LAW:single-enforcer] Meta on tag strips is the region toggle trigger
                    if region_idx is not None:
                        region = block.content_regions[region_idx]
                        region._strip_range = (part_start, len(block_strips))
                        region_meta = {META_TOGGLE_REGION: region_idx}
                        if part_start < len(block_strips):
                            # First strip: start tag or collapsed indicator
                            block_strips[part_start] = block_strips[
                                part_start
                            ].apply_meta(region_meta)
                            # Last strip: end tag (same as first when collapsed)
                            last_i = len(block_strips) - 1
                            if last_i != part_start:
                                block_strips[last_i] = block_strips[
                                    last_i
                                ].apply_meta(region_meta)

                if block_cache is not None:
                    block_cache[cache_key] = block_strips

            # Set text to non-None so the rest of the pipeline proceeds
            text = True  # sentinel — we already have block_strips

        elif renderer:
            # For Markdown blocks with search matches, render as plain Text
            # so highlight_regex works correctly
            if block_has_matches and isinstance(renderer(block), Markdown):
                # Re-render as plain Text for search highlighting
                plain_text = ""
                if hasattr(block, "text"):
                    plain_text = block.text
                text = Text(plain_text)
            else:
                text = renderer(block)
        else:
            text = None

        if text is None:
            continue

        # Apply search highlights (only on Text objects)
        if block_has_matches and isinstance(text, Text):
            _apply_search_highlights(text, search_ctx, turn_index, orig_idx)

        block_strip_map[orig_idx] = len(all_strips)

        # Standard rendering path (non-region or when text is a renderable)
        if not has_regions:
            # Cache key uses render_width (content width without gutter)
            cache_key = (
                id(block),
                render_width,
                vis,
                search_hash,
            )

            # Check cache first
            if block_cache is not None and cache_key in block_cache:
                cached = block_cache[cache_key]
                # Handle both old (list) and new (tuple) cache formats
                if isinstance(cached, tuple):
                    block_strips = cached[0]
                else:
                    block_strips = cached
            else:
                # Render block at render_width (all blocks use same width)
                segments = console.render(text, base_render_options)
                lines = list(Segment.split_lines(segments))
                if lines:
                    # // [LAW:no-shared-mutable-globals] adjust_cell_length returns
                    # a NEW Strip; build a fresh list so no reader sees unpadded data.
                    block_strips = [
                        s.adjust_cell_length(render_width)
                        for s in Strip.from_lines(lines)
                    ]
                else:
                    block_strips = []

                # Cache result
                if block_cache is not None:
                    block_cache[cache_key] = block_strips

        # Track expandability: always check against collapsed limit for this detail level
        # // [LAW:single-enforcer] _expandable enables click-to-expand interaction
        # // [LAW:dataflow-not-control-flow] Check if renderers differ, not if expansion "would happen"
        collapsed_limit = TRUNCATION_LIMITS[VisState(True, vis.full, False)]
        collapsed_key = (type_name, vis.visible, vis.full, False)
        expanded_key = (type_name, vis.visible, vis.full, True)
        has_different_expanded = RENDERERS.get(collapsed_key) is not RENDERERS.get(
            expanded_key
        )
        block._expandable = has_different_expanded or (
            collapsed_limit is not None
            and collapsed_limit > 0
            and len(block_strips) > collapsed_limit
        )

        # Truncation: ALWAYS applies when max_lines < strip count (not streaming)
        # // [LAW:dataflow-not-control-flow] No should_truncate flag, just max_lines value
        is_truncated = (
            not is_streaming and max_lines is not None and len(block_strips) > max_lines
        )

        if is_truncated:
            assert max_lines is not None  # implied by is_truncated
            hidden = len(block_strips) - max_lines
            truncated_strips = list(block_strips[:max_lines])
            truncated_strips.append(_make_collapse_indicator(hidden, render_width))
            block_strips_for_gutter = truncated_strips
            # Arrow: truncated blocks are collapsed
            arrow = (
                GUTTER_ARROWS.get((vis.full, False), "") if block._expandable else ""
            )
        else:
            block_strips_for_gutter = list(block_strips)
            # Arrow: non-truncated blocks use actual expanded state
            arrow = (
                GUTTER_ARROWS.get((vis.full, vis.expanded), "")
                if block._expandable
                else ""
            )

        # Unified gutter path — all blocks go through here
        is_neutral = indicator_name is None
        final_strips = _add_gutter_to_strips(
            block_strips_for_gutter,
            indicator_name,
            block._expandable,
            arrow,
            width,
            neutral=is_neutral,
            show_right=show_right,
        )
        all_strips.extend(final_strips)

    return all_strips, block_strip_map


def _apply_search_highlights(
    text: Text, search_ctx, turn_index: int, block_index: int
) -> None:
    """Apply search highlights to a Text object.

    All matches get a dim background highlight.
    The current navigated-to match gets a bright highlight override.
    """
    from rich.style import Style

    tc = get_theme_colors()

    # Dim highlight on ALL matches in this block
    try:
        text.highlight_regex(
            search_ctx.pattern,
            Style(bgcolor=tc.search_all_bg),
        )
    except Exception:
        return  # Regex may fail on rendered text, silently skip

    # Bright highlight on the CURRENT match (if it's in this block)
    current = search_ctx.current_match
    if (
        current is not None
        and current.turn_index == turn_index
        and current.block_index == block_index
    ):
        # Find the specific occurrence via pattern.finditer on plain text
        plain = text.plain
        try:
            for i, m in enumerate(search_ctx.pattern.finditer(plain)):
                # Find which occurrence in this block matches current_match's offset
                # We use the text_offset from SearchMatch which was computed on
                # the searchable text, not the rendered text. Since these may differ
                # (rendered text has indicators, indentation), we highlight the first
                # occurrence that overlaps.
                text.stylize(
                    Style.parse(tc.search_current_style),
                    m.start(),
                    m.end(),
                )
                break  # Highlight first match occurrence (most visible)
        except Exception:
            pass  # Silently handle regex errors on rendered text


def combine_rendered_texts(texts: list[Text]) -> Text:
    """Join rendered Text objects into a single Text with newline separators."""
    if not texts:
        return Text()
    if len(texts) == 1:
        return texts[0]
    combined = Text()
    for i, t in enumerate(texts):
        if i > 0:
            combined.append("\n")
        combined.append(t)
    return combined


# ─── Rendering helpers ─────────────────────────────────────────────────────────


def _render_diff(diff_lines: list, indent: str) -> Text:
    """Render diff lines with color-coded additions/deletions."""
    tc = get_theme_colors()
    # [LAW:dataflow-not-control-flow] Diff kind dispatch
    specs = {
        "hunk": ("", "dim"),
        "add": ("+ ", tc.success),
        "del": ("- ", tc.error),
    }
    t = Text()
    for i, (kind, text) in enumerate(diff_lines):
        if i > 0:
            t.append("\n")
        prefix, style = specs.get(kind, ("", ""))
        t.append(indent + prefix + text, style=style)
    return t


def _indent_text(text: str, indent: str) -> Text:
    """Indent each line of text with the given prefix."""
    lines = text.splitlines()
    t = Text()
    for i, line in enumerate(lines):
        if i > 0:
            t.append("\n")
        t.append(indent + line)
    return t


def _fmt_tokens(n: int) -> str:
    """Format token count for compact display: 1.2k, 68.9k, etc."""
    if n >= 1000:
        return "{:.1f}k".format(n / 1000)
    return str(n)


def _pct(part: int, total: int) -> str:
    """Format percentage."""
    if total == 0:
        return "0%"
    return "{:.0f}%".format(100 * part / total)
