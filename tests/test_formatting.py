"""Unit tests for formatting.py - block generation and content tracking."""

import pytest

from cc_dump.formatting import (
    ContentRegion,
    ErrorBlock,
    FormattedBlock,
    HeaderBlock,
    HttpHeadersBlock,
    ImageBlock,
    MetadataBlock,
    NewlineBlock,
    ProxyErrorBlock,
    RoleBlock,
    SeparatorBlock,
    StopReasonBlock,
    StreamInfoBlock,
    StreamToolUseBlock,
    SystemLabelBlock,
    TextContentBlock,
    TextDeltaBlock,
    ToolDefinitionsBlock,
    ToolResultBlock,
    ToolUseBlock,
    TrackedContentBlock,
    TurnBudgetBlock,
    UnknownTypeBlock,
    format_request,
    format_request_headers,
    format_response_event,
    format_response_headers,
    make_diff_lines,
    populate_content_regions,
    track_content,
    _tool_detail,
    _front_ellipse_path,
)
from cc_dump.event_types import parse_sse_event


# ─── format_request Tests ─────────────────────────────────────────────────────


def test_format_request_minimal(fresh_state):
    """Minimal request returns expected blocks."""
    body = {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "messages": [],
    }
    blocks = format_request(body, fresh_state)

    # Should have header, metadata, etc.
    assert len(blocks) > 0

    # Check for specific block types
    has_header = any(isinstance(b, HeaderBlock) for b in blocks)
    has_metadata = any(isinstance(b, MetadataBlock) for b in blocks)

    assert has_header
    assert has_metadata

    # Request counter should increment
    assert fresh_state["request_counter"] == 1


def test_format_request_with_system(fresh_state):
    """System prompt blocks included."""
    body = {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "system": "You are a helpful assistant.",
        "messages": [],
    }
    blocks = format_request(body, fresh_state)

    # Should have SystemLabelBlock
    has_system_label = any(isinstance(b, SystemLabelBlock) for b in blocks)
    assert has_system_label

    # Should have tracked content for system prompt
    has_tracked = any(isinstance(b, TrackedContentBlock) for b in blocks)
    assert has_tracked


def test_format_request_with_system_list(fresh_state):
    """System prompt as list of blocks handled."""
    body = {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "system": [
            {"text": "Block 1"},
            {"text": "Block 2"},
        ],
        "messages": [],
    }
    blocks = format_request(body, fresh_state)

    # Should have SystemLabelBlock
    has_system_label = any(isinstance(b, SystemLabelBlock) for b in blocks)
    assert has_system_label

    # Should have tracked content blocks
    tracked_blocks = [b for b in blocks if isinstance(b, TrackedContentBlock)]
    assert len(tracked_blocks) >= 2


def test_format_request_with_messages(fresh_state):
    """Message blocks included."""
    body = {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ],
    }
    blocks = format_request(body, fresh_state)

    # Should have RoleBlocks
    role_blocks = [b for b in blocks if isinstance(b, RoleBlock)]
    assert len(role_blocks) == 2
    assert role_blocks[0].role == "user"
    assert role_blocks[1].role == "assistant"

    # Should have TextContentBlocks
    text_blocks = [b for b in blocks if isinstance(b, TextContentBlock)]
    assert len(text_blocks) >= 2


def test_format_request_with_tool_use(fresh_state):
    """Tool use blocks formatted correctly."""
    body = {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "1",
                        "name": "get_weather",
                        "input": {"city": "NYC"},
                    },
                ],
            },
        ],
    }
    blocks = format_request(body, fresh_state)

    # Should have ToolUseBlock
    tool_blocks = [b for b in blocks if isinstance(b, ToolUseBlock)]
    assert len(tool_blocks) == 1
    assert tool_blocks[0].name == "get_weather"
    assert tool_blocks[0].input_size > 0


def test_format_request_with_tool_result(fresh_state):
    """Tool result blocks formatted correctly."""
    body = {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "1",
                        "content": "Result data",
                    },
                ],
            },
        ],
    }
    blocks = format_request(body, fresh_state)

    # Should have ToolResultBlock
    result_blocks = [b for b in blocks if isinstance(b, ToolResultBlock)]
    assert len(result_blocks) == 1
    assert result_blocks[0].size > 0
    assert result_blocks[0].is_error is False


