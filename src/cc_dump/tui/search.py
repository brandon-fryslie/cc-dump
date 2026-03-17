"""Full-text search for conversation content — vim-style / search.

State machine: INACTIVE → EDITING → NAVIGATING → INACTIVE
Search runs incrementally during EDITING with debounce.
Navigation keys in NAVIGATING phase are reserved for upcoming redesign.

This module is RELOADABLE.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum, IntFlag
from typing import Callable

from snarfx import Observable, reaction
from snarfx import textual as stx
from rich.text import Text
from textual.widgets import Static

import cc_dump.core.palette
import cc_dump.core.segmentation
from cc_dump.core.analysis import fmt_tokens
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
    region_index: int | None = None


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


@dataclass(frozen=True)
class SearchBarState:
    """Store-projected state required to render SearchBar."""

    phase: SearchPhase
    query: str
    modes: SearchMode
    cursor_pos: int
    current_index: int
    match_count: int


class SearchTextCache:
    """Bounded LRU cache for searchable block text.

    Entries are keyed by `_search_cache_key(block)` and optionally associated
    with an owner (turn identity) for selective invalidation when old turns
    are pruned.
    """

    def __init__(self, max_entries: int = 20_000):
        self.max_entries = max(1, int(max_entries))
        self._entries: OrderedDict[tuple[str, int], str] = OrderedDict()
        self._owners_by_key: dict[tuple[str, int], int] = {}
        self._keys_by_owner: dict[int, set[tuple[str, int]]] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: tuple[str, int]) -> bool:
        return key in self._entries

    def clear(self) -> None:
        self._entries.clear()
        self._owners_by_key.clear()
        self._keys_by_owner.clear()

    def get(self, key: tuple[str, int]) -> str | None:
        value = self._entries.get(key)
        if value is not None:
            self._entries.move_to_end(key)
        return value

    def put(self, key: tuple[str, int], value: str, owner: int | None = None) -> None:
        if key in self._entries:
            self._entries.move_to_end(key)
        self._entries[key] = value
        self._set_owner(key, owner)
        while len(self._entries) > self.max_entries:
            self._evict_oldest()

    def invalidate_missing_owners(self, active_owners: Iterable[int]) -> None:
        active = set(active_owners)
        stale_owners = [owner for owner in self._keys_by_owner if owner not in active]
        for owner in stale_owners:
            self._remove_owner(owner)

    def _set_owner(self, key: tuple[str, int], owner: int | None) -> None:
        prev_owner = self._owners_by_key.get(key)
        if prev_owner is not None and prev_owner != owner:
            prev_keys = self._keys_by_owner.get(prev_owner)
            if prev_keys is not None:
                prev_keys.discard(key)
                if not prev_keys:
                    self._keys_by_owner.pop(prev_owner, None)

        if owner is None:
            self._owners_by_key.pop(key, None)
            return

        self._owners_by_key[key] = owner
        self._keys_by_owner.setdefault(owner, set()).add(key)

    def _evict_oldest(self) -> None:
        old_key, _ = self._entries.popitem(last=False)
        owner = self._owners_by_key.pop(old_key, None)
        if owner is None:
            return
        owner_keys = self._keys_by_owner.get(owner)
        if owner_keys is not None:
            owner_keys.discard(old_key)
            if not owner_keys:
                self._keys_by_owner.pop(owner, None)

    def _remove_owner(self, owner: int) -> None:
        owner_keys = self._keys_by_owner.pop(owner, set())
        for key in owner_keys:
            self._entries.pop(key, None)
            self._owners_by_key.pop(key, None)


class SearchState:
    """Mutable search state managed by the app.

    Identity fields (phase, query, modes, cursor_pos) delegate to a SnarfX
    view store — they survive hot-reload via reconcile() without manual
    save/restore.

    Transient fields (matches, debounce timer, cache, etc.) are plain attributes
    rebuilt by run_search() after reload.

    // [LAW:one-source-of-truth] Store is the single source for identity fields.
    """

    def __init__(self, store):
        self._store = store
        # Transient — rebuilt by run_search() after reload
        self.matches: list[SearchMatch] = []
        self.saved_filters: dict = {}
        self.debounce_timer: object | None = None
        self.saved_scroll_y: float | None = None
        self.text_cache: SearchTextCache = SearchTextCache(max_entries=20_000)

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

    @property
    def current_index(self) -> int:
        return self._store.get("search:current_index")

    @current_index.setter
    def current_index(self, v: int) -> None:
        self._store.set("search:current_index", v)


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
    "SystemSection": lambda b: "SYSTEM",
    "MessageBlock": lambda b: f"{b.role} {b.msg_index}",
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
    "TurnBudgetBlock": lambda b: f"Context: {fmt_tokens(b.budget.total_est)} tokens",
    "ResponseUsageBlock": lambda b: f"Usage: {fmt_tokens(b.input_tokens + b.cache_read_tokens + b.cache_creation_tokens)} in {fmt_tokens(b.output_tokens)} out",
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
    return get_searchable_text_cached(block)


def _search_cache_key(block) -> tuple[str, int]:
    """Stable cache key for searchable text extraction."""
    return (str(getattr(block, "block_id", "") or ""), id(block))


def get_searchable_text_cached(
    block,
    cache: SearchTextCache | dict[tuple[str, int], str] | None = None,
    owner: int | None = None,
) -> str:
    """Extract searchable text with optional cache.

    // [LAW:one-source-of-truth] This function is the sole cache read/write boundary.
    """
    cache_key = _search_cache_key(block)
    if isinstance(cache, SearchTextCache):
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    elif cache is not None and cache_key in cache:
        return cache[cache_key]

    type_name = type(block).__name__
    extractor = _TEXT_EXTRACTORS.get(type_name)
    if extractor is None:
        return ""
    text = extractor(block)
    if isinstance(cache, SearchTextCache):
        cache.put(cache_key, text, owner=owner)
    elif cache is not None:
        cache[cache_key] = text
    return text


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


def build_searchable_blocks(blocks: Sequence[object]) -> tuple[tuple[int, object], ...]:
    """Build the per-turn searchable block projection in search iteration order."""
    searchable: list[tuple[int, object]] = []
    for block_idx in range(len(blocks) - 1, -1, -1):
        searchable.extend(_collect_descendants(blocks[block_idx], block_idx))
    return tuple(searchable)


def _turn_searchable_blocks(turn: object) -> tuple[tuple[int, object], ...]:
    """Return cached searchable blocks for a turn, building them only as fallback."""
    searchable = getattr(turn, "searchable_blocks", None)
    if searchable is not None:
        return searchable
    # [LAW:one-source-of-truth] Fallback derives from canonical `blocks` only.
    return build_searchable_blocks(getattr(turn, "blocks", ()))


def _match_region_index(
    block: object,
    text_offset: int,
    *,
    segmentation_cache: dict[int, cc_dump.core.segmentation.SegmentResult],
) -> int | None:
    """Resolve content region index for a match offset inside a text-like block."""
    content = getattr(block, "content", None)
    regions = getattr(block, "content_regions", None) or []
    if not isinstance(content, str) or not regions:
        return None
    cache_key = id(block)
    seg = segmentation_cache.get(cache_key)
    if seg is None:
        seg = cc_dump.core.segmentation.segment(content)
        segmentation_cache[cache_key] = seg
    for i, sb in enumerate(seg.sub_blocks):
        if sb.span.start <= text_offset < sb.span.end and i < len(regions):
            return regions[i].index
    return None


def find_all_matches(
    turns: Sequence[object],
    pattern: re.Pattern,
    text_cache: SearchTextCache | dict[tuple[str, int], str] | None = None,
) -> list[SearchMatch]:
    """Find all matches across all turns, ordered most-recent-first.

    Iterates turns bottom-up, blocks bottom-up within each turn,
    matches reversed within each block. Skips streaming turns.

    Walks container children recursively (arbitrary depth) so content inside
    MessageBlock, MetadataSection, ToolDefsSection→ToolDefBlock→SkillDefChild,
    etc. is searchable. Child matches use the top-level container's
    hierarchical index as block_index, but store the actual
    child block in the `block` field (for identity lookup).

    // [LAW:dataflow-not-control-flow] searchable list is always built;
    // blocks without children contribute only themselves.
    """
    matches: list[SearchMatch] = []
    segmentation_cache: dict[int, cc_dump.core.segmentation.SegmentResult] = {}

    for turn_idx in range(len(turns) - 1, -1, -1):
        td = turns[turn_idx]
        if td.is_streaming:
            continue
        owner = id(td)
        searchable = _turn_searchable_blocks(td)

        for hier_idx, block in searchable:
            text = get_searchable_text_cached(block, text_cache, owner=owner)
            if not text:
                continue

            block_matches = list(pattern.finditer(text))
            for m in reversed(block_matches):
                region_index = _match_region_index(
                    block,
                    m.start(),
                    segmentation_cache=segmentation_cache,
                )
                matches.append(
                    SearchMatch(
                        turn_index=turn_idx,
                        block_index=hier_idx,
                        text_offset=m.start(),
                        text_length=m.end() - m.start(),
                        block=block,
                        region_index=region_index,
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
        self._display_state: Observable[SearchBarState] = Observable(
            SearchBarState(
                phase=SearchPhase.INACTIVE,
                query="",
                modes=SearchMode.CASE_INSENSITIVE,
                cursor_pos=0,
                current_index=0,
                match_count=0,
            )
        )
        # [LAW:single-enforcer] SearchBar rendering is owned by one local projection reaction.
        self._display_reaction = reaction(
            lambda: self._display_state.get(),
            self._render_display,
            fire_immediately=False,
        )

    def on_mount(self) -> None:
        self._store_reaction = stx.reaction(
            self.app,
            lambda: self.app._view_store.search_ui_state.get(),
            self._apply_store_state,
            fire_immediately=True,
        )
        self._render_display(self._display_state.get())

    def on_unmount(self) -> None:
        self._store_reaction.dispose()
        self._display_reaction.dispose()

    def update_display(self, state: SearchBarState) -> None:
        self._display_state.set(state)

    def _apply_store_state(self, payload: object) -> None:
        state = payload if isinstance(payload, dict) else {}
        try:
            modes_raw = int(state.get("modes", int(SearchMode.CASE_INSENSITIVE)))
            modes = SearchMode(modes_raw)
        except (TypeError, ValueError):
            modes = SearchMode.CASE_INSENSITIVE
        phase_raw = str(state.get("phase", SearchPhase.INACTIVE.value))
        try:
            phase = SearchPhase(phase_raw)
        except ValueError:
            phase = SearchPhase.INACTIVE

        self.display = phase != SearchPhase.INACTIVE
        self.update_display(
            SearchBarState(
                phase=phase,
                query=str(state.get("query", "")),
                modes=modes,
                cursor_pos=int(state.get("cursor_pos", 0)),
                current_index=int(state.get("current_index", 0)),
                match_count=int(state.get("match_count", 0)),
            )
        )

    def _build_search_line(self, state: SearchBarState, tc) -> Text:
        line = Text()
        line.append("/ ", style=tc.search_prompt_style)
        line.append_text(self._query_with_cursor(state))
        line.append_text(self._match_summary(state, tc))
        return line

    def _query_with_cursor(self, state: SearchBarState) -> Text:
        if state.phase != SearchPhase.EDITING:
            return Text(state.query, style="bold")

        query = state.query
        cursor = state.cursor_pos
        if cursor < len(query):
            return Text.assemble(
                (query[:cursor], "bold"),
                (query[cursor], "bold reverse"),
                (query[cursor + 1 :], "bold"),
            )
        return Text.assemble((query, "bold"), ("█", ""))

    def _match_summary(self, state: SearchBarState, tc) -> Text:
        summary = Text()
        if state.match_count > 0:
            summary.append(
                f"  [{state.current_index + 1}/{state.match_count}]",
                style=tc.search_active_style,
            )
            return summary

        if not state.query:
            return summary

        pattern = compile_search_pattern(state.query, state.modes)
        if pattern is None:
            summary.append("  [invalid pattern]", style=tc.search_error_style)
            return summary

        summary.append("  [no matches]", style="dim")
        return summary

    def _build_mode_line(self, state: SearchBarState, tc) -> Text:
        line = Text()
        line.append("Modes: ", style="dim")
        for enabled, label in (
            (bool(state.modes & SearchMode.CASE_INSENSITIVE), "i "),
            (bool(state.modes & SearchMode.WORD_BOUNDARY), "w "),
            (bool(state.modes & SearchMode.REGEX), ".* "),
            (bool(state.modes & SearchMode.INCREMENTAL), "inc"),
        ):
            line.append(label, style=tc.search_active_style if enabled else "dim")
        return line

    def _build_toggle_help_line(self, tc) -> Text:
        line = Text()
        line.append("Toggle: ", style="dim")
        for key, label in (
            ("Alt+c", "=case "),
            ("Alt+w", "=word "),
            ("Alt+r", "=regex "),
            ("Alt+i", "=incr"),
        ):
            line.append(key, style=tc.search_keys_style)
            line.append(label, style="dim")
        return line

    def _build_nav_help_line(self, state: SearchBarState, tc) -> Text:
        line = Text()
        line.append("Keys: ", style="dim")
        pairs: Sequence[tuple[str, str]]
        if state.phase == SearchPhase.EDITING:
            pairs = (
                ("Enter", "=search "),
                ("^A/^E", "=home/end "),
                ("^W", "=del-word "),
                ("Esc", "=exit(stay) "),
                ("q", "=exit(restore)"),
            )
        else:
            pairs = (
                ("n", "=next "),
                ("N", "=prev "),
                ("^N/^P", "=next/prev "),
                ("Tab/S-Tab", "=next/prev "),
                ("/", "=edit "),
                ("Esc", "=exit(stay) "),
                ("q", "=exit(restore)"),
            )
        for key, label in pairs:
            line.append(key, style=tc.search_keys_style)
            line.append(label, style="dim")
        return line

    def _render_display(self, state: SearchBarState) -> None:
        """Render the search bar from current state."""
        if state.phase == SearchPhase.INACTIVE:
            self.display = False
            return

        self.display = True

        runtime = cc_dump.tui.rendering.get_runtime_from_owner(self)
        tc = cc_dump.tui.rendering.get_theme_colors(runtime=runtime)
        lines = [
            self._build_search_line(state, tc),
            self._build_mode_line(state, tc),
            self._build_toggle_help_line(tc),
            self._build_nav_help_line(state, tc),
        ]
        self.update(Text("\n").join(lines))
