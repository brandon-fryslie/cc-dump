"""Rich rendering for FormattedBlock structures in the TUI.

Converts structured IR from formatting.py into Rich Text objects for display.

Two-tier dispatch:
1. BLOCK_STATE_RENDERERS[(type_name, Level, expanded)] — custom per-state output
2. BLOCK_RENDERERS[type_name] — full content, then generic truncation via TRUNCATION_LIMITS

# [LAW:single-enforcer] All visibility logic is enforced in render_turn_to_strips().
# Individual renderers never check filters or collapsed state.
#
# Pygments Syntax() is for USER-AUTHORED code content (code fences, bash, etc.).
# Structural UI elements (XML tags, headers, labels) must use theme colors directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import MutableMapping
from typing import Callable, cast

from rich.text import Text
from rich.markdown import Markdown
from rich.console import ConsoleRenderable, Group
from rich.syntax import Syntax
from collections import Counter

from cc_dump.analysis import fmt_tokens as _fmt_tokens
from cc_dump.formatting import (
    FormattedBlock,
    SeparatorBlock,
    HeaderBlock,
    HttpHeadersBlock,
    MetadataBlock,
    NewSessionBlock,
    TrackedContentBlock,
    TextContentBlock,
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
    ALWAYS_VISIBLE,
)

import cc_dump.palette
import cc_dump.special_content

import re
import os
from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.color import Color
import cc_dump.segmentation

# Click-target meta keys — the sole identifiers for interactive segments.
# // [LAW:one-source-of-truth] Canonical constants; widget_factory reads these via module import.
META_TOGGLE_BLOCK = "toggle_block"
META_TOGGLE_REGION = "toggle_region"

# Region kinds that support click-to-collapse/expand.
# FUTURE: consider md/other region kinds for collapse behavior
COLLAPSIBLE_REGION_KINDS = frozenset({"xml_block", "tool_def", "code_fence"})


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
    follow_engaged_style: str

    # Search bar styles
    search_prompt_style: str
    search_active_style: str
    search_error_style: str
    search_keys_style: str

    # Markdown theme dict (for Rich console.push_theme)
    markdown_theme_dict: dict

    # Filter indicator colors: name → (gutter_fg, chip_bg, chip_fg)
    # // [LAW:one-source-of-truth] All filter colors derived from theme.
    filter_colors: dict[str, tuple[str, str, str]]

    # Action colors: pool of theme semantic colors for non-filter UI items
    # (panels, toggles, etc.). Naturally distinct from filter_colors since
    # filter hues are placed in gaps *between* these theme colors.
    action_colors: list[str]


def _normalize_color(color: str | None, fallback: str) -> str:
    """Normalize a theme color to #RRGGBB hex.

    Textual's ANSI themes use names like "ansi_green" that Rich can't parse
    in style strings. Convert via Textual's Color.parse().rgb, falling back
    to the provided default if parsing fails.

    "ansi_default" means "terminal's default" — unknowable at runtime, so
    we treat it as None and use the fallback.
    // [LAW:single-enforcer] All color normalization goes through here.
    """
    if color is None or color == "ansi_default":
        return fallback
    if color.startswith("#") and len(color) == 7:
        return color
    try:
        c = Color.parse(color)
        r, g, b = c.rgb
        return "#{:02X}{:02X}{:02X}".format(r, g, b)
    except Exception:
        return fallback


def _is_ansi_default(color: str | None) -> bool:
    """Check if a theme color is the unknowable terminal default."""
    return color is None or color == "ansi_default"


def build_theme_colors(textual_theme) -> ThemeColors:
    """Map a Textual Theme to ThemeColors.

    Handles None fields and ANSI color names with sensible derivations.
    When bg/fg/surface are all unknowable (ansi_default), assumes dark mode
    for fallback values since terminal TUI users overwhelmingly use dark backgrounds.
    """
    dark = textual_theme.dark

    # If bg/fg/surface are all unknowable, override dark assumption
    # // [LAW:dataflow-not-control-flow] assume_dark is a value, not a branch
    assume_dark = dark or all(
        _is_ansi_default(getattr(textual_theme, attr))
        for attr in ("background", "foreground", "surface")
    )

    primary = _normalize_color(textual_theme.primary, "#0178D4")
    secondary = _normalize_color(textual_theme.secondary, primary)
    accent = _normalize_color(textual_theme.accent, primary)
    warning = _normalize_color(textual_theme.warning, "#ffa62b")
    error = _normalize_color(textual_theme.error, "#ba3c5b")
    success = _normalize_color(textual_theme.success, "#4EBF71")
    foreground = _normalize_color(textual_theme.foreground, "#e0e0e0" if assume_dark else "#1e1e1e")
    background = _normalize_color(textual_theme.background, "#1e1e1e" if assume_dark else "#e0e0e0")
    surface = _normalize_color(textual_theme.surface, "#2b2b2b" if assume_dark else "#d0d0d0")

    code_theme = "github-dark" if dark else "friendly"

    # Search highlight: current match uses accent with inverted fg
    search_current_fg = "#000000" if dark else "#ffffff"
    search_current_style = f"bold {search_current_fg} on {accent}"

    # Markdown theme
    # [LAW:one-source-of-truth] markdown styling defined here
    md_code_style = f"{foreground} on {surface}"
    md_h_dim = "dim italic"

    markdown_theme_dict = {
        "markdown.text": foreground,
        "markdown.paragraph": foreground,
        "markdown.item": foreground,
        "markdown.strong": f"bold {foreground}",
        "markdown.em": f"italic {foreground}",
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
        "markdown.table.border": f"dim {foreground}",
        "markdown.table.header": f"bold {primary}",
        "markdown.hr": f"dim {foreground}",
    }

    filter_colors = cc_dump.palette.generate_filter_colors(
        primary=primary,
        secondary=secondary,
        accent=accent,
        background=background,
        foreground=foreground,
        surface=surface,
    )

    # Action color pool: theme semantic colors for non-filter UI items.
    # Order chosen for visual variety — avoids adjacent similar tones.
    action_colors = [accent, warning, success, error, primary, secondary]

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
        follow_active_style=f"bold {background} on {foreground}",
        follow_engaged_style=f"bold {foreground} on {background}",
        search_prompt_style=f"bold {primary}",
        search_active_style=f"bold {success}",
        search_error_style=f"bold {error}",
        search_keys_style=f"bold {warning}",
        markdown_theme_dict=markdown_theme_dict,
        filter_colors=filter_colors,
        action_colors=action_colors,
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
    global _theme_colors, ROLE_STYLES, TAG_STYLES, MSG_COLORS, FILTER_INDICATORS

    _theme_colors = build_theme_colors(textual_theme)
    tc = _theme_colors

    # Rebuild module-level style vars
    ROLE_STYLES = {
        "user": f"bold {tc.user}",
        "assistant": f"bold {tc.assistant}",
        "system": f"bold {tc.system}",
    }

    p = cc_dump.palette.PALETTE
    TAG_STYLES = [p.fg_on_bg_for_mode(i, tc.dark) for i in range(min(p.count, cc_dump.palette.TAG_COLOR_COUNT))]
    MSG_COLORS = [p.msg_color_for_mode(i, tc.dark) for i in range(6)]
    FILTER_INDICATORS = _build_filter_indicators(tc)


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
# METADATA consolidates former BUDGET, METADATA, and HEADERS categories.
BLOCK_CATEGORY: dict[str, Category | None] = {
    "SeparatorBlock": Category.METADATA,
    "HeaderBlock": Category.METADATA,
    "HttpHeadersBlock": Category.METADATA,
    "MetadataBlock": Category.METADATA,
    "NewSessionBlock": Category.METADATA,
    "TurnBudgetBlock": Category.METADATA,
    "TrackedContentBlock": Category.SYSTEM,
    "ToolUseBlock": Category.TOOLS,
    "ToolResultBlock": Category.TOOLS,
    "ToolUseSummaryBlock": Category.TOOLS,
    "StreamInfoBlock": Category.METADATA,
    "StreamToolUseBlock": Category.TOOLS,
    "StopReasonBlock": Category.METADATA,
    # Hierarchical container blocks
    "ThinkingBlock": Category.THINKING,
    "ConfigContentBlock": None,  # Inherits from parent (USER)
    "HookOutputBlock": None,     # Inherits from parent (USER)
    "MessageBlock": None,        # Context-dependent (USER or ASSISTANT)
    "MetadataSection": Category.METADATA,
    "SystemSection": Category.SYSTEM,
    "ToolDefsSection": Category.TOOLS,
    "ToolDefBlock": Category.TOOLS,
    "SkillDefChild": Category.TOOLS,
    "AgentDefChild": Category.TOOLS,
    "ResponseMetadataSection": Category.METADATA,
    # Context-dependent (use block.category field):
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


def _resolve_visibility(block: FormattedBlock, filters: dict, overrides=None) -> VisState:
    """Determine VisState for a block given current filter state.

    // [LAW:one-source-of-truth] Returns THE visibility representation.
    // [LAW:dataflow-not-control-flow] Value coalescing, not branching.
    // [LAW:single-enforcer] ViewOverrides is the sole source for per-block overrides.

    Filters contain VisState values keyed by category name.
    Runtime force_vis (from overrides) overrides all filters (search mode).
    Per-block expanded (from overrides) overrides category-level expansion.
    Returns ALWAYS_VISIBLE for blocks with no category.
    """
    # Check for runtime override (search mode) — from overrides only
    if overrides is not None:
        bvs = overrides._blocks.get(block.block_id)
        if bvs is not None and bvs.force_vis is not None:
            return bvs.force_vis

    cat = get_category(block)
    if cat is None:
        return ALWAYS_VISIBLE  # always fully visible

    vis = filters.get(cat.value, ALWAYS_VISIBLE)
    # Per-block expanded override — from overrides only
    block_expanded = None
    if overrides is not None:
        bvs = overrides._blocks.get(block.block_id)
        if bvs is not None:
            block_expanded = bvs.expanded
    expanded = block_expanded if block_expanded is not None else vis.expanded

    return VisState(vis.visible, vis.full, expanded)


# ─── Style helpers ─────────────────────────────────────────────────────────────

# Initial values — rebuilt by set_theme()
ROLE_STYLES: dict[str, str] = {}
TAG_STYLES: list[tuple[str, str]] = []
# Default MSG_COLORS to avoid division by zero in tests that don't call set_theme()
MSG_COLORS: list[str] = ["cyan", "magenta", "yellow", "blue", "green", "red"]


def _build_filter_indicators(tc: ThemeColors) -> dict[str, tuple[str, str]]:
    """Build filter indicator (symbol, fg_color) mapping from ThemeColors.

    // [LAW:one-source-of-truth] Filter indicator colors derived from theme via tc.filter_colors.
    // [LAW:single-enforcer] Rebuilt by set_theme() alongside TAG_STYLES/MSG_COLORS.
    """
    # // [LAW:one-source-of-truth] 6 categories matching Category enum.
    names = ["tools", "system", "metadata", "user", "assistant", "thinking"]
    # [LAW:one-source-of-truth] Use chip_bg (element [1]) to match footer chip colors.
    return {name: ("\u258c", tc.filter_colors[name][1]) for name in names}


# Initialized empty — rebuilt by set_theme() before first render.
FILTER_INDICATORS: dict[str, tuple[str, str]] = {}


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


def _render_xml_tag(tag_text: str) -> Text:
    """Render an XML open/close tag with theme-aware styling.

    Parses tag text to style components individually:
    - Arrow indicators (▷/▽): dim secondary
    - Angle brackets and slash: dim foreground
    - Tag name: tc.secondary (role color, theme-derived)
    - Inline content (collapsed preview text): dim italic foreground

    // [LAW:one-source-of-truth] Single function for all XML tag rendering.
    // [LAW:one-type-per-behavior] All XML tags render identically — one function.
    """

    tc = get_theme_colors()
    t = Text()

    pos = 0
    # Extract leading arrow if present
    arrow_match = re.match(r"^([▷▽]\s*)", tag_text)
    if arrow_match:
        t.append(arrow_match.group(1), style=f"dim {tc.secondary}")
        pos = arrow_match.end()

    # Parse remaining: alternating tags and text content
    tag_pattern = re.compile(r"(</?)([\w.-]+)(>)")
    remaining = tag_text[pos:]
    last_end = 0
    bracket_style = f"dim {tc.foreground}"
    name_style = tc.secondary

    for m in tag_pattern.finditer(remaining):
        # Text before this tag (content between tags in collapsed view)
        if m.start() > last_end:
            t.append(remaining[last_end : m.start()], style=f"dim italic {tc.foreground}")
        t.append(m.group(1), style=bracket_style)  # < or </
        t.append(m.group(2), style=name_style)  # tag name
        t.append(m.group(3), style=bracket_style)  # >
        last_end = m.end()

    # Trailing text after last tag
    if last_end < len(remaining):
        t.append(remaining[last_end:], style=f"dim italic {tc.foreground}")

    return t


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


def _render_http_headers_summary_expanded(block: HttpHeadersBlock) -> Text | None:
    """Multi-line summary for HttpHeadersBlock at SUMMARY expanded."""
    tc = get_theme_colors()
    t = Text("  ")
    n = len(block.headers)
    labels = {
        "response": ("HTTP {}".format(block.status_code), f"bold {tc.success}"),
        "request": ("Request Headers", f"bold {tc.info}"),
    }
    label, style = labels.get(block.header_type, ("Headers", "bold"))
    t.append(label, style=style)
    t.append("  ({} header{})".format(n, "s" if n != 1 else ""), style="dim")

    shown = 0
    for key in sorted(block.headers.keys()):
        if shown >= 6:
            break
        value = block.headers[key]
        t.append("\n    {}: ".format(key), style=f"dim {tc.info}")
        t.append(value, style="dim")
        shown += 1

    if n > shown:
        t.append("\n    ")
        t.append("··· {} more headers".format(n - shown), style="dim")
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


def _render_tracked_new(
    block: TrackedContentBlock, tag_style: str
) -> ConsoleRenderable:
    """Render a TrackedContentBlock with status='new'."""
    content_len = len(block.content.splitlines())
    header = Text(block.indent + "  ")
    header.append(" {} ".format(block.tag_id), style=tag_style)
    header.append(" NEW ({} lines):".format(content_len))

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
    old_len = len(block.old_content.splitlines())
    new_len = len(block.new_content.splitlines())
    t = Text(block.indent + "  ")
    t.append(" {} ".format(block.tag_id), style=tag_style)
    t.append(" CHANGED ({} -> {} lines):\n".format(old_len, new_len))
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


def _get_or_segment(block):
    """Lazy segmentation, cached on the block object."""
    if block._segment_result is None:
        block._segment_result = cc_dump.segmentation.segment(block.content)
    return block._segment_result


def _render_text_as_markdown(text: str, seg=None) -> ConsoleRenderable:
    """Render text string as Markdown using SubBlock segmentation.

    // [LAW:dataflow-not-control-flow] Dispatch via cc_dump.segmentation.SubBlockKind match.

    Extracted from _render_segmented_block to enable reuse for TrackedContentBlock.
    Accepts optional pre-computed segmentation to avoid double work.
    """

    tc = get_theme_colors()
    if seg is None:
        seg = cc_dump.segmentation.segment(text)

    # Single SubBlock of kind MD: fast path — just Markdown with tag wrapping
    if len(seg.sub_blocks) == 1 and seg.sub_blocks[0].kind == cc_dump.segmentation.SubBlockKind.MD:
        return Markdown(cc_dump.segmentation.wrap_tags_in_backticks(text), code_theme=tc.code_theme)

    parts: list[ConsoleRenderable] = []
    for sb in seg.sub_blocks:
        text_slice = text[sb.span.start : sb.span.end]

        if sb.kind == cc_dump.segmentation.SubBlockKind.MD:
            wrapped = cc_dump.segmentation.wrap_tags_in_backticks(text_slice)
            if wrapped.strip():
                parts.append(Markdown(wrapped, code_theme=tc.code_theme))

        elif sb.kind == cc_dump.segmentation.SubBlockKind.MD_FENCE:
            inner = text[sb.meta.inner_span.start : sb.meta.inner_span.end]
            wrapped = cc_dump.segmentation.wrap_tags_in_backticks(inner)
            if wrapped.strip():
                parts.append(Markdown(wrapped, code_theme=tc.code_theme))

        elif sb.kind == cc_dump.segmentation.SubBlockKind.CODE_FENCE:
            inner = text[sb.meta.inner_span.start : sb.meta.inner_span.end]
            parts.append(Syntax(inner, sb.meta.info or "", theme=tc.code_theme))

        elif sb.kind == cc_dump.segmentation.SubBlockKind.XML_BLOCK:
            m = sb.meta
            start_tag = text[m.start_tag_span.start : m.start_tag_span.end].rstrip("\n")
            end_tag = text[m.end_tag_span.start : m.end_tag_span.end].rstrip("\n")
            inner = text[m.inner_span.start : m.inner_span.end]
            xml_parts: list[ConsoleRenderable] = [_render_xml_tag(start_tag)]
            if inner.strip():
                xml_parts.append(
                    Markdown(
                        cc_dump.segmentation.wrap_tags_outside_fences(inner),
                        code_theme=tc.code_theme,
                    )
                )
            xml_parts.append(_render_xml_tag(end_tag))
            parts.append(Group(*xml_parts))

    if not parts:
        return Markdown(cc_dump.segmentation.wrap_tags_in_backticks(text), code_theme=tc.code_theme)
    if len(parts) == 1:
        return parts[0]
    return Group(*parts)


def _render_segmented_block(block) -> ConsoleRenderable:
    """Render a text block using SubBlock segmentation.

    // [LAW:dataflow-not-control-flow] Dispatch via cc_dump.segmentation.SubBlockKind match.
    """
    # Use cached segmentation on the block object for efficiency
    seg = _get_or_segment(block)
    return _render_text_as_markdown(block.content, seg=seg)


def _render_xml_collapsed(tag_name: str, inner_text: str) -> ConsoleRenderable:
    """Render a collapsed XML sub-block with content preview.

    // [LAW:one-source-of-truth] _render_xml_tag for all XML tag rendering.
    // [LAW:one-source-of-truth] Collapsed XML arrow is ▷ (summary collapsed).
    """
    preview = inner_text.strip().replace("\n", " ")
    max_len = 60
    if len(preview) > max_len:
        preview = preview[:max_len] + "\u2026"
    return _render_xml_tag(f"▷ <{tag_name}>{preview}</{tag_name}>")


def _render_code_fence_collapsed(info: str | None, inner_text: str) -> Text:
    """Render collapsed code fence as a compact one-line preview."""
    lang = info or "text"
    line_count = len(inner_text.splitlines()) if inner_text else 0
    preview = inner_text.strip().replace("\n", " ")
    if len(preview) > 60:
        preview = preview[:60] + "\u2026"

    t = Text("  ")
    t.append(f"▷ ```{lang}```", style="bold dim")
    if line_count:
        t.append(f" ({line_count} lines)", style="dim")
    if preview:
        t.append(" ")
        t.append(preview, style="dim")
    return t


_CODE_FENCE_DEFAULT_EXPANDED_MAX_LINES = 12


def _code_fence_default_expanded(inner_text: str) -> bool:
    """Default expansion policy for code_fence regions.

    // [LAW:no-mode-explosion] Single threshold controls default collapse behavior.
    """
    return len(inner_text.splitlines()) <= _CODE_FENCE_DEFAULT_EXPANDED_MAX_LINES


def _render_region_parts(
    block, overrides=None,
) -> list[tuple[ConsoleRenderable, int | None]]:
    """Render text into per-part renderables using block.content_regions for state.

    Returns (renderable, region_index) tuples. 1:1 correspondence between
    block.content_regions and seg.sub_blocks — every part gets its region_idx.

    // [LAW:dataflow-not-control-flow] content_regions controls the data;
    // region.expanded=None means expanded (default True).

    Args:
        block: A block with .content and .content_regions already populated
            by populate_content_regions().
        overrides: Optional ViewOverrides for reading region expanded state.

    Returns:
        List of (renderable, region_idx) tuples.
    """

    text = block.content
    regions = block.content_regions

    tc = get_theme_colors()
    seg = _get_or_segment(block)

    parts: list[tuple[ConsoleRenderable, int | None]] = []

    # 1:1 correspondence: regions[i] <-> seg.sub_blocks[i]
    for i, sb in enumerate(seg.sub_blocks):
        region = regions[i] if i < len(regions) else None
        region_idx = region.index if region else None
        text_slice = text[sb.span.start : sb.span.end]

        if sb.kind == cc_dump.segmentation.SubBlockKind.MD:
            wrapped = cc_dump.segmentation.wrap_tags_in_backticks(text_slice)
            if wrapped.strip():
                parts.append((Markdown(wrapped, code_theme=tc.code_theme), region_idx))

        elif sb.kind == cc_dump.segmentation.SubBlockKind.MD_FENCE:
            inner = text[sb.meta.inner_span.start : sb.meta.inner_span.end]
            wrapped = cc_dump.segmentation.wrap_tags_in_backticks(inner)
            if wrapped.strip():
                parts.append((Markdown(wrapped, code_theme=tc.code_theme), region_idx))

        elif sb.kind == cc_dump.segmentation.SubBlockKind.CODE_FENCE:
            inner = text[sb.meta.inner_span.start : sb.meta.inner_span.end]
            # // [LAW:one-source-of-truth] Region expanded state from overrides only.
            region_exp = None
            if overrides is not None and region is not None:
                rvs = overrides._regions.get((block.block_id, region.index))
                if rvs is not None:
                    region_exp = rvs.expanded
            default_expanded = _code_fence_default_expanded(inner)
            is_expanded = default_expanded if region_exp is None else (region_exp is not False)

            if is_expanded:
                parts.append(
                    (
                        Syntax(inner, sb.meta.info or "", theme=tc.code_theme),
                        region_idx,
                    )
                )
            else:
                parts.append(
                    (
                        _render_code_fence_collapsed(sb.meta.info, inner),
                        region_idx,
                    )
                )

        elif sb.kind == cc_dump.segmentation.SubBlockKind.XML_BLOCK:
            # expanded=None or True means expanded; False means collapsed
            # // [LAW:one-source-of-truth] Read from overrides only
            region_exp = None
            if overrides is not None and region is not None:
                rvs = overrides._regions.get((block.block_id, region.index))
                if rvs is not None:
                    region_exp = rvs.expanded
            is_expanded = region_exp is not False

            m = sb.meta
            inner = text[m.inner_span.start : m.inner_span.end]

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
                            cc_dump.segmentation.wrap_tags_outside_fences(inner),
                            code_theme=tc.code_theme,
                        )
                    )
                xml_parts_with_header.append(_render_xml_tag(end_tag))
                parts.append((Group(*xml_parts_with_header), region_idx))
            else:
                # Collapsed: content preview indicator
                collapsed = _render_xml_collapsed(m.tag_name, inner)
                parts.append((collapsed, region_idx))

    if not parts:
        # Fallback: render as plain markdown
        md = _render_text_as_markdown(text)
        return [(md, None)]

    return parts


def _render_text_content(block: TextContentBlock) -> ConsoleRenderable | None:
    if not block.content:
        return None
    # Render as segmented Markdown for USER and ASSISTANT categories
    if block.category in _MARKDOWN_CATEGORIES:
        return _render_segmented_block(block)
    return _indent_text(block.content, block.indent)


def _preview_line(text: str, max_chars: int = 100) -> str:
    """Return a single-line preview with normalized whitespace."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[: max_chars - 1] + "…"