def test_format_request_with_tool_result_error(fresh_state):
    """Tool result error flag preserved."""
    body = {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "1",
                        "content": "Error occurred",
                        "is_error": True,
                    },
                ],
            },
        ],
    }
    blocks = format_request(body, fresh_state)

    result_blocks = [b for b in blocks if isinstance(b, ToolResultBlock)]
    assert len(result_blocks) == 1
    assert result_blocks[0].is_error is True


def test_format_request_with_image(fresh_state):
    """Image blocks formatted correctly."""
    body = {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"media_type": "image/png"},
                    },
                ],
            },
        ],
    }
    blocks = format_request(body, fresh_state)

    image_blocks = [b for b in blocks if isinstance(b, ImageBlock)]
    assert len(image_blocks) == 1
    assert image_blocks[0].media_type == "image/png"


def test_format_request_with_unknown_type(fresh_state):
    """Unknown content types handled gracefully."""
    body = {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "unknown_type", "data": "something"},
                ],
            },
        ],
    }
    blocks = format_request(body, fresh_state)

    unknown_blocks = [b for b in blocks if isinstance(b, UnknownTypeBlock)]
    assert len(unknown_blocks) == 1
    assert unknown_blocks[0].block_type == "unknown_type"


# ─── format_response_event Tests ──────────────────────────────────────────────


def test_format_response_event_message_start():
    """message_start creates StreamInfoBlock."""
    sse = parse_sse_event("message_start", {
        "message": {
            "model": "claude-3-opus-20240229",
        },
    })
    blocks = format_response_event(sse)

    assert len(blocks) == 1
    assert isinstance(blocks[0], StreamInfoBlock)
    assert blocks[0].model == "claude-3-opus-20240229"


def test_format_response_event_content_block_start_tool():
    """content_block_start with tool_use creates StreamToolUseBlock."""
    sse = parse_sse_event("content_block_start", {
        "content_block": {
            "type": "tool_use",
            "name": "read_file",
        },
    })
    blocks = format_response_event(sse)

    assert len(blocks) == 1
    assert isinstance(blocks[0], StreamToolUseBlock)
    assert blocks[0].name == "read_file"


def test_format_response_event_content_block_start_text():
    """content_block_start with text returns empty (no block needed)."""
    sse = parse_sse_event("content_block_start", {
        "content_block": {
            "type": "text",
        },
    })
    blocks = format_response_event(sse)
    assert len(blocks) == 0


def test_format_response_event_content_block_delta():
    """content_block_delta creates TextDeltaBlock."""
    sse = parse_sse_event("content_block_delta", {
        "delta": {
            "type": "text_delta",
            "text": "Hello",
        },
    })
    blocks = format_response_event(sse)

    assert len(blocks) == 1
    assert isinstance(blocks[0], TextDeltaBlock)
    assert blocks[0].content == "Hello"


def test_format_response_event_content_block_delta_empty():
    """content_block_delta with empty text returns empty list."""
    sse = parse_sse_event("content_block_delta", {
        "delta": {
            "type": "text_delta",
            "text": "",
        },
    })
    blocks = format_response_event(sse)
    assert len(blocks) == 0


def test_format_response_event_message_delta():
    """message_delta with stop_reason creates StopReasonBlock."""
    sse = parse_sse_event("message_delta", {
        "delta": {
            "stop_reason": "end_turn",
        },
    })
    blocks = format_response_event(sse)

    assert len(blocks) == 1
    assert isinstance(blocks[0], StopReasonBlock)
    assert blocks[0].reason == "end_turn"


def test_format_response_event_message_delta_no_stop():
    """message_delta without stop_reason returns empty list."""
    sse = parse_sse_event("message_delta", {
        "delta": {},
    })
    blocks = format_response_event(sse)
    assert len(blocks) == 0


def test_format_response_event_message_stop():
    """message_stop returns empty list."""
    sse = parse_sse_event("message_stop", {})
    blocks = format_response_event(sse)
    assert len(blocks) == 0


# ─── HTTP Headers Tests ───────────────────────────────────────────────────────


def test_format_request_headers_empty():
    """Empty headers dict creates HttpHeadersBlock with empty dict."""
    blocks = format_request_headers({})
    assert len(blocks) == 1
    assert isinstance(blocks[0], HttpHeadersBlock)
    assert blocks[0].headers == {}


