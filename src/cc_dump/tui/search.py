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
    """A single match location in the conversation."""

    turn_index: int
    block_index: int
    text_offset: int
    text_length: int


@dataclass
class SearchContext:
    """Passed to rendering to highlight matches."""

    pattern: re.Pattern
    pattern_str: str
    current_match: SearchMatch | None
    all_matches: list[SearchMatch]

    def matches_in_block(self, turn_index: int, block_index: int) -> list[SearchMatch]:
        return [
            m
            for m in self.all_matches
            if m.turn_index == turn_index and m.block_index == block_index
        ]


@dataclass
class SearchState:
    """Mutable search state managed by the app."""

    phase: SearchPhase = SearchPhase.INACTIVE
    query: str = ""
    cursor_pos: int = 0
    modes: SearchMode = (
        SearchMode.CASE_INSENSITIVE | SearchMode.REGEX | SearchMode.INCREMENTAL
    )
    matches: list[SearchMatch] = field(default_factory=list)
    current_index: int = 0  # index into matches (0 = most recent)
    saved_filters: dict = field(default_factory=dict)
    expanded_blocks: list[tuple[int, int]] = field(
        default_factory=list
    )  # (turn_index, block_index) pairs we expanded
    raised_categories: set = field(default_factory=set)  # category names we raised
    debounce_timer: object | None = None  # Timer handle


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
    "TextContentBlock": lambda b: b.text,
    "ToolUseBlock": lambda b: f"{b.name} {b.detail}",
    "ToolResultBlock": lambda b: f"{b.tool_name} {b.detail}",
    "ToolUseSummaryBlock": lambda b: " ".join(
        f"{name} {count}x" for name, count in b.tool_counts.items()
    ),
    "ImageBlock": lambda b: f"image: {b.media_type}",
    "UnknownTypeBlock": lambda b: b.block_type,
    "StreamInfoBlock": lambda b: f"model: {b.model}",
    "StreamToolUseBlock": lambda b: b.name,
    "TextDeltaBlock": lambda b: b.text,
    "StopReasonBlock": lambda b: f"stop: {b.reason}",
    "ErrorBlock": lambda b: f"HTTP {b.code} {b.reason}",
    "ProxyErrorBlock": lambda b: b.error,
    "NewlineBlock": lambda b: "",
    "TurnBudgetBlock": lambda b: f"Context: {b.budget.total_est} tok",
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


def find_all_matches(turns: list, pattern: re.Pattern) -> list[SearchMatch]:
    """Find all matches across all turns, ordered most-recent-first.

    Iterates turns bottom-up, blocks bottom-up within each turn,
    matches reversed within each block. Skips streaming turns.
    """
    matches: list[SearchMatch] = []

    for turn_idx in range(len(turns) - 1, -1, -1):
        td = turns[turn_idx]
        if td.is_streaming:
            continue

        for block_idx in range(len(td.blocks) - 1, -1, -1):
            block = td.blocks[block_idx]
            text = get_searchable_text(block)
            if not text:
                continue

            # Find all matches in this block, reversed for bottom-up ordering
            block_matches = list(pattern.finditer(text))
            for m in reversed(block_matches):
                matches.append(
                    SearchMatch(
                        turn_index=turn_idx,
                        block_index=block_idx,
                        text_offset=m.start(),
                        text_length=m.end() - m.start(),
                    )
                )

    return matches


# ─── Search bar widget ────────────────────────────────────────────────────────


class SearchBar(Static):
    """Bottom search bar — renders as a single Rich Text line.

    Not an Input widget. The app's on_key handles all text editing.
    """

    DEFAULT_CSS = """
    SearchBar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text;
        display: none;
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
        t = Text()

        # Mode indicators
        t.append("[", style="dim")
        # Case insensitive
        ci_style = "bold" if state.modes & SearchMode.CASE_INSENSITIVE else "dim"
        t.append("i", style=ci_style)
        # Word boundary
        wb_style = "bold" if state.modes & SearchMode.WORD_BOUNDARY else "dim"
        t.append("w", style=wb_style)
        # Regex
        rx_style = "bold" if state.modes & SearchMode.REGEX else "dim"
        t.append(".*", style=rx_style)
        t.append("] ", style="dim")

        # Slash + query
        t.append("/", style="bold")

        if state.phase == SearchPhase.EDITING:
            # Show query with cursor
            query = state.query
            cursor = state.cursor_pos
            if cursor < len(query):
                t.append(query[:cursor])
                t.append(query[cursor], style="reverse")
                t.append(query[cursor + 1 :])
            else:
                t.append(query)
                t.append(" ", style="reverse")  # cursor at end
        else:
            # Navigating: show query without cursor
            t.append(state.query)

        # Match count
        if state.matches:
            t.append(
                f"  {state.current_index + 1}/{len(state.matches)}",
                style="bold",
            )
        elif state.query:
            # Check if pattern is invalid
            pattern = compile_search_pattern(state.query, state.modes)
            if pattern is None and state.query:
                t.append("  invalid pattern", style="bold red")
            else:
                t.append("  0 matches", style="dim")

        self.update(t)
