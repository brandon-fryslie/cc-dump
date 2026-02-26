"""Unit tests for cc_dump.tui.search module."""

import re

import pytest

from cc_dump.tui.search import (
    SearchMode,
    SearchPhase,
    SearchMatch,
    SearchContext,
    SearchState,
    SearchTextCache,
    get_searchable_text,
    compile_search_pattern,
    find_all_matches,
)
from cc_dump.core.formatting import (
    HeaderBlock,
    HttpHeadersBlock,
    MetadataBlock,
    SystemSection,
    TrackedContentBlock,
    MessageBlock,
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
    SeparatorBlock,
    Category,
    MessageBlock,
    ToolDefsSection,
    ToolDefBlock,
    SkillDefChild,
    ConfigContentBlock,
    ThinkingBlock,
)
from cc_dump.core.analysis import TurnBudget


# ─── Text extraction ─────────────────────────────────────────────────────────


SEARCHABLE_TEXT_CASES = [
    pytest.param(
        HeaderBlock(label="REQUEST #1", timestamp="1:23:45 PM"),
        ["REQUEST #1", "1:23:45 PM"],
        id="header",
    ),
    pytest.param(
        HttpHeadersBlock(headers={"content-type": "application/json"}),
        ["content-type", "application/json"],
        id="http_headers",
    ),
    pytest.param(
        MetadataBlock(model="claude-sonnet-4-5-20250929", max_tokens="8192"),
        ["claude-sonnet-4-5-20250929", "8192"],
        id="metadata",
    ),
    pytest.param(
        SystemSection(children=[]),
        ["SYSTEM"],
        id="system_section",
    ),
    pytest.param(
        TrackedContentBlock(status="new", content="hello world"),
        ["hello world"],
        id="tracked_content_new",
    ),
    pytest.param(
        TrackedContentBlock(status="changed", new_content="new stuff", old_content="old"),
        ["new stuff"],
        id="tracked_content_changed",
    ),
    pytest.param(
        TrackedContentBlock(status="ref"),
        [],
        id="tracked_content_ref",
    ),
    pytest.param(
        MessageBlock(role="assistant", msg_index=3, children=[]),
        ["assistant", "3"],
        id="message",
    ),
    pytest.param(
        TextContentBlock(content="Hello, how can I help?"),
        ["Hello, how can I help?"],
        id="text_content",
    ),
    pytest.param(
        ToolUseBlock(name="Read", detail="/path/to/file.py"),
        ["Read", "/path/to/file.py"],
        id="tool_use",
    ),
    pytest.param(
        ToolResultBlock(tool_name="Bash", detail="ls -la"),
        ["Bash", "ls -la"],
        id="tool_result",
    ),
    pytest.param(
        ToolUseSummaryBlock(tool_counts={"Read": 3, "Bash": 2}, total=5),
        ["Read", "Bash"],
        id="tool_use_summary",
    ),
    pytest.param(
        ImageBlock(media_type="image/png"),
        ["image/png"],
        id="image",
    ),
    pytest.param(
        StreamInfoBlock(model="claude-sonnet-4-5-20250929"),
        ["claude-sonnet-4-5-20250929"],
        id="stream_info",
    ),
    pytest.param(
        StreamToolUseBlock(name="Read"),
        ["Read"],
        id="stream_tool_use",
    ),
    pytest.param(
        TextDeltaBlock(content="streaming text"),
        ["streaming text"],
        id="text_delta",
    ),
    pytest.param(
        StopReasonBlock(reason="end_turn"),
        ["end_turn"],
        id="stop_reason",
    ),
    pytest.param(
        ErrorBlock(code=429, reason="rate_limited"),
        ["429", "rate_limited"],
        id="error",
    ),
    pytest.param(
        ProxyErrorBlock(error="connection refused"),
        ["connection refused"],
        id="proxy_error",
    ),
    pytest.param(
        NewlineBlock(),
        [],
        id="newline",
    ),
    pytest.param(
        SeparatorBlock(),
        [],
        id="separator",
    ),
    pytest.param(
        TurnBudgetBlock(budget=TurnBudget(total_est=50000)),
        ["Context: x tokens"],
        id="turn_budget",
    ),
    pytest.param(
        UnknownTypeBlock(block_type="thinking"),
        ["thinking"],
        id="unknown_type",
    ),
]