def test_format_request_headers_with_headers():
    """Request headers formatted as HttpHeadersBlock."""
    headers = {"Content-Type": "application/json", "User-Agent": "test/1.0"}
    blocks = format_request_headers(headers)

    assert len(blocks) == 1
    assert isinstance(blocks[0], HttpHeadersBlock)
    assert blocks[0].headers == headers
    assert blocks[0].header_type == "request"
    assert blocks[0].status_code == 0


def test_format_response_headers_empty():
    """Empty headers dict still emits HeaderBlock + HttpHeadersBlock (status code is informative)."""
    blocks = format_response_headers(200, {})
    assert len(blocks) == 2
    assert isinstance(blocks[0], HeaderBlock)
    assert blocks[0].header_type == "response"
    assert blocks[0].label == "RESPONSE"
    assert isinstance(blocks[1], HttpHeadersBlock)
    assert blocks[1].headers == {}
    assert blocks[1].status_code == 200


def test_format_response_headers_with_headers():
    """Response headers formatted as HeaderBlock + HttpHeadersBlock with status code."""
    headers = {"Content-Type": "text/event-stream", "x-request-id": "abc123"}
    blocks = format_response_headers(200, headers)

    assert len(blocks) == 2
    assert isinstance(blocks[0], HeaderBlock)
    assert blocks[0].header_type == "response"
    assert isinstance(blocks[1], HttpHeadersBlock)
    assert blocks[1].headers == headers
    assert blocks[1].header_type == "response"
    assert blocks[1].status_code == 200


def test_http_headers_block_instantiation():
    """HttpHeadersBlock can be instantiated with all fields."""
    block = HttpHeadersBlock(
        headers={"key": "value"},
        header_type="request",
        status_code=404
    )
    assert block.headers == {"key": "value"}
    assert block.header_type == "request"
    assert block.status_code == 404


def test_http_headers_block_defaults():
    """HttpHeadersBlock has correct default values."""
    block = HttpHeadersBlock()
    assert block.headers == {}
    assert block.header_type == "request"
    assert block.status_code == 0


# ─── track_content Tests ──────────────────────────────────────────────────────


def test_track_content_new(fresh_state):
    """First occurrence tagged 'new'."""
    result = track_content("Hello world", "system:0", fresh_state)

    assert isinstance(result, TrackedContentBlock)
    assert result.status == "new"
    assert result.tag_id.startswith("sp-")
    assert isinstance(result.color_idx, int)
    assert result.content == "Hello world"

    # State should be updated
    assert "system:0" in fresh_state["positions"]
    assert fresh_state["next_id"] == 1


def test_track_content_ref(fresh_state):
    """Second occurrence of same content tagged 'ref'."""
    # First call
    track_content("Hello", "system:0", fresh_state)

    # Second call with same content at different position
    result = track_content("Hello", "msg:1", fresh_state)

    assert isinstance(result, TrackedContentBlock)
    assert result.status == "ref"
    assert result.tag_id.startswith("sp-")
    assert isinstance(result.color_idx, int)


def test_track_content_changed(fresh_state):
    """Modified content at same position tagged 'changed'."""
    # First call
    track_content("Original", "system:0", fresh_state)

    # Second call with different content at same position
    result = track_content("Modified", "system:0", fresh_state)

    assert isinstance(result, TrackedContentBlock)
    assert result.status == "changed"
    assert result.tag_id.startswith("sp-")
    assert isinstance(result.color_idx, int)
    assert result.old_content == "Original"
    assert result.new_content == "Modified"


def test_track_content_multiple_positions_same_content(fresh_state):
    """Same content at multiple positions shares tag."""
    result1 = track_content("Shared", "pos:1", fresh_state)
    result2 = track_content("Shared", "pos:2", fresh_state)

    # First is new
    assert isinstance(result1, TrackedContentBlock)
    assert result1.status == "new"
    tag_id_1 = result1.tag_id

    # Second is ref to same tag
    assert isinstance(result2, TrackedContentBlock)
    assert result2.status == "ref"
    tag_id_2 = result2.tag_id

    assert tag_id_1 == tag_id_2


# ─── make_diff_lines Tests ────────────────────────────────────────────────────


def test_make_diff_lines_no_change():
    """Empty diff for identical content."""
    old = "Hello\nWorld"
    new = "Hello\nWorld"

    diff_lines = make_diff_lines(old, new)

    # No changes means no diff output (after filtering header lines)
    assert len(diff_lines) == 0


