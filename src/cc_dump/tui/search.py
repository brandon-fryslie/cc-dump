"""Full-text search for conversation content — vim-style / search.

State machine: INACTIVE → EDITING → NAVIGATING → INACTIVE
Search runs incrementally during EDITING with debounce.
Navigation (n/N) in NAVIGATING phase raises category visibility and expands blocks.

This module is RELOADABLE.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, IntFlag
from typing import Callable

from rich.text import Text
from textual.widgets import Static

import cc_dump.palette
import cc_dump.tui.rendering


# ─── Data types ──────────────────────────────────────────────────────────────


class SearchMode(IntFlag):
    CASE_INSENSITIVE = 1
    WORD_BOUNDARY = 2
    REGEX = 4
    INCREMENTAL = 8


class SearchPhase(Enum):
    INACTIVE = "inactive"
    EDITING = "editing"
    NAVIGATING = "navigating"


@dataclass
class SearchMatch:
    """A single match location in the conversation.

    block_index: hierarchical index (parent container's index for children).
    block: the actual block object — enables identity-based lookup after flattening.
    """

    turn_index: int
    block_index: int
    text_offset: int
    text_length: int
    block: object = None


@dataclass
class SearchContext:
    """Passed to rendering to highlight matches."""

    pattern: re.Pattern
    pattern_str: str
    current_match: SearchMatch | None
    all_matches: list[SearchMatch]

    def matches_in_block(
        self, turn_index: int, block_index: int, block: object = None
    ) -> list[SearchMatch]:
        """Return matches for a specific block.

        When block is provided, uses identity matching (m.block is block)
        to resolve the flat-vs-hierarchical index mismatch introduced by
        container blocks with children.
        """
        # // [LAW:dataflow-not-control-flow] identity_match is a value, filter always runs
        if block is not None:
            return [
                m
                for m in self.all_matches
                if m.turn_index == turn_index and m.block is block
            ]
        return [
            m
            for m in self.all_matches
            if m.turn_index == turn_index and m.block_index == block_index
        ]


class SearchState:
    """Mutable search state managed by the app.

    Identity fields (phase, query, modes, cursor_pos) delegate to a SnarfX
    view store — they survive hot-reload via reconcile() without manual
    save/restore.

    Transient fields (matches, expanded_blocks, etc.) are plain attributes
    rebuilt by run_search() after reload.

    // [LAW:one-source-of-truth] Store is the single source for identity fields.
    """

    def __init__(self, store):
        self._store = store
        # Transient — rebuilt by run_search() after reload
        self.matches: list[SearchMatch] = []
        self.current_index: int = 0
        self.saved_filters: dict = {}
        self.expanded_blocks: list[tuple[int, int, object]] = []
        self.debounce_timer: object | None = None
        self.saved_scroll_y: float | None = None

    # ── Identity properties (delegated to store) ──

    @property
    def phase(self) -> SearchPhase:
        return SearchPhase(self._store.get("search:phase"))

    @phase.setter
    def phase(self, v: SearchPhase) -> None:
        self._store.set("search:phase", v.value)

    @property
    def query(self) -> str:
        return self._store.get("search:query")

    @query.setter
    def query(self, v: str) -> None:
        self._store.set("search:query", v)

    @property
    def modes(self) -> SearchMode:
        return SearchMode(self._store.get("search:modes"))

    @modes.setter
    def modes(self, v: SearchMode) -> None:
        self._store.set("search:modes", int(v))

    @property
    def cursor_pos(self) -> int:
        return self._store.get("search:cursor_pos")

    @cursor_pos.setter
    def cursor_pos(self, v: int) -> None:
        self._store.set("search:cursor_pos", v)


# ─── Text extraction ─────────────────────────────────────────────────────────

# [LAW:dataflow-not-control-flow] Dispatch table for searchable text extraction.
# Maps block type name → callable(block) → str.

_TEXT_EXTRACTORS: dict[str, Callable] = {
    "SeparatorBlock": lambda b: "",
    "HeaderBlock": lambda b: f"{b.label} {b.timestamp}",
    "HttpHeadersBlock": lambda b: " ".join(
        f"{k}: {v}" for k, v in b.headers.items()
    ),
    "MetadataBlock": lambda b: f"model: {b.model} max_tokens: {b.max_tokens}",
    "SystemLabelBlock": lambda b: "SYSTEM:",
    "TrackedContentBlock": lambda b: (
        b.content if b.status == "new" else b.new_content if b.status == "changed" else ""
    ),
    "RoleBlock": lambda b: b.role,
    "TextContentBlock": lambda b: b.content,
    "ToolUseBlock": lambda b: f"{b.name} {b.detail}",
    "ToolResultBlock": lambda b: f"{b.tool_name} {b.detail}",
    "ToolUseSummaryBlock": lambda b: " ".join(
        f"{name} {count}x" for name, count in b.tool_counts.items()
    ),
    "ImageBlock": lambda b: f"image: {b.media_type}",
    "UnknownTypeBlock": lambda b: b.block_type,
    "StreamInfoBlock": lambda b: f"model: {b.model}",
    "StreamToolUseBlock": lambda b: b.name,
    "TextDeltaBlock": lambda b: b.content,
    "StopReasonBlock": lambda b: f"stop: {b.reason}",
    "ErrorBlock": lambda b: f"HTTP {b.code} {b.reason}",
    "ProxyErrorBlock": lambda b: b.error,
    "NewlineBlock": lambda b: "",
    "TurnBudgetBlock": lambda b: f"Context: {b.budget.total_est} tokens",
    # Container child types — searchable when find_all_matches walks children
    "ToolDefBlock": lambda b: f"{b.name} {b.description}",
    "SkillDefChild": lambda b: f"{b.name} {b.description}",
    "AgentDefChild": lambda b: f"{b.name} {b.description}",
    "ConfigContentBlock": lambda b: b.content,
    "HookOutputBlock": lambda b: b.content,
    "ThinkingBlock": lambda b: b.content,
}


def get_searchable_text(block) -> str:
    """Extract plain searchable text from a FormattedBlock."""
    type_name = type(block).__name__
    extractor = _TEXT_EXTRACTORS.get(type_name)
    if extractor is None:
        return ""
    return extractor(block)


# ─── Pattern compilation ─────────────────────────────────────────────────────


def compile_search_pattern(query: str, modes: SearchMode) -> re.Pattern | None:
    """Build regex from query + mode flags. Returns None for empty/invalid patterns."""
    if not query:
        return None

    # If REGEX mode is off, escape the query for literal matching
    if not (modes & SearchMode.REGEX):
        pattern_str = re.escape(query)
    else:
        pattern_str = query

    # Word boundary wrapping
    if modes & SearchMode.WORD_BOUNDARY:
        pattern_str = rf"\b{pattern_str}\b"

    # Case sensitivity
    flags = 0
    if modes & SearchMode.CASE_INSENSITIVE:
        flags |= re.IGNORECASE

    try:
        return re.compile(pattern_str, flags)
    except re.error:
        return None


# ─── Match finding ────────────────────────────────────────────────────────────


def _collect_descendants(block, hier_idx: int) -> list[tuple[int, object]]:
    """Collect (hier_idx, block) depth-first, children before parent.

    // [LAW:dataflow-not-control-flow] children is always read; empty list = leaf.
    """
    items: list[tuple[int, object]] = []
    for child in reversed(getattr(block, "children", None) or []):
        items.extend(_collect_descendants(child, hier_idx))
    items.append((hier_idx, block))
    return items


def find_all_matches(turns: list, pattern: re.Pattern) -> list[SearchMatch]:
    """Find all matches across all turns, ordered most-recent-first.

    Iterates turns bottom-up, blocks bottom-up within each turn,
    matches reversed within each block. Skips streaming turns.

    Walks container children recursively (arbitrary depth) so content inside
    MessageBlock, MetadataSection, ToolDefsSection→ToolDefBlock→SkillDefChild,
    etc. is searchable. Child matches use the top-level container's
    hierarchical index as block_index (for _force_vis), but store the actual
    child block in the `block` field (for identity lookup).

    // [LAW:dataflow-not-control-flow] searchable list is always built;
    // blocks without children contribute only themselves.
    """
    matches: list[SearchMatch] = []

    for turn_idx in range(len(turns) - 1, -1, -1):
        td = turns[turn_idx]
        if td.is_streaming:
            continue

        for block_idx in range(len(td.blocks) - 1, -1, -1):
            top_block = td.blocks[block_idx]
            searchable = _collect_descendants(top_block, block_idx)

            for hier_idx, block in searchable:
                text = get_searchable_text(block)
                if not text:
                    continue

                block_matches = list(pattern.finditer(text))
                for m in reversed(block_matches):
                    matches.append(
                        SearchMatch(
                            turn_index=turn_idx,
                            block_index=hier_idx,
                            text_offset=m.start(),
                            text_length=m.end() - m.start(),
                            block=block,
                        )
                    )

    return matches


# ─── Search bar widget ────────────────────────────────────────────────────────


class SearchBar(Static):
    """Bottom search bar — renders as multi-line search interface.

    Not an Input widget. The app's on_key handles all text editing.
    """

    DEFAULT_CSS = """
    SearchBar {
        dock: bottom;
        height: auto;
        max-height: 6;
        color: $text;
        display: none;
        padding: 0 1;
        border-top: solid $accent;
    }
    """

    def __init__(self):
        super().__init__("")

    def update_display(self, state: SearchState) -> None:
        """Render the search bar from current state."""
        if state.phase == SearchPhase.INACTIVE:
            self.display = False
            return

        self.display = True

        # Build multi-line display with theme-aware colors
        tc = cc_dump.tui.rendering.get_theme_colors()
        lines = []

        # Line 1: Search input
        search_line = Text()
        search_line.append("/ ", style=tc.search_prompt_style)

        if state.phase == SearchPhase.EDITING:
            # Show query with cursor
            query = state.query
            cursor = state.cursor_pos
            if cursor < len(query):
                search_line.append(query[:cursor], style="bold")
                search_line.append(query[cursor], style="bold reverse")  # Inverted cursor
                search_line.append(query[cursor + 1 :], style="bold")
            else:
                search_line.append(query, style="bold")
                search_line.append("█", style="")  # Block cursor at end
        else:
            # Navigating: show query without cursor
            search_line.append(state.query, style="bold")

        # Match count on same line
        if state.matches:
            search_line.append(
                f"  [{state.current_index + 1}/{len(state.matches)}]",
                style=tc.search_active_style,
            )
        elif state.query:
            # Check if pattern is invalid
            pattern = compile_search_pattern(state.query, state.modes)
            if pattern is None and state.query:
                search_line.append("  [invalid pattern]", style=tc.search_error_style)
            else:
                search_line.append("  [no matches]", style="dim")

        lines.append(search_line)

        # Line 2: Mode indicators
        mode_line = Text()
        mode_line.append("Modes: ", style="dim")

        # Case insensitive
        if state.modes & SearchMode.CASE_INSENSITIVE:
            mode_line.append("i ", style=tc.search_active_style)
        else:
            mode_line.append("i ", style="dim")

        # Word boundary
        if state.modes & SearchMode.WORD_BOUNDARY:
            mode_line.append("w ", style=tc.search_active_style)
        else:
            mode_line.append("w ", style="dim")

        # Regex
        if state.modes & SearchMode.REGEX:
            mode_line.append(".* ", style=tc.search_active_style)
        else:
            mode_line.append(".* ", style="dim")

        # Incremental
        if state.modes & SearchMode.INCREMENTAL:
            mode_line.append("inc", style=tc.search_active_style)
        else:
            mode_line.append("inc", style="dim")

        lines.append(mode_line)

        # Line 3: Mode toggle help
        help_line = Text()
        help_line.append("Toggle: ", style="dim")
        help_line.append("Alt+c", style=tc.search_keys_style)
        help_line.append("=case ", style="dim")
        help_line.append("Alt+w", style=tc.search_keys_style)
        help_line.append("=word ", style="dim")
        help_line.append("Alt+r", style=tc.search_keys_style)
        help_line.append("=regex ", style="dim")
        help_line.append("Alt+i", style=tc.search_keys_style)
        help_line.append("=incr", style="dim")
        lines.append(help_line)

        # Line 4: Navigation help
        nav_line = Text()
        if state.phase == SearchPhase.EDITING:
            nav_line.append("Keys: ", style="dim")
            nav_line.append("Enter", style=tc.search_keys_style)
            nav_line.append("=search ", style="dim")
            nav_line.append("Esc", style=tc.search_keys_style)
            nav_line.append("=exit(stay) ", style="dim")
            nav_line.append("q", style=tc.search_keys_style)
            nav_line.append("=exit(restore)", style="dim")
        else:
            nav_line.append("Keys: ", style="dim")
            nav_line.append("n", style=tc.search_keys_style)
            nav_line.append("=next ", style="dim")
            nav_line.append("N", style=tc.search_keys_style)
            nav_line.append("=prev ", style="dim")
            nav_line.append("/", style=tc.search_keys_style)
            nav_line.append("=edit ", style="dim")
            nav_line.append("Esc", style=tc.search_keys_style)
            nav_line.append("=exit(stay) ", style="dim")
            nav_line.append("q", style=tc.search_keys_style)
            nav_line.append("=exit(restore)", style="dim")
        lines.append(nav_line)

        # Join lines with newlines
        combined = Text("\n").join(lines)
        self.update(combined)
