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

from cc_dump.formatting import (
    FormattedBlock,
    SeparatorBlock,
    HeaderBlock,
    HttpHeadersBlock,
    MetadataBlock,
    SystemLabelBlock,
    TrackedContentBlock,
    RoleBlock,
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
        raise RuntimeError(
            "Theme not initialized. Call set_theme() before rendering."
        )
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
    VisState(False, False, True):  0,
    VisState(False, True, False):  0,
    VisState(False, True, True):   0,
    # Summary level (visible=True, full=False)
    VisState(True, False, False):  3,    # summary collapsed
    VisState(True, False, True):   12,   # summary expanded
    # Full level (visible=True, full=True)
    VisState(True, True, False):   5,    # full collapsed
    VisState(True, True, True):    None, # full expanded (unlimited)
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
    "TurnBudgetBlock": Category.BUDGET,
    "SystemLabelBlock": Category.SYSTEM,
    "TrackedContentBlock": Category.SYSTEM,
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


def _resolve_visibility(
    block: FormattedBlock, filters: dict
) -> VisState:
    """Determine VisState for a block given current filter state.

    // [LAW:one-source-of-truth] Returns THE visibility representation.
    // [LAW:dataflow-not-control-flow] Value coalescing, not branching.

    Filters contain VisState values keyed by category name.
    Per-block `block.expanded` overrides category-level expansion.
    Returns ALWAYS_VISIBLE for blocks with no category.
    """
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


def _add_filter_indicator(text: ConsoleRenderable, filter_name: str) -> ConsoleRenderable:
    """Add a colored indicator to show which filter controls this content.

    Only works for Text objects. Non-Text renderables (like Markdown) are returned unchanged.
    Use _prepend_indicator_to_strips() for those cases.
    """
    # Guard: only Text objects can be modified this way
    if not isinstance(text, Text):
        return text

    if filter_name not in FILTER_INDICATORS:
        return text

    symbol, color = FILTER_INDICATORS[filter_name]
    indicator = Text()
    indicator.append(symbol + " ", style=f"bold {color}")
    indicator.append(text)
    return indicator


def _category_indicator_name(block: FormattedBlock) -> str | None:
    """Get the filter indicator name for a block's category."""
    cat = get_category(block)
    if cat is None:
        return None
    return cat.value


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
    label_fn, style = specs.get(
        block.header_type, (lambda b: "UNKNOWN", "bold")
    )
    t = Text()
    t.append(" {} ".format(label_fn(block)), style=style)
    t.append(" ({})".format(block.timestamp), style="dim")
    return t


def _render_http_headers(block: HttpHeadersBlock) -> Text | None:
    tc = get_theme_colors()
    t = Text()
    if block.header_type == "response":
        t.append("  HTTP {} ".format(block.status_code), style=f"bold {tc.info}")
    else:
        t.append("  HTTP Headers ", style=f"bold {tc.info}")

    for key in sorted(block.headers.keys()):
        value = block.headers[key]
        t.append("\n    {}: ".format(key), style=f"dim {tc.info}")
        t.append(value, style="dim")

    return t


def _render_metadata(block: MetadataBlock) -> Text | None:
    parts = []
    parts.append("model: ")
    parts.append(("{}".format(block.model), "bold"))
    parts.append(" | max_tokens: {}".format(block.max_tokens))
    parts.append(" | stream: {}".format(block.stream))
    if block.tool_count:
        parts.append(" | tools: {}".format(block.tool_count))

    t = Text()
    t.append("  ", style="dim")
    for part in parts:
        if isinstance(part, tuple):
            t.append(part[0], style=part[1])
        else:
            t.append(part)
    t.stylize("dim")
    return t


def _render_system_label(block: SystemLabelBlock) -> Text | None:
    tc = get_theme_colors()
    return Text("SYSTEM:", style=f"bold {tc.system}")


def _render_tracked_new(block: TrackedContentBlock, tag_style: str) -> ConsoleRenderable:
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


def _render_tracked_content(block: TrackedContentBlock) -> ConsoleRenderable | None:
    """Render a TrackedContentBlock with tag colors — full content."""
    fg, bg = TAG_STYLES[block.color_idx % len(TAG_STYLES)]
    tag_style = "bold {} on {}".format(fg, bg)

    renderer = _TRACKED_STATUS_RENDERERS.get(block.status)
    if renderer:
        return renderer(block, tag_style)
    return Text("")


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
    if (
        len(seg.sub_blocks) == 1
        and seg.sub_blocks[0].kind == SubBlockKind.MD
    ):
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
            parts.append(
                Syntax(inner, sb.meta.info or "", theme=tc.code_theme)
            )

        elif sb.kind == SubBlockKind.XML_BLOCK:
            m = sb.meta
            start_tag = text[
                m.start_tag_span.start : m.start_tag_span.end
            ].rstrip("\n")
            end_tag = text[
                m.end_tag_span.start : m.end_tag_span.end
            ].rstrip("\n")
            inner = text[m.inner_span.start : m.inner_span.end]
            xml_parts: list[ConsoleRenderable] = [
                Text(start_tag, style="bold dim")
            ]
            if inner.strip():
                xml_parts.append(
                    Markdown(
                        wrap_tags_outside_fences(inner),
                        code_theme=tc.code_theme,
                    )
                )
            xml_parts.append(Text(end_tag, style="bold dim"))
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


def _render_text_content(block: TextContentBlock) -> ConsoleRenderable | None:
    if not block.text:
        return None
    # Render as segmented Markdown for USER and ASSISTANT categories
    if block.category in _MARKDOWN_CATEGORIES:
        return _render_segmented_block(block)
    return _indent_text(block.text, block.indent)


def _render_tool_use(block: ToolUseBlock) -> Text | None:
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    t = Text("  ")
    t.append("[Use: {}]".format(block.name), style="bold {}".format(color))
    if block.detail:
        t.append(" {}".format(block.detail), style="dim")
    t.append(" ({} bytes)".format(block.input_size))
    return t


def _render_tool_result(block: ToolResultBlock) -> Text | None:
    color = MSG_COLORS[block.msg_color_idx % len(MSG_COLORS)]
    # [LAW:dataflow-not-control-flow] Build label unconditionally from data
    suffix = " ERROR" if block.is_error else ""
    name_part = block.tool_name if block.tool_name else ""
    if name_part:
        label = f"[Result: {name_part}{suffix}]"
    else:
        label = f"[Result{suffix}]"
    t = Text("  ")
    t.append(label, style="bold {}".format(color))
    if block.detail:
        t.append(" {}".format(block.detail), style="dim")
    t.append(" ({} bytes)".format(block.size))
    return t


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
    "TurnBudgetBlock": _render_turn_budget,
    "SystemLabelBlock": _render_system_label,
    "TrackedContentBlock": _render_tracked_content,
    "RoleBlock": _render_role,
    "TextContentBlock": _render_text_content,
    "ToolUseBlock": _render_tool_use,
    "ToolResultBlock": _render_tool_result,
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
    # TrackedContentBlock: title-only at summary level
    ("TrackedContentBlock", True, False, False): _render_tracked_content_title,
    ("TrackedContentBlock", True, False, True):  _render_tracked_content_title,
    # TurnBudgetBlock: oneliner at summary level
    ("TurnBudgetBlock", True, False, False): _render_turn_budget_oneliner,
    ("TurnBudgetBlock", True, False, True):  _render_turn_budget_oneliner,
}