def _line_count(text: str) -> int:
    """Return human-readable line count for content previews."""
    return len(text.splitlines()) if text else 0


def _render_text_summary_collapsed(block: TextContentBlock) -> ConsoleRenderable | None:
    """Summary-collapsed text renderer: one-line glanceable preview.

    // [LAW:dataflow-not-control-flow] Summary is derived from content value only.
    """
    if not block.content:
        return None
    lines = _line_count(block.content)
    preview = _preview_line(block.content, max_chars=110)
    t = Text("  ")
    t.append(preview)
    if lines > 1:
        t.append(f"  ({lines} lines)", style="dim")
    return t


def _render_text_summary_expanded(block: TextContentBlock) -> ConsoleRenderable | None:
    """Summary-expanded text renderer: bounded preview with explicit remainder.

    Distinct from full-expanded to preserve progressive disclosure semantics.
    """
    if not block.content:
        return None

    lines = block.content.splitlines()
    preview_limit = 18
    if len(lines) <= preview_limit:
        return _render_text_content(block)

    head = "\n".join(lines[:preview_limit])
    hidden = len(lines) - preview_limit

    if block.category in _MARKDOWN_CATEGORIES:
        preview = _render_text_as_markdown(head)
    else:
        preview = _indent_text(head, block.indent)

    tail = Text()
    tail.append(f"    ··· {hidden} more lines", style="dim")
    return Group(preview, tail)


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
    t.append(" ({} lines)".format(block.size))
    return t