class TestGetSearchableText:
    """Test text extraction from all block types."""

    @pytest.mark.parametrize("block,expected", SEARCHABLE_TEXT_CASES)
    def test_get_searchable_text(self, block, expected):
        """Test searchable text extraction from various block types."""
        text = get_searchable_text(block)
        for sub in expected:
            assert sub in text, f"Expected '{sub}' in searchable text, got: {text}"
        if not expected:
            assert text == "", f"Expected empty string, got: {text}"

    def test_get_searchable_text_cached_reuses_cached_value(self, monkeypatch):
        """Cached extraction should avoid repeated extractor execution for same block."""
        import cc_dump.tui.search as search_mod

        class CacheBlock:
            block_id = "cache-block-1"

        calls = {"count": 0}

        def _extractor(_block):
            calls["count"] += 1
            return "cached text"

        monkeypatch.setitem(search_mod._TEXT_EXTRACTORS, "CacheBlock", _extractor)

        block = CacheBlock()
        cache: dict[tuple[str, int], str] = {}

        assert search_mod.get_searchable_text_cached(block, cache) == "cached text"
        assert search_mod.get_searchable_text_cached(block, cache) == "cached text"
        assert calls["count"] == 1


class TestSearchTextCache:
    def test_lru_eviction_keeps_newest_entries(self):
        cache = SearchTextCache(max_entries=2)
        cache.put(("a", 1), "A", owner=1)
        cache.put(("b", 1), "B", owner=1)
        cache.get(("a", 1))  # mark "a" as most-recently-used
        cache.put(("c", 1), "C", owner=1)

        assert ("a", 1) in cache
        assert ("b", 1) not in cache
        assert ("c", 1) in cache

    def test_invalidate_missing_owners_prunes_removed_turn_entries(self):
        cache = SearchTextCache(max_entries=10)
        cache.put(("a", 1), "A", owner=11)
        cache.put(("b", 1), "B", owner=22)
        cache.put(("c", 1), "C", owner=22)

        cache.invalidate_missing_owners({22})

        assert ("a", 1) not in cache
        assert ("b", 1) in cache
        assert ("c", 1) in cache


# ─── Pattern compilation ─────────────────────────────────────────────────────


class TestCompileSearchPattern:
    """Test regex pattern compilation with mode flags."""

    def test_empty_query(self):
        assert compile_search_pattern("", SearchMode(0)) is None

    def test_literal_case_insensitive(self):
        pattern = compile_search_pattern(
            "hello",
            SearchMode.CASE_INSENSITIVE,
        )
        assert pattern is not None
        assert pattern.search("Hello World")
        assert pattern.search("HELLO")

    def test_literal_case_sensitive(self):
        pattern = compile_search_pattern("hello", SearchMode(0))
        assert pattern is not None
        assert pattern.search("hello world")
        assert not pattern.search("Hello World")

    def test_regex_mode(self):
        pattern = compile_search_pattern(
            r"foo\d+",
            SearchMode.REGEX | SearchMode.CASE_INSENSITIVE,
        )
        assert pattern is not None
        assert pattern.search("foo123")
        assert not pattern.search("foobar")

    def test_regex_off_escapes_special_chars(self):
        pattern = compile_search_pattern("foo.bar", SearchMode(0))
        assert pattern is not None
        assert pattern.search("foo.bar")
        assert not pattern.search("fooXbar")

    def test_word_boundary(self):
        pattern = compile_search_pattern(
            "test",
            SearchMode.WORD_BOUNDARY,
        )
        assert pattern is not None
        assert pattern.search("run test now")
        assert not pattern.search("testing")

    def test_invalid_regex(self):
        pattern = compile_search_pattern(
            "[invalid",
            SearchMode.REGEX,
        )
        assert pattern is None

    def test_invalid_regex_literal_mode(self):
        # In literal mode, special chars are escaped, so this should work
        pattern = compile_search_pattern("[invalid", SearchMode(0))
        assert pattern is not None
        assert pattern.search("[invalid")

    def test_all_modes_combined(self):
        pattern = compile_search_pattern(
            r"foo\d+",
            SearchMode.CASE_INSENSITIVE
            | SearchMode.REGEX
            | SearchMode.WORD_BOUNDARY
            | SearchMode.INCREMENTAL,
        )
        assert pattern is not None
        assert pattern.search("FOO123 bar")
        # word boundary should prevent matching inside another word
        # (depending on regex engine behavior with \b around \d+)