def test_make_diff_lines_with_changes():
    """Proper diff output for changes."""
    old = "Hello\nWorld\nFoo"
    new = "Hello\nEarth\nFoo"

    diff_lines = make_diff_lines(old, new)

    # Should have changes
    assert len(diff_lines) > 0

    # Check for hunk marker, deletions, and additions
    kinds = [kind for kind, _ in diff_lines]
    assert "hunk" in kinds or "del" in kinds or "add" in kinds


def test_make_diff_lines_addition():
    """Addition detected in diff."""
    old = "Line 1"
    new = "Line 1\nLine 2"

    diff_lines = make_diff_lines(old, new)

    # Should have addition
    kinds = [kind for kind, _ in diff_lines]
    assert "add" in kinds


def test_make_diff_lines_deletion():
    """Deletion detected in diff."""
    old = "Line 1\nLine 2"
    new = "Line 1"

    diff_lines = make_diff_lines(old, new)

    # Should have deletion
    kinds = [kind for kind, _ in diff_lines]
    assert "del" in kinds


def test_make_diff_lines_format():
    """Diff lines are (kind, text) tuples."""
    old = "A"
    new = "B"

    diff_lines = make_diff_lines(old, new)

    # Each line should be a tuple
    for item in diff_lines:
        assert isinstance(item, tuple)
        assert len(item) == 2
        kind, text = item
        assert kind in ("hunk", "add", "del")
        assert isinstance(text, str)


# ─── Block Instantiation Tests ────────────────────────────────────────────────


def test_block_types_can_be_instantiated():
    """All block types can be instantiated with expected fields."""

    # Test a sampling of block types
    assert isinstance(SeparatorBlock(style="heavy"), FormattedBlock)
    assert isinstance(HeaderBlock(label="TEST"), FormattedBlock)
    assert isinstance(HttpHeadersBlock(headers={"key": "value"}), FormattedBlock)
    assert isinstance(MetadataBlock(model="claude"), FormattedBlock)
    assert isinstance(SystemLabelBlock(), FormattedBlock)
    assert isinstance(RoleBlock(role="user"), FormattedBlock)
    assert isinstance(TextContentBlock(content="Hello"), FormattedBlock)
    assert isinstance(ToolUseBlock(name="tool"), FormattedBlock)
    assert isinstance(ToolResultBlock(size=100), FormattedBlock)
    assert isinstance(ImageBlock(media_type="image/png"), FormattedBlock)
    assert isinstance(UnknownTypeBlock(block_type="unknown"), FormattedBlock)
    assert isinstance(StreamInfoBlock(model="claude"), FormattedBlock)
    assert isinstance(StreamToolUseBlock(name="tool"), FormattedBlock)
    assert isinstance(TextDeltaBlock(content="delta"), FormattedBlock)
    assert isinstance(StopReasonBlock(reason="end_turn"), FormattedBlock)
    assert isinstance(ErrorBlock(code=500), FormattedBlock)
    assert isinstance(ProxyErrorBlock(error="error"), FormattedBlock)
    assert isinstance(NewlineBlock(), FormattedBlock)
    assert isinstance(TrackedContentBlock(status="new"), FormattedBlock)
    assert isinstance(TurnBudgetBlock(), FormattedBlock)


def test_tracked_content_block_fields():
    """TrackedContentBlock has expected fields."""
    block = TrackedContentBlock(
        status="new",
        tag_id="sp-1",
        color_idx=0,
        content="test",
        indent="  ",
    )

    assert block.status == "new"
    assert block.tag_id == "sp-1"
    assert block.color_idx == 0
    assert block.content == "test"
    assert block.indent == "  "


# ─── Integration Tests ────────────────────────────────────────────────────────


def test_format_request_multiple_calls_increment_counter(fresh_state):
    """Multiple format_request calls increment request counter."""
    body = {"model": "claude", "max_tokens": 100, "messages": []}

    format_request(body, fresh_state)
    assert fresh_state["request_counter"] == 1

    format_request(body, fresh_state)
    assert fresh_state["request_counter"] == 2

    format_request(body, fresh_state)
    assert fresh_state["request_counter"] == 3


def test_content_tracking_preserves_color_across_refs(fresh_state):
    """Content tracking preserves color index across references."""
    # Track content first time
    result1 = track_content("Shared content", "pos:1", fresh_state)
    color1 = result1.color_idx

    # Track same content at different position
    result2 = track_content("Shared content", "pos:2", fresh_state)
    color2 = result2.color_idx

    # Should have same color
    assert color1 == color2