def _append_special_marker_badges(t: Text, block: FormattedBlock) -> None:
    """Append compact special-content badges for renderer highlighting.

    // [LAW:one-source-of-truth] Marker classification lives in special_content.
    """
    for marker in cc_dump.special_content.display_markers_for_block(block):
        t.append(f" [{marker.label}]", style="bold dim")


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
    _append_special_marker_badges(t, block)
    t.append(" ({} lines)".format(block.input_size))
    return t


def _render_tool_use_summary_collapsed(block: ToolUseBlock) -> Text | None:
    """Summary-collapsed ToolUse renderer: compact call identity only."""
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    t = Text("  ")
    t.append("[Use: {}]".format(block.name), style="bold {}".format(color))
    _append_special_marker_badges(t, block)
    return t


def _render_tool_use_summary_expanded(block: ToolUseBlock) -> ConsoleRenderable | None:
    """Summary-expanded ToolUse renderer: detail + optional description preview."""
    base = _render_tool_use_oneliner(block)
    if not block.description or base is None:
        return base
    desc_line = block.description.split("\n", 1)[0]
    if len(desc_line) > 120:
        desc_line = desc_line[:117] + "..."
    desc_text = Text("    ")
    desc_text.append(desc_line, style="dim italic")
    return Group(base, desc_text)