# ─── Match finding ────────────────────────────────────────────────────────────


class _FakeTurnData:
    """Minimal turn data for testing find_all_matches."""

    def __init__(self, turn_index, blocks, is_streaming=False):
        self.turn_index = turn_index
        self.blocks = blocks
        self.is_streaming = is_streaming


class TestFindAllMatches:
    """Test match finding with bottom-up ordering."""

    def test_empty_turns(self):
        pattern = re.compile("test")
        assert find_all_matches([], pattern) == []

    def test_single_match(self):
        blocks = [TextContentBlock(content="hello test world")]
        turns = [_FakeTurnData(0, blocks)]
        pattern = re.compile("test")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 1
        assert matches[0].turn_index == 0
        assert matches[0].block_index == 0
        assert matches[0].text_offset == 6
        assert matches[0].text_length == 4

    def test_multiple_matches_in_block(self):
        blocks = [TextContentBlock(content="test one test two test three")]
        turns = [_FakeTurnData(0, blocks)]
        pattern = re.compile("test")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 3
        # Bottom-up within block: last match first
        assert matches[0].text_offset > matches[1].text_offset
        assert matches[1].text_offset > matches[2].text_offset

    def test_bottom_up_turn_ordering(self):
        turns = [
            _FakeTurnData(0, [TextContentBlock(content="first turn match")]),
            _FakeTurnData(1, [TextContentBlock(content="second turn match")]),
        ]
        pattern = re.compile("match")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 2
        # Most recent turn (index 1) first
        assert matches[0].turn_index == 1
        assert matches[1].turn_index == 0

    def test_bottom_up_block_ordering(self):
        blocks = [
            TextContentBlock(content="block zero match"),
            TextContentBlock(content="block one match"),
        ]
        turns = [_FakeTurnData(0, blocks)]
        pattern = re.compile("match")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 2
        # Later block first
        assert matches[0].block_index == 1
        assert matches[1].block_index == 0

    def test_skips_streaming_turns(self):
        turns = [
            _FakeTurnData(0, [TextContentBlock(content="match")]),
            _FakeTurnData(1, [TextContentBlock(content="match")], is_streaming=True),
        ]
        pattern = re.compile("match")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 1
        assert matches[0].turn_index == 0

    def test_skips_empty_text_blocks(self):
        blocks = [
            NewlineBlock(),
            SeparatorBlock(),
            TextContentBlock(content="findme"),
        ]
        turns = [_FakeTurnData(0, blocks)]
        pattern = re.compile("findme")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 1
        assert matches[0].block_index == 2

    def test_no_matches(self):
        blocks = [TextContentBlock(content="hello world")]
        turns = [_FakeTurnData(0, blocks)]
        pattern = re.compile("nonexistent")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 0

    def test_case_insensitive_pattern(self):
        blocks = [TextContentBlock(content="Hello World")]
        turns = [_FakeTurnData(0, blocks)]
        pattern = re.compile("hello", re.IGNORECASE)
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 1

    def test_tool_blocks_searchable(self):
        blocks = [
            ToolUseBlock(name="Bash", detail="ls -la /tmp"),
            ToolResultBlock(tool_name="Bash", detail="ls -la /tmp"),
        ]
        turns = [_FakeTurnData(0, blocks)]
        pattern = re.compile("Bash")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 2


# ─── SearchContext ────────────────────────────────────────────────────────────