# ─── Tool Detail Tests ────────────────────────────────────────────────────────


TOOL_DETAIL_EXACT_CASES = [
    pytest.param("Read", {}, "", id="read_no_path"),
    pytest.param("Read", {"file_path": "/a/b.ts"}, "/a/b.ts", id="read_very_short"),
    pytest.param("Skill", {"skill": "commit"}, "commit", id="skill_name"),
    pytest.param("Skill", {}, "", id="skill_no_name"),
    pytest.param("Bash", {"command": "git status"}, "git status", id="bash_command"),
    pytest.param("Bash", {}, "", id="bash_no_command"),
    pytest.param("WebSearch", {"query": "test"}, "", id="unknown_tool"),
]


class TestToolDetail:
    """Tests for _tool_detail helper function."""

    @pytest.mark.parametrize("tool_name,input_dict,expected", TOOL_DETAIL_EXACT_CASES)
    def test_tool_detail_exact(self, tool_name, input_dict, expected):
        """Test exact-match tool detail extraction."""
        assert _tool_detail(tool_name, input_dict) == expected

    def test_read_with_long_file_path(self):
        """Read tool extracts and ellipses long file path."""
        result = _tool_detail("Read", {"file_path": "/Users/foo/bar/baz/very/deep/nested/directory/file.ts"})
        assert "file.ts" in result
        assert result.startswith("...")

    def test_read_short_path_no_ellipsis(self):
        """Read tool with short path returns it unchanged."""
        result = _tool_detail("Read", {"file_path": "/Users/foo/bar/baz/file.ts"})
        assert result == "/Users/foo/bar/baz/file.ts"
        assert not result.startswith("...")

    def test_bash_multiline(self):
        """Bash tool extracts only first line of multiline command."""
        result = _tool_detail("Bash", {"command": "line1\nline2"})
        assert result == "line1"

    def test_bash_truncation(self):
        """Bash tool truncates long commands."""
        long_cmd = "x" * 100
        result = _tool_detail("Bash", {"command": long_cmd})
        assert len(result) <= 60
        assert result.endswith("...")

    def test_mcp_read_tool(self):
        """MCP Read tool also extracts file path."""
        result = _tool_detail(
            "mcp__plugin_repomix-mcp_repomix__file_system_read_file",
            {"file_path": "/Users/foo/bar/baz/very/deep/nested/directory/file.ts"}
        )
        assert "file.ts" in result
        assert result.startswith("...")


class TestFrontEllipsePath:
    """Tests for _front_ellipse_path helper function."""

    def test_short_path_unchanged(self):
        """Short paths are returned unchanged."""
        assert _front_ellipse_path("/a/b.ts", max_len=40) == "/a/b.ts"

    def test_long_path_ellipsed(self):
        """Long paths are front-ellipsed."""
        result = _front_ellipse_path("/Users/foo/code/project/src/deep/file.ts", max_len=30)
        assert result.startswith("...")
        assert result.endswith("file.ts")
        assert len(result) <= 33  # max_len + "..."

    def test_path_at_limit(self):
        """Path exactly at max_len is unchanged."""
        path = "a" * 40
        result = _front_ellipse_path(path, max_len=40)
        assert result == path

    def test_very_long_filename(self):
        """Very long filename gets ellipsed."""
        long_filename = "x" * 100
        result = _front_ellipse_path("/" + long_filename, max_len=40)
        assert result.startswith("...")
        assert len(result) <= 43

    def test_empty_path(self):
        """Empty path returns empty string (shorter than max_len)."""
        result = _front_ellipse_path("", max_len=40)
        # Empty string split on "/" gives [""], so we get "..." prepended to empty
        assert result == ""

    def test_root_path(self):
        """Root path handled correctly."""
        result = _front_ellipse_path("/", max_len=40)
        assert result == "/"