def _render_tool_use_bash_full(block: ToolUseBlock) -> ConsoleRenderable | None:
    """Full ToolUseBlock for Bash: header + $ command with syntax highlighting.

    // [LAW:dataflow-not-control-flow] Dispatch via _TOOL_USE_FULL_RENDERERS table.
    """
    tc = get_theme_colors()
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    header = Text("  ")
    header.append("[Use: Bash]", style="bold {}".format(color))
    _append_special_marker_badges(header, block)
    header.append(" ({} lines)".format(block.input_size))

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
    _append_special_marker_badges(t, block)
    t.append(" ({} lines)".format(block.input_size))

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


def _render_tool_use_read_full(block: ToolUseBlock) -> Text | None:
    """Full ToolUseBlock for Read: path + range hints."""
    tc = get_theme_colors()
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    t = Text("  ")
    t.append("[Use: Read]", style=f"bold {color}")
    if block.detail:
        t.append(f" {block.detail}", style="dim")
    _append_special_marker_badges(t, block)
    t.append(f" ({block.input_size} lines)")

    file_path = str(block.tool_input.get("file_path", "") or "")
    offset = block.tool_input.get("offset")
    limit = block.tool_input.get("limit")
    if file_path:
        t.append("\n    ")
        t.append(file_path, style=tc.secondary)
    if offset is not None or limit is not None:
        t.append("\n    ")
        t.append(
            "offset={} limit={}".format(offset if offset is not None else 0, limit if limit is not None else "all"),
            style="dim",
        )
    return t


def _render_tool_use_write_full(block: ToolUseBlock) -> Text | None:
    """Full ToolUseBlock for Write: path + payload preview."""
    tc = get_theme_colors()
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    t = Text("  ")
    t.append("[Use: Write]", style=f"bold {color}")
    if block.detail:
        t.append(f" {block.detail}", style="dim")
    _append_special_marker_badges(t, block)
    t.append(f" ({block.input_size} lines)")

    content = str(block.tool_input.get("content", "") or "")
    if content:
        first = content.splitlines()[0] if content.splitlines() else content
        preview = first[:80] + ("..." if len(first) > 80 else "")
        line_count = content.count("\n") + 1
        t.append("\n    ")
        t.append(f"+ payload ({line_count} lines): ", style=tc.success)
        t.append(preview, style="dim")
    return t


def _render_tool_use_grep_full(block: ToolUseBlock) -> Text | None:
    """Full ToolUseBlock for Grep: show regex pattern and path scope."""
    tc = get_theme_colors()
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    t = Text("  ")
    t.append("[Use: Grep]", style=f"bold {color}")
    if block.detail:
        t.append(f" {block.detail}", style="dim")
    _append_special_marker_badges(t, block)
    t.append(f" ({block.input_size} lines)")

    pattern = str(block.tool_input.get("pattern", "") or "")
    path = str(block.tool_input.get("path", "") or "")
    if pattern:
        t.append("\n    ")
        t.append(f"/{pattern}/", style=f"bold {tc.accent}")
    if path:
        t.append("\n    ")
        t.append(path, style=tc.secondary)
    return t


def _render_tool_use_glob_full(block: ToolUseBlock) -> Text | None:
    """Full ToolUseBlock for Glob: show glob pattern and search root."""
    tc = get_theme_colors()
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    t = Text("  ")
    t.append("[Use: Glob]", style=f"bold {color}")
    if block.detail:
        t.append(f" {block.detail}", style="dim")
    _append_special_marker_badges(t, block)
    t.append(f" ({block.input_size} lines)")

    pattern = str(block.tool_input.get("pattern", "") or "")
    path = str(block.tool_input.get("path", "") or "")
    if pattern:
        t.append("\n    ")
        t.append(pattern, style=tc.secondary)
    if path:
        t.append("\n    ")
        t.append(path, style="dim")
    return t