class TestSearchContext:
    def test_matches_in_block(self):
        matches = [
            SearchMatch(turn_index=0, block_index=0, text_offset=0, text_length=4),
            SearchMatch(turn_index=0, block_index=1, text_offset=5, text_length=3),
            SearchMatch(turn_index=1, block_index=0, text_offset=0, text_length=4),
        ]
        ctx = SearchContext(
            pattern=re.compile("test"),
            pattern_str="test",
            current_match=matches[0],
            all_matches=matches,
        )
        assert len(ctx.matches_in_block(0, 0)) == 1
        assert len(ctx.matches_in_block(0, 1)) == 1
        assert len(ctx.matches_in_block(1, 0)) == 1
        assert len(ctx.matches_in_block(1, 1)) == 0


# ─── SearchState defaults ────────────────────────────────────────────────────


class TestSearchState:
    def test_defaults(self):
        import cc_dump.app.view_store
        store = cc_dump.app.view_store.create()
        state = SearchState(store)
        assert state.phase == SearchPhase.INACTIVE
        assert state.query == ""
        assert state.cursor_pos == 0
        assert state.modes & SearchMode.CASE_INSENSITIVE
        assert state.modes & SearchMode.REGEX
        assert state.modes & SearchMode.INCREMENTAL
        assert not (state.modes & SearchMode.WORD_BOUNDARY)
        assert state.matches == []
        assert state.current_index == 0
        assert isinstance(state.text_cache, SearchTextCache)

    def test_property_proxy_round_trip(self):
        """Identity fields round-trip through store."""
        import cc_dump.app.view_store
        store = cc_dump.app.view_store.create()
        state = SearchState(store)

        state.phase = SearchPhase.NAVIGATING
        assert state.phase == SearchPhase.NAVIGATING
        assert store.get("search:phase") == "navigating"

        state.query = "hello"
        assert state.query == "hello"
        assert store.get("search:query") == "hello"

        state.modes = SearchMode.CASE_INSENSITIVE | SearchMode.WORD_BOUNDARY
        assert state.modes == SearchMode.CASE_INSENSITIVE | SearchMode.WORD_BOUNDARY
        assert store.get("search:modes") == int(SearchMode.CASE_INSENSITIVE | SearchMode.WORD_BOUNDARY)

        state.cursor_pos = 7
        assert state.cursor_pos == 7
        assert store.get("search:cursor_pos") == 7


# ─── Hierarchy walking ────────────────────────────────────────────────────────