class TestToolUseBlockDetail:
    """Tests for ToolUseBlock detail field."""

    def test_tool_use_block_with_detail(self):
        """ToolUseBlock can be created with detail."""
        block = ToolUseBlock(name="Read", input_size=100, msg_color_idx=0, detail="...path/file.ts")
        assert block.name == "Read"
        assert block.input_size == 100
        assert block.msg_color_idx == 0
        assert block.detail == "...path/file.ts"

    def test_tool_use_block_without_detail(self):
        """ToolUseBlock can be created without detail (defaults to empty)."""
        block = ToolUseBlock(name="Read", input_size=100, msg_color_idx=0)
        assert block.detail == ""

    def test_format_request_populates_read_detail_long_path(self, fresh_state):
        """format_request populates detail for Read tool with long path."""
        body = {
            "model": "claude-3-opus",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "1",
                            "name": "Read",
                            "input": {"file_path": "/Users/foo/bar/baz/very/deep/nested/directory/file.ts"},
                        },
                    ],
                },
            ],
        }
        blocks = format_request(body, fresh_state)
        tool_blocks = [b for b in blocks if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 1
        assert "file.ts" in tool_blocks[0].detail
        assert tool_blocks[0].detail.startswith("...")

    def test_format_request_populates_read_detail_short_path(self, fresh_state):
        """format_request populates detail for Read tool with short path (no ellipsis)."""
        body = {
            "model": "claude-3-opus",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "1",
                            "name": "Read",
                            "input": {"file_path": "/a/b.ts"},
                        },
                    ],
                },
            ],
        }
        blocks = format_request(body, fresh_state)
        tool_blocks = [b for b in blocks if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].detail == "/a/b.ts"

    def test_format_request_populates_skill_detail(self, fresh_state):
        """format_request populates detail for Skill tool."""
        body = {
            "model": "claude-3-opus",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "1",
                            "name": "Skill",
                            "input": {"skill": "commit"},
                        },
                    ],
                },
            ],
        }
        blocks = format_request(body, fresh_state)
        tool_blocks = [b for b in blocks if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].detail == "commit"

    def test_format_request_populates_bash_detail(self, fresh_state):
        """format_request populates detail for Bash tool."""
        body = {
            "model": "claude-3-opus",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "1",
                            "name": "Bash",
                            "input": {"command": "git status"},
                        },
                    ],
                },
            ],
        }
        blocks = format_request(body, fresh_state)
        tool_blocks = [b for b in blocks if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].detail == "git status"

    def test_format_request_unknown_tool_empty_detail(self, fresh_state):
        """format_request sets empty detail for unknown tools."""
        body = {
            "model": "claude-3-opus",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "1",
                            "name": "UnknownTool",
                            "input": {"anything": "value"},
                        },
                    ],
                },
            ],
        }
        blocks = format_request(body, fresh_state)
        tool_blocks = [b for b in blocks if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].detail == ""


# ─── Tool Correlation Tests ───────────────────────────────────────────────────