def _build_renderer_registry() -> dict[tuple[str, bool, bool, bool], Callable]:
    """Build unified renderer registry. Every (type, vis_state) has one renderer.

    // [LAW:dataflow-not-control-flow] Single lookup replaces conditional dispatch.
    """
    registry: dict[tuple[str, bool, bool, bool], Callable] = {}
    visible_states = [
        (True, False, False), (True, False, True),
        (True, True, False), (True, True, True),
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


def _prepare_blocks(
    blocks: list, filters: dict
) -> list[tuple[int, FormattedBlock]]:
    """Pre-pass: apply tool summarization based on tools level.

    // [LAW:dataflow-not-control-flow] tools_on is a value, not a branch.
    """
    tools_filter = filters.get("tools", ALWAYS_VISIBLE)
    tools_on = tools_filter.full  # individual tools at FULL level
    return collapse_tool_runs(blocks, tools_on)


# ─── Truncation and collapse indicator ─────────────────────────────────────────


def _make_collapse_indicator(hidden_lines: int, width: int):
    """Create a dim '... N more lines' strip."""
    from rich.segment import Segment
    from rich.style import Style
    from textual.strip import Strip

    text = "    \u00b7\u00b7\u00b7 {} more lines".format(hidden_lines)
    seg = Segment(text, style=Style(dim=True))
    strip = Strip([seg])
    strip.adjust_cell_length(width)
    return strip


_ARROW_COLLAPSED = "\u25b6"  # ▶
_ARROW_EXPANDED = "\u25bc"  # ▼


def _prepend_indicator_to_strips(block_strips, indicator_name: str, width: int):
    """Prepend a category indicator segment to the first strip.

    Used for Markdown and other non-Text renderables where we can't prepend
    to the Text object directly.
    """
    if not block_strips or indicator_name not in FILTER_INDICATORS:
        return block_strips
    from rich.segment import Segment
    from rich.style import Style
    from textual.strip import Strip

    symbol, color = FILTER_INDICATORS[indicator_name]
    indicator_seg = Segment(symbol + " ", Style(bold=True, color=color))

    first = block_strips[0]
    segments = list(first)
    new_segments = [indicator_seg] + segments

    new_strip = Strip(new_segments)
    new_strip.adjust_cell_length(width)
    return [new_strip] + list(block_strips[1:])


def _add_arrow_or_space_to_strips(
    block_strips, is_expandable, is_expanded, category_color, width
):
    """Add arrow (if expandable) or space (if not) after indicator for alignment."""
    if not block_strips:
        return block_strips
    from rich.segment import Segment
    from rich.style import Style
    from textual.strip import Strip

    if is_expandable:
        arrow = _ARROW_EXPANDED if is_expanded else _ARROW_COLLAPSED
        insert_seg = Segment(arrow + " ", Style(color=category_color, bold=True))
    else:
        insert_seg = Segment("  ", Style())  # two spaces for alignment

    first = block_strips[0]
    segments = list(first)

    # Insert after first segment (the indicator ▌)
    if len(segments) > 0:
        new_segments = [segments[0], insert_seg] + segments[1:]
    else:
        new_segments = [insert_seg]

    new_strip = Strip(new_segments)
    new_strip.adjust_cell_length(width)
    return [new_strip] + list(block_strips[1:])


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

    render_options = console.options
    if not wrap:
        render_options = render_options.update(overflow="ignore", no_wrap=True)
    render_options = render_options.update_width(width)

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

        # Single unified renderer lookup
        # // [LAW:dataflow-not-control-flow] One lookup replaces conditional dispatch
        renderer = RENDERERS.get((type_name, vis.visible, vis.full, vis.expanded))
        if renderer:
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

        # Apply search highlights before indicator (only on Text objects)
        if block_has_matches and isinstance(text, Text):
            _apply_search_highlights(text, search_ctx, turn_index, orig_idx)

        # Add category indicator (works for Text, passed through for others)
        indicator_name = _category_indicator_name(block)
        indicator_added_to_text = False
        if indicator_name:
            original_text = text
            text = _add_filter_indicator(text, indicator_name)
            indicator_added_to_text = text is not original_text  # True if Text modified

        block_strip_map[orig_idx] = len(all_strips)

        # Cache key: simpler with VisState
        cache_key = (
            id(block),
            width,
            vis,
            search_hash,
        )

        # Check cache first
        if block_cache is not None and cache_key in block_cache:
            block_strips = block_cache[cache_key]
        else:
            # Render block
            segments = console.render(text, render_options)
            lines = list(Segment.split_lines(segments))
            if lines:
                block_strips = Strip.from_lines(lines)
                for strip in block_strips:
                    strip.adjust_cell_length(width)
            else:
                block_strips = []

            # Cache result
            if block_cache is not None:
                block_cache[cache_key] = block_strips

        # If indicator wasn't added to text (e.g., Markdown), add to strips
        if indicator_name and not indicator_added_to_text:
            block_strips = _prepend_indicator_to_strips(
                block_strips, indicator_name, width
            )

        # Track expandability: always check against collapsed limit for this detail level
        # // [LAW:single-enforcer] _expandable enables click-to-expand interaction
        collapsed_limit = TRUNCATION_LIMITS[VisState(True, vis.full, False)]
        block._expandable = (
            collapsed_limit is not None
            and collapsed_limit > 0
            and len(block_strips) > collapsed_limit
        )

        # Truncation: ALWAYS applies when max_lines < strip count (not streaming)
        # // [LAW:dataflow-not-control-flow] No should_truncate flag, just max_lines value
        if (
            not is_streaming
            and max_lines is not None
            and len(block_strips) > max_lines
        ):
            hidden = len(block_strips) - max_lines
            truncated_strips = list(block_strips[:max_lines])
            # Add arrow (collapsed) or space for alignment (only if has indicator)
            if indicator_name:
                cat_color = FILTER_INDICATORS.get(indicator_name, (None, None))[1]
                truncated_strips = _add_arrow_or_space_to_strips(
                    truncated_strips, block._expandable, False, cat_color, width
                )
            truncated_strips.append(_make_collapse_indicator(hidden, width))
            all_strips.extend(truncated_strips)
        else:
            # Not truncated - add arrow (expanded) or space for alignment (only if has indicator)
            if indicator_name:
                cat_color = FILTER_INDICATORS.get(indicator_name, (None, None))[1]
                final_strips = _add_arrow_or_space_to_strips(
                    list(block_strips), block._expandable, True, cat_color, width
                )
                all_strips.extend(final_strips)
            else:
                all_strips.extend(block_strips)

    return all_strips, block_strip_map


def _apply_search_highlights(text: Text, search_ctx, turn_index: int, block_index: int) -> None:
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