class TestFindAllMatchesHierarchy:
    """Test that find_all_matches walks container children."""

    def test_walks_message_block_children(self):
        """Content inside a MessageBlock's children is searchable."""
        child_text = TextContentBlock(content="findme inside container")
        container = MessageBlock(role="user", msg_index=0, children=[child_text])
        turns = [_FakeTurnData(0, [container])]
        pattern = re.compile("findme")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 1
        assert matches[0].block_index == 0  # parent container's hierarchical index
        assert matches[0].block is child_text  # actual child block reference

    def test_walks_grandchildren(self):
        """ToolDefsSection → ToolDefBlock → SkillDefChild is searchable."""
        skill = SkillDefChild(name="review-pr", description="Code review helper")
        tool_def = ToolDefBlock(name="Skill", description="Skills", children=[skill])
        section = ToolDefsSection(tool_count=1, children=[tool_def])
        turns = [_FakeTurnData(0, [section])]
        pattern = re.compile("review-pr")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 1
        assert matches[0].block is skill
        assert matches[0].block_index == 0  # section's hierarchical index

    def test_container_itself_is_searchable(self):
        """ToolDefBlock's own text is searchable alongside children."""
        skill = SkillDefChild(name="review", description="Code review")
        tool_def = ToolDefBlock(name="Bash", description="Run commands", children=[skill])
        section = ToolDefsSection(tool_count=1, children=[tool_def])
        turns = [_FakeTurnData(0, [section])]
        pattern = re.compile("Bash")
        matches = find_all_matches(turns, pattern)
        # Should find "Bash" in the ToolDefBlock itself
        assert any(m.block is tool_def for m in matches)

    def test_block_reference_stored(self):
        """SearchMatch.block stores the correct block reference for identity lookup."""
        block = TextContentBlock(content="unique text here")
        turns = [_FakeTurnData(0, [block])]
        pattern = re.compile("unique")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 1
        assert matches[0].block is block

    def test_child_and_sibling_both_found(self):
        """Matches in both a container child and a sibling top-level block."""
        child = TextContentBlock(content="match in child")
        container = MessageBlock(role="user", msg_index=0, children=[child])
        sibling = TextContentBlock(content="match in sibling")
        turns = [_FakeTurnData(0, [container, sibling])]
        pattern = re.compile("match")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 2
        match_blocks = [m.block for m in matches]
        assert any(b is child for b in match_blocks)
        assert any(b is sibling for b in match_blocks)

    def test_hierarchical_index_is_container_for_children(self):
        """Children use the parent container's index, not their own flat position."""
        child1 = TextContentBlock(content="first child match")
        child2 = TextContentBlock(content="second child match")
        container = MessageBlock(role="user", msg_index=0, children=[child1, child2])
        header = HeaderBlock(label="REQUEST #1", timestamp="now")
        turns = [_FakeTurnData(0, [header, container])]
        pattern = re.compile("child match")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 2
        # Both children should have block_index=1 (the container's hierarchical index)
        assert all(m.block_index == 1 for m in matches)

    def test_recursive_depth_beyond_grandchildren(self):
        """Recursive walk finds matches at depth > 2 (great-grandchildren).

        Tree: MessageBlock → ToolDefsSection → ToolDefBlock → SkillDefChild
        The old 2-level walk would miss the SkillDefChild at depth 3.
        """
        skill = SkillDefChild(name="deep-skill", description="deeply nested")
        tool_def = ToolDefBlock(name="Task", description="Tasks", children=[skill])
        section = ToolDefsSection(tool_count=1, children=[tool_def])
        container = MessageBlock(role="user", msg_index=0, children=[section])
        turns = [_FakeTurnData(0, [container])]
        pattern = re.compile("deep-skill")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 1
        assert matches[0].block is skill
        assert matches[0].block_index == 0  # top-level container's index

    def test_config_and_thinking_blocks_searchable(self):
        """ConfigContentBlock and ThinkingBlock are searchable as children."""
        config = ConfigContentBlock(content="CLAUDE.md project instructions")
        thinking = ThinkingBlock(content="Let me think about this")
        container = MessageBlock(role="user", msg_index=0, children=[config, thinking])
        turns = [_FakeTurnData(0, [container])]

        pattern = re.compile("CLAUDE.md")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 1
        assert matches[0].block is config

        pattern2 = re.compile("think about")
        matches2 = find_all_matches(turns, pattern2)
        assert len(matches2) == 1
        assert matches2[0].block is thinking


# ─── Identity matching in SearchContext ──────────────────────────────────────


class TestSearchContextIdentityMatching:
    """Test matches_in_block with identity-based matching."""

    def test_identity_matching(self):
        """When block param is provided, matches by identity not index."""
        block_a = TextContentBlock(content="hello")
        block_b = TextContentBlock(content="world")
        matches = [
            SearchMatch(turn_index=0, block_index=0, text_offset=0, text_length=5, block=block_a),
            SearchMatch(turn_index=0, block_index=0, text_offset=0, text_length=5, block=block_b),
        ]
        ctx = SearchContext(
            pattern=re.compile("test"),
            pattern_str="test",
            current_match=matches[0],
            all_matches=matches,
        )
        # Same block_index=0 for both, but identity separates them
        result_a = ctx.matches_in_block(0, 0, block=block_a)
        assert len(result_a) == 1
        assert result_a[0].block is block_a

        result_b = ctx.matches_in_block(0, 0, block=block_b)
        assert len(result_b) == 1
        assert result_b[0].block is block_b

    def test_index_fallback_without_block(self):
        """Without block param, falls back to index matching."""
        matches = [
            SearchMatch(turn_index=0, block_index=0, text_offset=0, text_length=5, block=object()),
            SearchMatch(turn_index=0, block_index=1, text_offset=0, text_length=5, block=object()),
        ]
        ctx = SearchContext(
            pattern=re.compile("test"),
            pattern_str="test",
            current_match=matches[0],
            all_matches=matches,
        )
        result = ctx.matches_in_block(0, 0)
        assert len(result) == 1
        assert result[0].block_index == 0