class TestToolCorrelation:
    """Tests for tool_use_id correlation between ToolUseBlock and ToolResultBlock."""

    def test_tool_use_id_populated(self, fresh_state):
        """ToolUseBlock and ToolResultBlock have tool_use_id populated."""
        body = {
            "model": "claude-3-opus",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "tu_123", "name": "Read", "input": {"file_path": "/a.txt"}},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tu_123", "content": "file contents"},
                    ],
                },
            ],
        }
        blocks = format_request(body, fresh_state)
        tool_uses = [b for b in blocks if isinstance(b, ToolUseBlock)]
        tool_results = [b for b in blocks if isinstance(b, ToolResultBlock)]

        assert len(tool_uses) == 1
        assert len(tool_results) == 1
        assert tool_uses[0].tool_use_id == "tu_123"
        assert tool_results[0].tool_use_id == "tu_123"

    def test_tool_result_name_populated(self, fresh_state):
        """ToolResultBlock has tool_name populated from matching ToolUseBlock."""
        body = {
            "model": "claude-3-opus",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "tu_123", "name": "Read", "input": {"file_path": "/a.txt"}},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tu_123", "content": "file contents"},
                    ],
                },
            ],
        }
        blocks = format_request(body, fresh_state)
        tool_results = [b for b in blocks if isinstance(b, ToolResultBlock)]

        assert len(tool_results) == 1
        assert tool_results[0].tool_name == "Read"

    def test_tool_result_detail_populated(self, fresh_state):
        """ToolResultBlock has detail copied from matching ToolUseBlock."""
        body = {
            "model": "claude-3-opus",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "tu_123", "name": "Read", "input": {"file_path": "/Users/foo/bar/baz/very/deep/nested/directory/file.ts"}},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tu_123", "content": "file contents"},
                    ],
                },
            ],
        }
        blocks = format_request(body, fresh_state)
        tool_results = [b for b in blocks if isinstance(b, ToolResultBlock)]

        assert len(tool_results) == 1
        assert tool_results[0].detail != ""
        assert "file.ts" in tool_results[0].detail

    def test_color_correlation(self, fresh_state):
        """Matching ToolUseBlock and ToolResultBlock share the same msg_color_idx."""
        body = {
            "model": "claude-3-opus",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {}},
                        {"type": "tool_use", "id": "tu_2", "name": "Bash", "input": {}},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tu_1", "content": "r1"},
                        {"type": "tool_result", "tool_use_id": "tu_2", "content": "r2"},
                    ],
                },
            ],
        }
        blocks = format_request(body, fresh_state)
        uses = {b.tool_use_id: b for b in blocks if isinstance(b, ToolUseBlock)}
        results = {b.tool_use_id: b for b in blocks if isinstance(b, ToolResultBlock)}

        # Matching pairs share color
        assert uses["tu_1"].msg_color_idx == results["tu_1"].msg_color_idx
        assert uses["tu_2"].msg_color_idx == results["tu_2"].msg_color_idx

        # Different pairs have different colors
        assert uses["tu_1"].msg_color_idx != uses["tu_2"].msg_color_idx

    def test_color_assignment_deterministic(self, fresh_state):
        """Same request produces same color assignments."""
        body = {
            "model": "claude-3-opus",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {}},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tu_1", "content": "r1"},
                    ],
                },
            ],
        }

        # Format twice
        blocks1 = format_request(body, fresh_state)
        uses1 = [b for b in blocks1 if isinstance(b, ToolUseBlock)]

        # Reset state but format again
        fresh_state["request_counter"] = 0
        blocks2 = format_request(body, fresh_state)
        uses2 = [b for b in blocks2 if isinstance(b, ToolUseBlock)]

        # Should have same color
        assert uses1[0].msg_color_idx == uses2[0].msg_color_idx

    def test_missing_tool_use_fallback(self, fresh_state):
        """ToolResultBlock without matching ToolUseBlock uses fallback color."""
        body = {
            "model": "claude-3-opus",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "missing_id", "content": "result"},
                    ],
                },
            ],
        }
        blocks = format_request(body, fresh_state)
        tool_results = [b for b in blocks if isinstance(b, ToolResultBlock)]

        assert len(tool_results) == 1
        # Should have tool_use_id set but tool_name empty
        assert tool_results[0].tool_use_id == "missing_id"
        assert tool_results[0].tool_name == ""
        # Should have a color assigned (fallback to message color)
        assert isinstance(tool_results[0].msg_color_idx, int)

    def test_default_fields_work(self, fresh_state):
        """Existing code creating blocks without new fields works with defaults."""
        # ToolUseBlock without tool_use_id
        block1 = ToolUseBlock(name="Read", input_size=100, msg_color_idx=0)
        assert block1.tool_use_id == ""
        assert block1.description == ""

        # ToolResultBlock without new fields
        block2 = ToolResultBlock(size=500, is_error=False, msg_color_idx=0)
        assert block2.tool_use_id == ""
        assert block2.tool_name == ""
        assert block2.detail == ""


# ─── ToolDefinitionsBlock Tests ──────────────────────────────────────────────


def _make_body_with_tools(tools):
    """Helper: build a request body with the given tool definitions."""
    return {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "tools": tools,
        "messages": [],
    }


SAMPLE_TOOLS = [
    {
        "name": "Read",
        "description": "Read a file from disk",
        "input_schema": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
    },
    {
        "name": "Write",
        "description": "Write content to a file",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["file_path", "content"],
        },
    },
]