# [LAW:dataflow-not-control-flow] Tool-specific full renderers for ToolUseBlock
_TOOL_USE_FULL_RENDERERS: dict[str, Callable] = {
    "Bash": _render_tool_use_bash_full,
    "Edit": _render_tool_use_edit_full,
    "Read": _render_tool_use_read_full,
    "Write": _render_tool_use_write_full,
    "Grep": _render_tool_use_grep_full,
    "Glob": _render_tool_use_glob_full,
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


# ─── ToolDefBlock renderers ───────────────────────────────────────────────────


def _render_tool_def_header(name: str, tokens: int) -> Text:
    """Render aligned tool name + token count header."""
    t = Text("  ")
    t.append(f"{name:<18}", style="bold")
    if tokens > 0:
        t.append(f"{_fmt_tokens(tokens)} tokens", style="dim")
    return t


def _render_tool_def_summary_collapsed(block: FormattedBlock) -> ConsoleRenderable | None:
    """SUMMARY collapsed: aligned name + token count."""
    name = getattr(block, "name", "")
    tokens = getattr(block, "token_estimate", 0)
    return _render_tool_def_header(name, tokens)


def _render_tool_def_summary_expanded(block: FormattedBlock) -> ConsoleRenderable | None:
    """SUMMARY expanded: header + one-line description preview."""
    header = _render_tool_def_summary_collapsed(block)
    if header is None:
        return None
    description = getattr(block, "description", "")
    if not description:
        return header
    first_line = description.split("\n", 1)[0]
    if len(first_line) > 80:
        first_line = first_line[:77] + "..."
    preview = Text("    ")
    preview.append(first_line, style="dim italic")
    return Group(header, preview)


def _render_tool_def_full_collapsed(block: FormattedBlock) -> ConsoleRenderable | None:
    """FULL collapsed: same compact header as summary collapsed."""
    return _render_tool_def_summary_collapsed(block)


# ─── ToolResultBlock renderers ─────────────────────────────────────────────────


def _render_tool_result_summary(block: ToolResultBlock) -> Text | None:
    """Summary ToolResultBlock: header only, no content.

    // [LAW:dataflow-not-control-flow] Registered in BLOCK_STATE_RENDERERS.
    """
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    return _tool_result_header(block, color)


def _render_tool_result_summary_collapsed(block: ToolResultBlock) -> Text | None:
    """Summary-collapsed ToolResult renderer: minimal result signal."""
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    t = Text("  ")
    suffix = " ERROR" if block.is_error else ""
    t.append("[Result{}]".format(suffix), style="bold {}".format(color))
    if block.size:
        t.append(" ({} lines)".format(block.size), style="dim")
    return t


def _render_tool_result_summary_expanded(block: ToolResultBlock) -> ConsoleRenderable | None:
    """Summary-expanded ToolResult renderer: header + one-line content preview."""
    header = _render_tool_result_summary(block)
    if header is None:
        return None
    if not block.content:
        return header
    preview = _preview_line(block.content, max_chars=120)
    body = Text("    ")
    body.append(preview, style="dim")
    return Group(header, body)


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


def _render_bash_result_content(block: ToolResultBlock) -> ConsoleRenderable | None:
    """Render Bash result with explicit success/error semantics and readable output body."""
    tc = get_theme_colors()
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    header = _tool_result_header(block, color)

    if not block.content:
        return header

    header.append("\n")
    header.append(block.content, style=tc.error if block.is_error else tc.foreground)
    return header


def _grep_highlight_text(content: str, pattern: str, highlight_style: str) -> Text:
    """Highlight grep matches with resilient regex fallback."""
    if not pattern:
        return Text(content)

    try:
        compiled = re.compile(pattern)
    except re.error:
        compiled = re.compile(re.escape(pattern))

    result = Text()
    pos = 0
    for match in compiled.finditer(content):
        start, end = match.span()
        if start > pos:
            result.append(content[pos:start])
        result.append(content[start:end], style=highlight_style)
        pos = end
    if pos < len(content):
        result.append(content[pos:])
    return result


def _render_grep_result_content(block: ToolResultBlock) -> ConsoleRenderable | None:
    """Render Grep result with highlighted matched pattern."""
    tc = get_theme_colors()
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    header = _tool_result_header(block, color)

    if not block.content:
        return header

    pattern = str(block.tool_input.get("pattern", "") or "")
    highlighted = _grep_highlight_text(block.content, pattern, f"bold {tc.accent}")
    header.append("\n")
    header.append_text(highlighted)
    return header


def _render_glob_result_content(block: ToolResultBlock) -> ConsoleRenderable | None:
    """Render Glob result as path list with stable line formatting."""
    tc = get_theme_colors()
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    header = _tool_result_header(block, color)

    if not block.content:
        return header

    lines = [line for line in block.content.splitlines() if line.strip()]
    if not lines:
        return header

    body = Text()
    for i, line in enumerate(lines):
        if i > 0:
            body.append("\n")
        body.append(line, style=tc.secondary)
    header.append("\n")
    header.append_text(body)
    return header


# [LAW:dataflow-not-control-flow] Tool-specific content renderers for ToolResultBlock
_TOOL_RESULT_CONTENT_RENDERERS: dict[str, Callable] = {
    "Read": _render_read_content,
    "Write": _render_confirm_content,
    "Edit": _render_confirm_content,
    "Bash": _render_bash_result_content,
    "Grep": _render_grep_result_content,
    "Glob": _render_glob_result_content,
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
    return Text(block.content)


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
    t.append("{} tokens".format(_fmt_tokens(total)))
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
    t.append(" NEW ({} lines)".format(len(block.content.splitlines())))
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
        " CHANGED ({} -> {} lines)".format(
            len(block.old_content.splitlines()), len(block.new_content.splitlines())
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
    t.append("{} tokens".format(_fmt_tokens(b.total_est)))
    return t


# ─── Hierarchical block renderers (Phase 2 stubs) ─────────────────────────────
# // [LAW:dataflow-not-control-flow] Stubs render placeholder content;
# container expansion logic will be added in Phase 4.


def _render_thinking(block: FormattedBlock) -> ConsoleRenderable | None:
    """Render thinking block — full content with dim italic style."""
    t = Text()
    t.append("[thinking] ", style="bold dim")
    content = getattr(block, "content", "")
    if content:
        t.append(content, style="dim italic")
    return t


def _render_thinking_summary(block: FormattedBlock) -> ConsoleRenderable | None:
    """Render thinking block summary — line count only."""
    content = getattr(block, "content", "")
    line_count = len(content.splitlines()) if content else 0
    t = Text()
    t.append("[thinking]", style="bold dim")
    t.append(f" ({line_count} lines)", style="dim")
    return t


def _render_config_content(block: FormattedBlock) -> ConsoleRenderable | None:
    """Render config content block — full content with source label."""
    source = getattr(block, "source", "unknown")
    content = getattr(block, "content", "")
    header = Text()
    header.append(f"[config: {source}]", style="bold dim")
    _append_special_marker_badges(header, block)
    if not content:
        return header
    return Group(header, _render_text_as_markdown(content))


def _render_config_content_summary(block: FormattedBlock) -> ConsoleRenderable | None:
    """Render config content block summary — source and line count."""
    source = getattr(block, "source", "unknown")
    content = getattr(block, "content", "")
    line_count = len(content.splitlines()) if content else 0
    t = Text()
    t.append(f"[config: {source}]", style="bold dim")
    _append_special_marker_badges(t, block)
    if line_count:
        t.append(f" ({line_count} lines)", style="dim")
        t.append(" ", style="dim")
        t.append(_preview_line(content, max_chars=80), style="dim")
    return t


def _render_hook_output(block: FormattedBlock) -> ConsoleRenderable | None:
    """Render hook output block — full content with hook name."""
    hook_name = getattr(block, "hook_name", "")
    content = getattr(block, "content", "")
    header = Text()
    header.append(f"[hook: {hook_name}]", style="bold dim")
    _append_special_marker_badges(header, block)
    if not content:
        return header
    return Group(header, _render_text_as_markdown(content))


def _render_hook_output_summary(block: FormattedBlock) -> ConsoleRenderable | None:
    """Render hook output block summary — hook name and line count."""
    hook_name = getattr(block, "hook_name", "")
    content = getattr(block, "content", "")
    line_count = len(content.splitlines()) if content else 0
    t = Text()
    t.append(f"[hook: {hook_name}]", style="bold dim")
    _append_special_marker_badges(t, block)
    if line_count:
        t.append(f" ({line_count} lines)", style="dim")
        t.append(" ", style="dim")
        t.append(_preview_line(content, max_chars=80), style="dim")
    return t


def _render_message_block(block: FormattedBlock) -> ConsoleRenderable | None:
    """Render message container header (replaces RoleBlock rendering)."""
    tc = get_theme_colors()
    role = getattr(block, "role", "")
    idx = getattr(block, "msg_index", 0)
    timestamp = getattr(block, "timestamp", "")
    role_lower = role.lower()
    style = ROLE_STYLES.get(role_lower, "bold magenta")
    label = role.upper().replace("_", " ")
    t = Text(f"{label} [{idx}]", style=style)
    if timestamp:
        t.append(f"  {timestamp}", style="dim")

    agent_kind = getattr(block, "agent_kind", "") or "main"
    agent_label = getattr(block, "agent_label", "")
    if agent_label:
        badge_styles = {
            "main": f"bold {tc.foreground} on {tc.background}",
            "subagent": f"bold {tc.background} on {tc.accent}",
            "unknown": f"bold {tc.background} on {tc.warning}",
        }
        badge_style = badge_styles.get(agent_kind, badge_styles["unknown"])
        t.append(f" [{agent_label}]", style=badge_style)
        # Subagent/unknown turns get a subtle header tint to stay visually distinct.
        # // [LAW:dataflow-not-control-flow] Tint selection is table-driven by agent_kind.
        tint_by_kind = {
            "main": None,
            "subagent": tc.surface,
            "unknown": tc.surface,
        }
        tint = tint_by_kind.get(agent_kind)
        if tint:
            t.stylize(f"on {tint}", 0, len(t))
    return t


def _render_metadata_section(block: FormattedBlock) -> ConsoleRenderable | None:
    """Render metadata section container header."""
    return Text("METADATA", style="bold dim")


def _render_system_section(block: FormattedBlock) -> ConsoleRenderable | None:
    """Render system section container header."""
    return Text("SYSTEM", style="bold dim")


def _render_tool_defs_section(block: FormattedBlock) -> ConsoleRenderable | None:
    """Render tool defs section container header."""
    count = getattr(block, "tool_count", 0)
    tokens = getattr(block, "total_tokens", 0)
    t = Text()
    t.append(f"{count} tools", style="bold dim")
    _append_special_marker_badges(t, block)
    if tokens:
        t.append(f" / {_fmt_tokens(tokens)} tokens", style="dim")
    return t


def _render_tool_def(block: FormattedBlock) -> ConsoleRenderable | None:
    """Render individual tool definition with schema details."""
    name = getattr(block, "name", "")
    tokens = getattr(block, "token_estimate", 0)
    description = getattr(block, "description", "")
    input_schema = getattr(block, "input_schema", {})

    header = _render_tool_def_header(name, tokens)
    lines: list[ConsoleRenderable] = [header]

    if description:
        desc = Text("    ")
        desc.append(description, style="dim italic")
        lines.append(desc)

    properties = {}
    if isinstance(input_schema, dict):
        raw_properties = input_schema.get("properties", {})
        properties = raw_properties if isinstance(raw_properties, dict) else {}
        raw_required = input_schema.get("required", [])
        required = {
            item
            for item in raw_required
            if isinstance(item, str)
        } if isinstance(raw_required, list) else set()
    else:
        required = set()

    if properties:
        params = Text("    parameters:", style="dim")
        lines.append(params)
        for pname, pinfo in properties.items():
            ptype = ""
            if isinstance(pinfo, dict):
                raw_type = pinfo.get("type", "")
                if isinstance(raw_type, str):
                    ptype = raw_type
            req_marker = "*" if pname in required else ""
            row = Text("      ")
            row.append(f"{pname}{req_marker}", style="bold dim")
            if ptype:
                row.append(f": {ptype}", style="dim")
            lines.append(row)

    if len(lines) == 1:
        return header
    return Group(*lines)


def _render_named_def_child(block: FormattedBlock) -> ConsoleRenderable | None:
    """Render a named definition child (skills, agents, and similar)."""
    name = getattr(block, "name", "")
    desc = getattr(block, "description", "")
    t = Text()
    t.append(name, style="bold")
    if desc:
        preview = desc[:60] + "..." if len(desc) > 60 else desc
        t.append(f' — "{preview}"', style="dim")
    return t


def _render_response_metadata_section(block: FormattedBlock) -> ConsoleRenderable | None:
    """Render response metadata section container header."""
    return Text("RESPONSE METADATA", style="bold dim")



# ─── Registries ────────────────────────────────────────────────────────────────

# Full content renderers. Signature: (block) -> ConsoleRenderable | None
BLOCK_RENDERERS: dict[str, Callable[[FormattedBlock], ConsoleRenderable | None]] = {
    "SeparatorBlock": _render_separator,
    "HeaderBlock": _render_header,
    "HttpHeadersBlock": _render_http_headers,
    "MetadataBlock": _render_metadata,
    "NewSessionBlock": _render_new_session,
    "TurnBudgetBlock": _render_turn_budget,
    "TrackedContentBlock": _render_tracked_content_full,
    "TextContentBlock": _render_text_content,
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
    # Hierarchical block renderers
    "ThinkingBlock": _render_thinking,
    "ConfigContentBlock": _render_config_content,
    "HookOutputBlock": _render_hook_output,
    "MessageBlock": _render_message_block,
    "MetadataSection": _render_metadata_section,
    "SystemSection": _render_system_section,
    "ToolDefsSection": _render_tool_defs_section,
    "ToolDefBlock": _render_tool_def,
    # [LAW:one-type-per-behavior] SkillDefChild and AgentDefChild share one renderer.
    "SkillDefChild": _render_named_def_child,
    "AgentDefChild": _render_named_def_child,
    "ResponseMetadataSection": _render_response_metadata_section,
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
    ("HttpHeadersBlock", True, False, True): _render_http_headers_summary_expanded,
    # TurnBudgetBlock: oneliner at summary level
    ("TurnBudgetBlock", True, False, False): _render_turn_budget_oneliner,
    ("TurnBudgetBlock", True, False, True): _render_turn_budget_oneliner,
    # TextContentBlock: dedicated summary renderers (full states use default render path)
    ("TextContentBlock", True, False, False): _render_text_summary_collapsed,
    ("TextContentBlock", True, False, True): _render_text_summary_expanded,
    # ToolResultBlock: summary states + header-only at full collapsed
    ("ToolResultBlock", True, False, False): _render_tool_result_summary_collapsed,
    ("ToolResultBlock", True, False, True): _render_tool_result_summary_expanded,
    ("ToolResultBlock", True, True, False): _render_tool_result_summary,
    # ToolUseBlock: summary states + description at full expanded
    ("ToolUseBlock", True, False, False): _render_tool_use_summary_collapsed,
    ("ToolUseBlock", True, False, True): _render_tool_use_summary_expanded,
    ("ToolUseBlock", True, True, True): _render_tool_use_full_with_desc,
    # ToolDefBlock: custom compact summary/collapsed output, full-expanded via default renderer
    ("ToolDefBlock", True, False, False): _render_tool_def_summary_collapsed,
    ("ToolDefBlock", True, False, True): _render_tool_def_summary_expanded,
    ("ToolDefBlock", True, True, False): _render_tool_def_full_collapsed,
    # ThinkingBlock: summary at both summary levels
    ("ThinkingBlock", True, False, False): _render_thinking_summary,
    ("ThinkingBlock", True, False, True): _render_thinking_summary,
    # ConfigContentBlock: summary at summary levels
    ("ConfigContentBlock", True, False, False): _render_config_content_summary,
    ("ConfigContentBlock", True, False, True): _render_config_content_summary,
    # HookOutputBlock: summary at summary levels
    ("HookOutputBlock", True, False, False): _render_hook_output_summary,
    ("HookOutputBlock", True, False, True): _render_hook_output_summary,
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



# ─── Truncation and collapse indicator ─────────────────────────────────────────


def _make_collapse_indicator(hidden_lines: int, content_width: int):
    """Create a dim '... N more lines' strip at content width (gutter added separately)."""

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
    # Intentionally empty for now: tool defs are represented by ToolDefBlock instances.
}


# ─── Recursive tree rendering context ─────────────────────────────────────────


@dataclass
class _RenderContext:
    """Bundles accumulators for recursive block tree rendering.

    // [LAW:no-shared-mutable-globals] All mutable state is scoped to one render pass.
    """

    all_strips: list
    flat_blocks: list
    block_strip_map: dict
    console: object
    render_options: object
    render_width: int
    width: int
    block_cache: object
    is_streaming: bool
    search_ctx: object
    turn_index: int
    show_right: bool
    filters: dict
    overrides: object = None  # ViewOverrides | None — dual-read/write
    last_rendered_indicator: str | None = None


def _block_cache(ctx: _RenderContext) -> MutableMapping[tuple[object, ...], object] | None:
    """Return typed cache view for mypy while preserving runtime cache implementation."""
    # // [LAW:locality-or-seam] Type seam around generic cache to avoid widening renderer types.
    return cast(MutableMapping[tuple[object, ...], object] | None, ctx.block_cache)


_STRUCTURAL_EMPTY_BLOCK_TYPES = frozenset(
    {
        "NewlineBlock",
    }
)


def _strip_has_visible_text(strip: Strip) -> bool:
    """Whether a strip contains non-whitespace text."""
    return "".join(seg.text for seg in strip).strip() != ""


def _block_has_visible_text(block_strips: list[Strip]) -> bool:
    """Whether any strip line has non-whitespace text."""
    return any(_strip_has_visible_text(strip) for strip in block_strips)


def _hide_empty_leaf_blocks(block: FormattedBlock, block_strips: list[Strip]) -> bool:
    """Drop empty leaf blocks from rendered output.

    // [LAW:behavior-not-structure] Decision is based on rendered content only.
    // [LAW:locality-or-seam] Rendering-only transform; formatting IR is untouched.
    """
    type_name = type(block).__name__
    if type_name in _STRUCTURAL_EMPTY_BLOCK_TYPES:
        return True
    if getattr(block, "children", None):
        return True
    return _block_has_visible_text(block_strips)


# // [LAW:single-enforcer] Render-stage block filtering lives in one transform chain.
_BLOCK_EMIT_TRANSFORMS: tuple[Callable[[FormattedBlock, list[Strip]], bool], ...] = (
    _hide_empty_leaf_blocks,
)


def _should_render_block(block: FormattedBlock, block_strips: list[Strip]) -> bool:
    """Apply render-stage block transforms."""
    return all(transform(block, block_strips) for transform in _BLOCK_EMIT_TRANSFORMS)


def _coalesce_consecutive_same_category(
    block: FormattedBlock, indicator_name: str | None, ctx: _RenderContext
) -> bool:
    """Mark block as a continuation when category matches previous rendered block.

    // [LAW:one-type-per-behavior] Generic category-based grouping, no role/type special-casing.
    """
    _ = block
    if not indicator_name:
        return False
    return ctx.last_rendered_indicator == indicator_name


# // [LAW:single-enforcer] Coalescing policy is declared in one transform chain.
_BLOCK_TRANSFORMS: tuple[
    Callable[[FormattedBlock, str | None, _RenderContext], bool],
    ...,
] = (
    _coalesce_consecutive_same_category,
)


def _is_coalesced_continuation(
    block: FormattedBlock, indicator_name: str | None, ctx: _RenderContext
) -> bool:
    """Apply coalescing transforms for this block render step."""
    return any(transform(block, indicator_name, ctx) for transform in _BLOCK_TRANSFORMS)


def _collapse_children(
    children: list[FormattedBlock], tools_on: bool, overrides=None,
) -> list[FormattedBlock]:
    """Return new list with consecutive ToolUse/ToolResult runs collapsed.

    Non-mutating — original children list preserved for search indexing.
    Returns blocks directly (no index tuples) since indices are managed
    by the tree walker.

    // [LAW:dataflow-not-control-flow] tools_on is a value; both paths always run.
    """
    if tools_on:
        return list(children)

    _tool_types = {"ToolUseBlock", "ToolResultBlock"}
    result: list[FormattedBlock] = []
    pending: list[FormattedBlock] = []

    def _has_force_vis(b):
        # // [LAW:one-source-of-truth] force_vis from overrides only
        if overrides is not None:
            bvs = overrides._blocks.get(b.block_id)
            if bvs is not None and bvs.force_vis is not None:
                return True
        return False

    def flush():
        if not pending:
            return
        # Blocks with search overrides are emitted individually
        if any(_has_force_vis(b) for b in pending):
            result.extend(pending)
            pending.clear()
            return
        use_blocks = [b for b in pending if type(b).__name__ == "ToolUseBlock"]
        # Orphaned ToolResultBlocks without a preceding ToolUseBlock are dropped
        if not use_blocks:
            pending.clear()
            return
        counts = Counter(b.name for b in use_blocks)
        result.append(
            ToolUseSummaryBlock(
                tool_counts=dict(counts),
                total=len(use_blocks),
            )
        )
        pending.clear()

    for block in children:
        if type(block).__name__ in _tool_types:
            pending.append(block)
        else:
            flush()
            result.append(block)

    flush()
    return result


def _render_block_tree(block: FormattedBlock, ctx: _RenderContext) -> None:
    """Recursively render a block and its children into ctx accumulators.

    For each block:
    1. Resolve visibility — skip if hidden (max_lines == 0)
    2. Render block's own content (renderer dispatch, cache, search, regions)
    3. Compute _expandable (has children OR different expanded renderer OR exceeds limit)
    4. Apply truncation, add gutter
    5. Record in ctx.block_strip_map/flat_blocks using sequential key
    6. If block has expanded children: collapse them, recurse

    // [LAW:single-enforcer] All visibility logic in this function.
    // [LAW:dataflow-not-control-flow] Same operations every call; values decide outcomes.
    """

    vis = _resolve_visibility(block, ctx.filters, overrides=ctx.overrides)
    max_lines = TRUNCATION_LIMITS[vis]

    # Hidden blocks produce 0 lines
    if max_lines == 0:
        return

    type_name = type(block).__name__
    children = getattr(block, "children", None) or []

    # Check if this block has search matches
    block_has_matches = False
    search_hash = None
    if ctx.search_ctx is not None:
        # Use identity-based matching (block= kwarg)
        block_matches = ctx.search_ctx.matches_in_block(
            ctx.turn_index, 0, block=block
        )
        block_has_matches = bool(block_matches)
        search_hash = ctx.search_ctx.pattern_str if block_has_matches else None

    # Resolve category indicator name
    indicator_name = _category_indicator_name(block)

    # Single unified renderer lookup
    # // [LAW:dataflow-not-control-flow] One lookup replaces conditional dispatch
    state_key = (type_name, vis.visible, vis.full, vis.expanded)
    renderer = RENDERERS.get(state_key)
    state_override = state_key in BLOCK_STATE_RENDERERS

    # Detect blocks with content regions for per-part rendering
    has_regions = bool(block.content_regions)

    # Precedence: state-specific renderer > region rendering > default renderer
    if has_regions and not state_override:
        region_renderer = _REGION_PART_RENDERERS.get(type_name, _render_region_parts)
        region_parts = region_renderer(block, overrides=ctx.overrides)

        # Region cache state — read from overrides first, fallback to region field
        def _region_expanded(r):
            # // [LAW:one-source-of-truth] Region expanded from overrides only
            if ctx.overrides is not None:
                rvs = ctx.overrides._regions.get((block.block_id, r.index))
                if rvs is not None:
                    return rvs.expanded
            return None  # default: expanded
        region_cache_state = tuple(
            (r.index, _region_expanded(r)) for r in block.content_regions
        )
        cache_key = (
            block.block_id,
            ctx.render_width,
            vis,
            search_hash,
            region_cache_state,
        )

        cache = _block_cache(ctx)
        if cache is not None and cache_key in cache:
            cached_block = cache[cache_key]
            block_strips = cached_block if isinstance(cached_block, list) else []
        else:
            block_strips = []

            for part_renderable, region_idx in region_parts:
                part_start = len(block_strips)
                part_segments = ctx.console.render(
                    part_renderable, ctx.render_options
                )
                part_lines = list(Segment.split_lines(part_segments))
                if part_lines:
                    part_strips = [
                        s.adjust_cell_length(ctx.render_width)
                        for s in Strip.from_lines(part_lines)
                    ]
                    block_strips.extend(part_strips)

                if region_idx is not None:
                    region = block.content_regions[region_idx]
                    # // [LAW:one-source-of-truth] strip_range in ViewOverrides only
                    strip_range = (part_start, len(block_strips))
                    if ctx.overrides is not None:
                        ctx.overrides.get_region(block.block_id, region_idx).strip_range = strip_range
                    if (
                        region.kind in COLLAPSIBLE_REGION_KINDS
                        and part_start < len(block_strips)
                    ):
                        region_meta = {META_TOGGLE_REGION: region_idx}
                        block_strips[part_start] = block_strips[
                            part_start
                        ].apply_meta(region_meta)
                        last_i = len(block_strips) - 1
                        if last_i != part_start:
                            block_strips[last_i] = block_strips[
                                last_i
                            ].apply_meta(region_meta)

            if cache is not None:
                cache[cache_key] = block_strips

        text = True  # sentinel — we already have block_strips

    elif renderer:
        if block_has_matches and isinstance(renderer(block), Markdown):
            plain_text = ""
            if hasattr(block, "content"):
                plain_text = block.content
            text = Text(plain_text)
        else:
            text = renderer(block)
    else:
        text = None

    if text is None:
        return

    # Apply search highlights (only on Text objects)
    if block_has_matches and isinstance(text, Text):
        _apply_search_highlights(
            text, ctx.search_ctx, ctx.turn_index, 0, block=block
        )

    # Standard rendering path (non-region)
    if not has_regions:
        cache_key = (
            block.block_id,
            ctx.render_width,
            vis,
            search_hash,
        )

        cache = _block_cache(ctx)
        if cache is not None and cache_key in cache:
            cached = cache[cache_key]
            if isinstance(cached, tuple):
                block_strips = cached[0]
            else:
                block_strips = cached
        else:
            segments = ctx.console.render(text, ctx.render_options)
            lines = list(Segment.split_lines(segments))
            if lines:
                block_strips = [
                    s.adjust_cell_length(ctx.render_width)
                    for s in Strip.from_lines(lines)
                ]
            else:
                block_strips = []

            if cache is not None:
                cache[cache_key] = block_strips

    # Track expandability: children make a block expandable, as does
    # having a different expanded renderer or exceeding truncation limit
    # // [LAW:single-enforcer] _expandable enables click-to-expand interaction
    collapsed_limit = TRUNCATION_LIMITS[VisState(True, vis.full, False)]
    collapsed_key = (type_name, vis.visible, vis.full, False)
    expanded_key = (type_name, vis.visible, vis.full, True)
    has_different_expanded = RENDERERS.get(collapsed_key) is not RENDERERS.get(
        expanded_key
    )
    is_expandable = bool(children) or has_different_expanded or (
        collapsed_limit is not None
        and collapsed_limit > 0
        and len(block_strips) > collapsed_limit
    )
    # // [LAW:one-source-of-truth] Expandable state in ViewOverrides only
    if ctx.overrides is not None:
        ctx.overrides.get_block(block.block_id).expandable = is_expandable

    # Truncation
    # // [LAW:dataflow-not-control-flow] No should_truncate flag, just max_lines value
    is_truncated = (
        not ctx.is_streaming
        and max_lines is not None
        and len(block_strips) > max_lines
    )

    if is_truncated:
        assert max_lines is not None
        hidden = len(block_strips) - max_lines
        truncated_strips = list(block_strips[:max_lines])
        truncated_strips.append(
            _make_collapse_indicator(hidden, ctx.render_width)
        )
        block_strips_for_gutter = truncated_strips
        arrow = (
            GUTTER_ARROWS.get((vis.full, False), "")
            if is_expandable
            else ""
        )
    else:
        block_strips_for_gutter = list(block_strips)
        arrow = (
            GUTTER_ARROWS.get((vis.full, vis.expanded), "")
            if is_expandable
            else ""
        )
    if _is_coalesced_continuation(block, indicator_name, ctx):
        arrow = ""

    if _should_render_block(block, block_strips_for_gutter):
        # Record using sequential key: block_strip_map[i] corresponds to flat_blocks[i]
        seq_key = len(ctx.flat_blocks)
        ctx.block_strip_map[seq_key] = len(ctx.all_strips)
        ctx.flat_blocks.append(block)

        # Unified gutter path
        is_neutral = indicator_name is None
        final_strips = _add_gutter_to_strips(
            block_strips_for_gutter,
            indicator_name,
            is_expandable,
            arrow,
            ctx.width,
            neutral=is_neutral,
            show_right=ctx.show_right,
        )
        ctx.all_strips.extend(final_strips)
        ctx.last_rendered_indicator = indicator_name

    # Recurse into children when container is visible and expanded
    if children and vis.visible and vis.expanded:
        tools_filter = ctx.filters.get("tools", ALWAYS_VISIBLE)
        collapsed = _collapse_children(children, tools_filter.full, overrides=ctx.overrides)
        for child in collapsed:
            _render_block_tree(child, ctx)


# ─── Core rendering ───────────────────────────────────────────────────────────


def render_streaming_preview(text: str, console, width: int) -> list:
    """Lightweight streaming renderer — Markdown + gutter, nothing else.

    Bypasses: visibility resolution, _render_block_tree(), renderer dispatch,
    search highlighting, expandability, truncation, block caching, region handling.

    Used by _refresh_streaming_delta() for O(n) rendering of accumulated text,
    replacing the O(n^2) full pipeline that re-ran all visibility/dispatch logic.
    """

    # // [LAW:one-source-of-truth] Reuse gutter constants from this module
    show_right = width >= MIN_WIDTH_FOR_RIGHT_GUTTER
    total_gutter = GUTTER_WIDTH + (RIGHT_GUTTER_WIDTH if show_right else 0)
    render_width = max(1, width - total_gutter)

    tc = get_theme_colors()
    renderable = Markdown(text, code_theme=tc.code_theme)

    render_options = console.options.update_width(render_width)
    segments = console.render(renderable, render_options)
    lines = list(Segment.split_lines(segments))
    if lines:
        content_strips = [
            s.adjust_cell_length(render_width) for s in Strip.from_lines(lines)
        ]
    else:
        content_strips = []

    return _add_gutter_to_strips(
        content_strips,
        indicator_name="assistant",
        is_expandable=False,
        arrow_char="",
        width=width,
        show_right=show_right,
    )


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
    overrides=None,
) -> tuple[list, dict[int, int], list[FormattedBlock]]:
    """Render blocks to Strip objects for Line API storage.

    Recursively walks the block tree. Each block's own content is rendered,
    then children are rendered (when the container is expanded and visible).

    # [LAW:single-enforcer] All visibility logic happens here (via _render_block_tree).

    Args:
        blocks: FormattedBlock list for one turn (hierarchical)
        filters: Current filter state (category name -> VisState)
        console: Rich Console instance
        width: Render width in cells
        wrap: Enable word wrapping
        block_cache: Optional LRUCache for caching rendered strips per block
        is_streaming: If True, skip truncation (show all content during stream)
        search_ctx: Optional SearchContext for highlighting matches
        turn_index: Turn index for search match correlation
        overrides: Optional ViewOverrides for reading/writing per-block view state

    Returns:
        (strips, block_strip_map, flat_blocks) — pre-rendered lines, a dict mapping
        sequential block index to its first strip line index, and the flattened
        block list for click resolution.
    """
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

    ctx = _RenderContext(
        all_strips=[],
        flat_blocks=[],
        block_strip_map={},
        console=console,
        render_options=base_render_options,
        render_width=render_width,
        width=width,
        block_cache=block_cache,
        is_streaming=is_streaming,
        search_ctx=search_ctx,
        turn_index=turn_index,
        show_right=show_right,
        filters=filters,
        overrides=overrides,
    )

    for block in blocks:
        _render_block_tree(block, ctx)

    return ctx.all_strips, ctx.block_strip_map, ctx.flat_blocks


def _apply_search_highlights(
    text: Text, search_ctx, turn_index: int, block_index: int, block: object = None
) -> None:
    """Apply search highlights to a Text object.

    All matches get a dim background highlight.
    The current navigated-to match gets a bright highlight override.

    Uses identity matching (block is current.block) when block is provided,
    falling back to index comparison for backwards compatibility.
    """

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
    # // [LAW:dataflow-not-control-flow] identity_match is a value
    current = search_ctx.current_match
    is_current_block = (
        current is not None
        and current.turn_index == turn_index
        and (
            (block is not None and current.block is block)
            or (block is None and current.block_index == block_index)
        )
    )
    if is_current_block:
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
        "remove": ("- ", tc.error),
        # // [LAW:locality-or-seam] Legacy support for pre-rename persisted tuples.
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


def _pct(part: int, total: int) -> str:
    """Format percentage."""
    if total == 0:
        return "0%"
    return "{:.0f}%".format(100 * part / total)
