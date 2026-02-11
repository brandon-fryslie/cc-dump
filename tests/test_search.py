"""Unit tests for cc_dump.tui.search module."""

import re

import pytest

from cc_dump.tui.search import (
    SearchMode,
    SearchPhase,
    SearchMatch,
    SearchContext,
    SearchState,
    get_searchable_text,
    compile_search_pattern,
    find_all_matches,
)
from cc_dump.formatting import (
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
    SeparatorBlock,
    Category,
)
from cc_dump.analysis import TurnBudget


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
        SystemLabelBlock(),
        ["SYSTEM:"],
        id="system_label",
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
        RoleBlock(role="assistant"),
        ["assistant"],
        id="role",
    ),
    pytest.param(
        TextContentBlock(text="Hello, how can I help?"),
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
        TextDeltaBlock(text="streaming text"),
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
        ["50000"],
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
        blocks = [TextContentBlock(text="hello test world")]
        turns = [_FakeTurnData(0, blocks)]
        pattern = re.compile("test")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 1
        assert matches[0].turn_index == 0
        assert matches[0].block_index == 0
        assert matches[0].text_offset == 6
        assert matches[0].text_length == 4

    def test_multiple_matches_in_block(self):
        blocks = [TextContentBlock(text="test one test two test three")]
        turns = [_FakeTurnData(0, blocks)]
        pattern = re.compile("test")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 3
        # Bottom-up within block: last match first
        assert matches[0].text_offset > matches[1].text_offset
        assert matches[1].text_offset > matches[2].text_offset

    def test_bottom_up_turn_ordering(self):
        turns = [
            _FakeTurnData(0, [TextContentBlock(text="first turn match")]),
            _FakeTurnData(1, [TextContentBlock(text="second turn match")]),
        ]
        pattern = re.compile("match")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 2
        # Most recent turn (index 1) first
        assert matches[0].turn_index == 1
        assert matches[1].turn_index == 0

    def test_bottom_up_block_ordering(self):
        blocks = [
            TextContentBlock(text="block zero match"),
            TextContentBlock(text="block one match"),
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
            _FakeTurnData(0, [TextContentBlock(text="match")]),
            _FakeTurnData(1, [TextContentBlock(text="match")], is_streaming=True),
        ]
        pattern = re.compile("match")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 1
        assert matches[0].turn_index == 0

    def test_skips_empty_text_blocks(self):
        blocks = [
            NewlineBlock(),
            SeparatorBlock(),
            TextContentBlock(text="findme"),
        ]
        turns = [_FakeTurnData(0, blocks)]
        pattern = re.compile("findme")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 1
        assert matches[0].block_index == 2

    def test_no_matches(self):
        blocks = [TextContentBlock(text="hello world")]
        turns = [_FakeTurnData(0, blocks)]
        pattern = re.compile("nonexistent")
        matches = find_all_matches(turns, pattern)
        assert len(matches) == 0

    def test_case_insensitive_pattern(self):
        blocks = [TextContentBlock(text="Hello World")]
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
        state = SearchState()
        assert state.phase == SearchPhase.INACTIVE
        assert state.query == ""
        assert state.cursor_pos == 0
        assert state.modes & SearchMode.CASE_INSENSITIVE
        assert state.modes & SearchMode.REGEX
        assert state.modes & SearchMode.INCREMENTAL
        assert not (state.modes & SearchMode.WORD_BOUNDARY)
        assert state.matches == []
        assert state.current_index == 0