class TestToolDefinitionsBlock:
    """Tests for ToolDefinitionsBlock creation and fields."""

    def test_tool_definitions_block_created(self, fresh_state):
        """ToolDefinitionsBlock created when tools present."""
        body = _make_body_with_tools(SAMPLE_TOOLS)
        blocks = format_request(body, fresh_state)
        tool_def_blocks = [b for b in blocks if isinstance(b, ToolDefinitionsBlock)]
        assert len(tool_def_blocks) == 1
        tdb = tool_def_blocks[0]
        assert len(tdb.tools) == 2
        assert tdb.tools[0]["name"] == "Read"
        assert tdb.tools[1]["name"] == "Write"

    def test_tool_definitions_block_token_estimates(self, fresh_state):
        """ToolDefinitionsBlock has per-tool token estimates."""
        body = _make_body_with_tools(SAMPLE_TOOLS)
        blocks = format_request(body, fresh_state)
        tdb = [b for b in blocks if isinstance(b, ToolDefinitionsBlock)][0]
        assert len(tdb.tool_tokens) == 2
        assert all(t > 0 for t in tdb.tool_tokens)
        assert tdb.total_tokens == sum(tdb.tool_tokens)

    def test_tool_definitions_block_content_regions(self, fresh_state):
        """ToolDefinitionsBlock has pre-populated content_regions with kind and tags."""
        body = _make_body_with_tools(SAMPLE_TOOLS)
        blocks = format_request(body, fresh_state)
        tdb = [b for b in blocks if isinstance(b, ToolDefinitionsBlock)][0]
        assert len(tdb.content_regions) == 2
        assert all(isinstance(r, ContentRegion) for r in tdb.content_regions)
        # Default collapsed
        assert all(r.expanded is False for r in tdb.content_regions)
        assert tdb.content_regions[0].index == 0
        assert tdb.content_regions[1].index == 1
        # kind and tags
        assert all(r.kind == "tool_def" for r in tdb.content_regions)
        assert tdb.content_regions[0].tags == ["Read"]
        assert tdb.content_regions[1].tags == ["Write"]

    def test_tool_definitions_block_with_empty_tools(self, fresh_state):
        """ToolDefinitionsBlock created even with empty tools list."""
        body = _make_body_with_tools([])
        blocks = format_request(body, fresh_state)
        tool_def_blocks = [b for b in blocks if isinstance(b, ToolDefinitionsBlock)]
        assert len(tool_def_blocks) == 1
        assert tool_def_blocks[0].tools == []
        assert tool_def_blocks[0].total_tokens == 0

    def test_tool_descriptions_stored_in_state(self, fresh_state):
        """state['tool_descriptions'] populated after format_request."""
        body = _make_body_with_tools(SAMPLE_TOOLS)
        format_request(body, fresh_state)
        assert "tool_descriptions" in fresh_state
        assert fresh_state["tool_descriptions"]["Read"] == "Read a file from disk"
        assert fresh_state["tool_descriptions"]["Write"] == "Write content to a file"

    def test_tool_definitions_block_instantiation(self):
        """ToolDefinitionsBlock can be instantiated with expected fields."""
        block = ToolDefinitionsBlock(
            tools=[{"name": "Foo"}],
            tool_tokens=[100],
            total_tokens=100,
        )
        assert isinstance(block, FormattedBlock)
        assert len(block.tools) == 1
        assert block.total_tokens == 100


class TestToolUseBlockDescription:
    """Tests for ToolUseBlock.description field population."""

    def test_tool_use_description_from_state(self, fresh_state):
        """ToolUseBlock.description populated from tool definitions."""
        body = {
            "model": "claude-3-opus",
            "max_tokens": 4096,
            "tools": SAMPLE_TOOLS,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "1",
                            "name": "Read",
                            "input": {"file_path": "/a.txt"},
                        },
                    ],
                },
            ],
        }
        blocks = format_request(body, fresh_state)
        tool_uses = [b for b in blocks if isinstance(b, ToolUseBlock)]
        assert len(tool_uses) == 1
        assert tool_uses[0].description == "Read a file from disk"

    def test_tool_use_description_empty_without_tools(self, fresh_state):
        """ToolUseBlock.description defaults to '' when no tool definitions."""
        body = {
            "model": "claude-3-opus",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "1",
                            "name": "Read",
                            "input": {"file_path": "/a.txt"},
                        },
                    ],
                },
            ],
        }
        blocks = format_request(body, fresh_state)
        tool_uses = [b for b in blocks if isinstance(b, ToolUseBlock)]
        assert len(tool_uses) == 1
        assert tool_uses[0].description == ""

    def test_tool_use_description_unknown_tool(self, fresh_state):
        """ToolUseBlock.description empty for tool not in definitions."""
        body = {
            "model": "claude-3-opus",
            "max_tokens": 4096,
            "tools": SAMPLE_TOOLS,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "1",
                            "name": "UnknownTool",
                            "input": {},
                        },
                    ],
                },
            ],
        }
        blocks = format_request(body, fresh_state)
        tool_uses = [b for b in blocks if isinstance(b, ToolUseBlock)]
        assert len(tool_uses) == 1
        assert tool_uses[0].description == ""
