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


class TestGetSearchableText:
    """Test text extraction from all block types."""

    def test_header_block(self):
        block = HeaderBlock(label="REQUEST #1", timestamp="1:23:45 PM")
        assert "REQUEST #1" in get_searchable_text(block)
        assert "1:23:45 PM" in get_searchable_text(block)

    def test_http_headers_block(self):
        block = HttpHeadersBlock(headers={"content-type": "application/json"})
        text = get_searchable_text(block)
        assert "content-type" in text
        assert "application/json" in text

    def test_metadata_block(self):
        block = MetadataBlock(model="claude-sonnet-4-5-20250929", max_tokens="8192")
        text = get_searchable_text(block)
        assert "claude-sonnet-4-5-20250929" in text
        assert "8192" in text

    def test_system_label_block(self):
        assert get_searchable_text(SystemLabelBlock()) == "SYSTEM:"

    def test_tracked_content_new(self):
        block = TrackedContentBlock(status="new", content="hello world")
        assert get_searchable_text(block) == "hello world"

    def test_tracked_content_changed(self):
        block = TrackedContentBlock(
            status="changed", new_content="new stuff", old_content="old"
        )
        assert get_searchable_text(block) == "new stuff"

    def test_tracked_content_ref(self):
        block = TrackedContentBlock(status="ref")
        assert get_searchable_text(block) == ""

    def test_role_block(self):
        block = RoleBlock(role="assistant")
        assert get_searchable_text(block) == "assistant"

    def test_text_content_block(self):
        block = TextContentBlock(text="Hello, how can I help?")
        assert get_searchable_text(block) == "Hello, how can I help?"

    def test_tool_use_block(self):
        block = ToolUseBlock(name="Read", detail="/path/to/file.py")
        text = get_searchable_text(block)
        assert "Read" in text
        assert "/path/to/file.py" in text

    def test_tool_result_block(self):
        block = ToolResultBlock(tool_name="Bash", detail="ls -la")
        text = get_searchable_text(block)
        assert "Bash" in text
        assert "ls -la" in text

    def test_tool_use_summary_block(self):
        block = ToolUseSummaryBlock(tool_counts={"Read": 3, "Bash": 2}, total=5)
        text = get_searchable_text(block)
        assert "Read" in text
        assert "Bash" in text

    def test_image_block(self):
        block = ImageBlock(media_type="image/png")
        assert "image/png" in get_searchable_text(block)

    def test_stream_info_block(self):
        block = StreamInfoBlock(model="claude-sonnet-4-5-20250929")
        assert "claude-sonnet-4-5-20250929" in get_searchable_text(block)

    def test_stream_tool_use_block(self):
        block = StreamToolUseBlock(name="Read")
        assert get_searchable_text(block) == "Read"

    def test_text_delta_block(self):
        block = TextDeltaBlock(text="streaming text")
        assert get_searchable_text(block) == "streaming text"

    def test_stop_reason_block(self):
        block = StopReasonBlock(reason="end_turn")
        assert "end_turn" in get_searchable_text(block)

    def test_error_block(self):
        block = ErrorBlock(code=429, reason="rate_limited")
        text = get_searchable_text(block)
        assert "429" in text
        assert "rate_limited" in text

    def test_proxy_error_block(self):
        block = ProxyErrorBlock(error="connection refused")
        assert "connection refused" in get_searchable_text(block)

    def test_newline_block(self):
        assert get_searchable_text(NewlineBlock()) == ""

    def test_separator_block(self):
        assert get_searchable_text(SeparatorBlock()) == ""

    def test_turn_budget_block(self):
        budget = TurnBudget(total_est=50000)
        block = TurnBudgetBlock(budget=budget)
        assert "50000" in get_searchable_text(block)

    def test_unknown_type_block(self):
        block = UnknownTypeBlock(block_type="thinking")
        assert get_searchable_text(block) == "thinking"


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
