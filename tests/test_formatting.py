"""Unit tests for formatting.py - block generation and content tracking."""

import pytest

from cc_dump.core.formatting import (
    ConfigContentBlock,
    ContentRegion,
    ErrorBlock,
    FormattedBlock,
    HeaderBlock,
    HookOutputBlock,
    HttpHeadersBlock,
    ImageBlock,
    MessageBlock,
    MetadataBlock,
    MetadataSection,
    NewlineBlock,
    ProxyErrorBlock,
    ResponseMetadataSection,
    SeparatorBlock,
    StopReasonBlock,
    StreamInfoBlock,
    StreamToolUseBlock,
    SystemSection,
    TextContentBlock,
    TextDeltaBlock,
    SkillDefChild,
    AgentDefChild,
    ToolDefBlock,
    ToolDefsSection,
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
from cc_dump.pipeline.event_types import parse_sse_event


def _find_blocks(blocks, block_type):
    """Recursively find all blocks of a given type in the hierarchy."""
    result = []
    for block in blocks:
        if isinstance(block, block_type):
            result.append(block)
        for child in getattr(block, "children", []):
            result.extend(_find_blocks([child], block_type))
    return result


def _has_block(blocks, block_type):
    """Check if any block of given type exists in the hierarchy."""
    return len(_find_blocks(blocks, block_type)) > 0


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

    # Check for specific block types (MetadataBlock is inside MetadataSection container)
    has_header = any(isinstance(b, HeaderBlock) for b in blocks)
    has_metadata = _has_block(blocks, MetadataBlock)

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

    # Should have SystemSection container
    has_system_section = any(isinstance(b, SystemSection) for b in blocks)
    assert has_system_section

    # Should have tracked content inside SystemSection
    has_tracked = _has_block(blocks, TrackedContentBlock)
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

    # Should have SystemSection container
    has_system_section = any(isinstance(b, SystemSection) for b in blocks)
    assert has_system_section

    # Should have tracked content blocks inside SystemSection
    tracked_blocks = _find_blocks(blocks, TrackedContentBlock)
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

    # Should have MessageBlocks (containers replacing RoleBlock)
    msg_blocks = _find_blocks(blocks, MessageBlock)
    assert len(msg_blocks) == 2
    assert msg_blocks[0].role == "user"
    assert msg_blocks[1].role == "assistant"

    # Should have TextContentBlocks inside MessageBlocks
    text_blocks = _find_blocks(blocks, TextContentBlock)
    assert len(text_blocks) >= 2


def test_format_request_user_text_extracts_hook_output_block(fresh_state):
    """User text with known hook XML tag becomes HookOutputBlock child."""
    body = {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "<system-reminder>\nHook payload\n</system-reminder>\n\nTail text",
                    }
                ],
            },
        ],
    }
    blocks = format_request(body, fresh_state)
    msg_blocks = _find_blocks(blocks, MessageBlock)
    assert len(msg_blocks) == 1
    children = msg_blocks[0].children

    hook_blocks = [b for b in children if isinstance(b, HookOutputBlock)]
    text_blocks = [b for b in children if isinstance(b, TextContentBlock)]
    assert len(hook_blocks) == 1
    assert hook_blocks[0].hook_name == "system-reminder"
    assert "Hook payload" in hook_blocks[0].content
    assert any("Tail text" in b.content for b in text_blocks)


def test_format_request_user_text_extracts_non_hook_xml_as_config(fresh_state):
    """User text with non-hook XML tag becomes ConfigContentBlock child."""
    body = {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "<policy_spec>\nNo shell injection.\n</policy_spec>",
                    }
                ],
            },
        ],
    }
    blocks = format_request(body, fresh_state)
    msg_blocks = _find_blocks(blocks, MessageBlock)
    assert len(msg_blocks) == 1
    children = msg_blocks[0].children

    cfg_blocks = [b for b in children if isinstance(b, ConfigContentBlock)]
    assert len(cfg_blocks) == 1
    assert cfg_blocks[0].source == "policy_spec"
    assert "No shell injection." in cfg_blocks[0].content


def test_format_request_user_text_extracts_claude_md_config_without_duplication(
    fresh_state,
):
    """CLAUDE.md section is extracted to ConfigContentBlock and removed from plain text blocks."""
    config_line = "RULE: one source of truth"
    body = {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Prefix text\n"
                            "Contents of /Users/test/.claude/CLAUDE.md (global):\n"
                            f"{config_line}\n"
                            "Suffix text"
                        ),
                    }
                ],
            },
        ],
    }
    blocks = format_request(body, fresh_state)
    msg_blocks = _find_blocks(blocks, MessageBlock)
    assert len(msg_blocks) == 1
    children = msg_blocks[0].children

    cfg_blocks = [b for b in children if isinstance(b, ConfigContentBlock)]
    text_blocks = [b for b in children if isinstance(b, TextContentBlock)]
    assert len(cfg_blocks) == 1
    assert cfg_blocks[0].source == "/Users/test/.claude/CLAUDE.md"
    assert config_line in cfg_blocks[0].content
    assert all(config_line not in b.content for b in text_blocks)


def test_format_request_assistant_text_does_not_extract_hook_or_config(fresh_state):
    """Hook/config decomposition only applies to user text blocks."""
    body = {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "<system-reminder>\nAssistant text\n</system-reminder>",
                    }
                ],
            },
        ],
    }
    blocks = format_request(body, fresh_state)
    msg_blocks = _find_blocks(blocks, MessageBlock)
    assert len(msg_blocks) == 1
    children = msg_blocks[0].children

    assert any(isinstance(b, TextContentBlock) for b in children)
    assert not any(isinstance(b, HookOutputBlock) for b in children)
    assert not any(isinstance(b, ConfigContentBlock) for b in children)


def test_extracted_config_block_has_content_regions_for_collapse(fresh_state):
    """Extracted ConfigContentBlock participates in region-based collapse/search."""
    body = {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Contents of /tmp/CLAUDE.md:\n"
                            "<policy_spec>\n"
                            "Always run tests.\n"
                            "</policy_spec>\n"
                        ),
                    }
                ],
            },
        ],
    }
    blocks = format_request(body, fresh_state)
    cfg_blocks = _find_blocks(blocks, ConfigContentBlock)
    assert len(cfg_blocks) == 1

    cfg = cfg_blocks[0]
    assert cfg.content_regions
    assert any(region.kind == "xml_block" for region in cfg.content_regions)


def test_format_request_long_first_message_keeps_text_content(fresh_state):
    """Long first message content remains TextContentBlock (no tracking coercion)."""
    long_text = "line\n" * 700
    body = {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "messages": [
            {"role": "user", "content": long_text},
        ],
    }
    blocks = format_request(body, fresh_state)

    text_blocks = _find_blocks(blocks, TextContentBlock)
    tracked_blocks = _find_blocks(blocks, TrackedContentBlock)

    assert any(tb.content == long_text for tb in text_blocks)
    assert tracked_blocks == []


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

    # Should have ToolUseBlock inside MessageBlock
    tool_blocks = _find_blocks(blocks, ToolUseBlock)
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

    # Should have ToolResultBlock inside MessageBlock
    result_blocks = _find_blocks(blocks, ToolResultBlock)
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

    result_blocks = _find_blocks(blocks, ToolResultBlock)
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

    image_blocks = _find_blocks(blocks, ImageBlock)
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

    unknown_blocks = _find_blocks(blocks, UnknownTypeBlock)
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
    """Empty headers dict still emits ResponseMetadataSection with children."""
    blocks = format_response_headers(200, {})
    assert len(blocks) == 1
    assert isinstance(blocks[0], ResponseMetadataSection)
    children = blocks[0].children
    assert len(children) == 2
    assert isinstance(children[0], HeaderBlock)
    assert children[0].header_type == "response"
    assert children[0].label == "RESPONSE"
    assert isinstance(children[1], HttpHeadersBlock)
    assert children[1].headers == {}
    assert children[1].status_code == 200


def test_format_response_headers_with_headers():
    """Response headers formatted as ResponseMetadataSection with HeaderBlock + HttpHeadersBlock."""
    headers = {"Content-Type": "text/event-stream", "x-request-id": "abc123"}
    blocks = format_response_headers(200, headers)

    assert len(blocks) == 1
    assert isinstance(blocks[0], ResponseMetadataSection)
    children = blocks[0].children
    assert len(children) == 2
    assert isinstance(children[0], HeaderBlock)
    assert children[0].header_type == "response"
    assert isinstance(children[1], HttpHeadersBlock)
    assert children[1].headers == headers
    assert children[1].header_type == "response"
    assert children[1].status_code == 200


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
    assert "hunk" in kinds or "remove" in kinds or "add" in kinds


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
    assert "remove" in kinds


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
        assert kind in ("hunk", "add", "remove")
        assert isinstance(text, str)


# ─── Block Instantiation Tests ────────────────────────────────────────────────


def test_block_types_can_be_instantiated():
    """All block types can be instantiated with expected fields."""

    # Test a sampling of block types
    assert isinstance(SeparatorBlock(style="heavy"), FormattedBlock)
    assert isinstance(HeaderBlock(label="TEST"), FormattedBlock)
    assert isinstance(HttpHeadersBlock(headers={"key": "value"}), FormattedBlock)
    assert isinstance(MetadataBlock(model="claude"), FormattedBlock)
    assert isinstance(SystemSection(children=[]), FormattedBlock)
    assert isinstance(MessageBlock(role="user", msg_index=0, children=[]), FormattedBlock)
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
        tool_blocks = _find_blocks(blocks, ToolUseBlock)
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
        tool_blocks = _find_blocks(blocks, ToolUseBlock)
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
        tool_blocks = _find_blocks(blocks, ToolUseBlock)
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
        tool_blocks = _find_blocks(blocks, ToolUseBlock)
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
        tool_blocks = _find_blocks(blocks, ToolUseBlock)
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
        tool_uses = _find_blocks(blocks, ToolUseBlock)
        tool_results = _find_blocks(blocks, ToolResultBlock)

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
        tool_results = _find_blocks(blocks, ToolResultBlock)

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
        tool_results = _find_blocks(blocks, ToolResultBlock)

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
        uses = {b.tool_use_id: b for b in _find_blocks(blocks, ToolUseBlock)}
        results = {b.tool_use_id: b for b in _find_blocks(blocks, ToolResultBlock)}

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
        uses1 = _find_blocks(blocks1, ToolUseBlock)

        # Reset state but format again
        fresh_state["request_counter"] = 0
        blocks2 = format_request(body, fresh_state)
        uses2 = _find_blocks(blocks2, ToolUseBlock)

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
        tool_results = _find_blocks(blocks, ToolResultBlock)

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


# ─── ToolDefsSection Tests ───────────────────────────────────────────────────


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
    """Tests for ToolDefsSection creation and fields."""

    def test_tool_definitions_block_created(self, fresh_state):
        """ToolDefsSection created when tools present."""
        body = _make_body_with_tools(SAMPLE_TOOLS)
        blocks = format_request(body, fresh_state)
        tool_def_sections = [b for b in blocks if isinstance(b, ToolDefsSection)]
        assert len(tool_def_sections) == 1
        tds = tool_def_sections[0]
        assert tds.tool_count == 2
        assert len(tds.children) == 2
        assert tds.children[0].name == "Read"
        assert tds.children[1].name == "Write"

    def test_tool_definitions_block_token_estimates(self, fresh_state):
        """ToolDefsSection children have per-tool token estimates."""
        body = _make_body_with_tools(SAMPLE_TOOLS)
        blocks = format_request(body, fresh_state)
        tds = [b for b in blocks if isinstance(b, ToolDefsSection)][0]
        assert len(tds.children) == 2
        assert all(child.token_estimate > 0 for child in tds.children)
        assert tds.total_tokens == sum(child.token_estimate for child in tds.children)

    def test_tool_definitions_block_content_regions(self, fresh_state):
        """ToolDefsSection children capture tool name and schema."""
        body = _make_body_with_tools(SAMPLE_TOOLS)
        blocks = format_request(body, fresh_state)
        tds = [b for b in blocks if isinstance(b, ToolDefsSection)][0]
        assert len(tds.children) == 2
        assert tds.children[0].name == "Read"
        assert tds.children[1].name == "Write"
        assert tds.children[0].description == "Read a file from disk"
        assert tds.children[1].description == "Write content to a file"

    def test_skill_tool_parses_named_children(self, fresh_state):
        """Skill tool definition lines parse into SkillDefChild children."""
        body = _make_body_with_tools(
            [
                {
                    "name": "Skill",
                    "description": '- review-pr: "Review pull requests"\n- do:run-tests: "Run test suite"',
                    "input_schema": {"type": "object"},
                }
            ]
        )
        blocks = format_request(body, fresh_state)
        tds = [b for b in blocks if isinstance(b, ToolDefsSection)][0]
        tool = tds.children[0]
        assert len(tool.children) == 2
        assert isinstance(tool.children[0], SkillDefChild)
        assert tool.children[0].name == "review-pr"
        assert tool.children[0].description == "Review pull requests"
        assert tool.children[0].plugin_source == ""
        assert isinstance(tool.children[1], SkillDefChild)
        assert tool.children[1].name == "do:run-tests"
        assert tool.children[1].plugin_source == "do"

    def test_task_tool_parses_named_children(self, fresh_state):
        """Task tool definition lines parse into AgentDefChild children."""
        body = _make_body_with_tools(
            [
                {
                    "name": "Task",
                    "description": "- researcher: Gathers context (Tools: Read, Bash)\n- writer: Drafts output",
                    "input_schema": {"type": "object"},
                }
            ]
        )
        blocks = format_request(body, fresh_state)
        tds = [b for b in blocks if isinstance(b, ToolDefsSection)][0]
        tool = tds.children[0]
        assert len(tool.children) == 2
        assert isinstance(tool.children[0], AgentDefChild)
        assert tool.children[0].name == "researcher"
        assert tool.children[0].description == "Gathers context"
        assert tool.children[0].available_tools == "Read, Bash"
        assert isinstance(tool.children[1], AgentDefChild)
        assert tool.children[1].name == "writer"
        assert tool.children[1].description == "Drafts output"
        assert tool.children[1].available_tools == ""

    def test_tool_definitions_block_with_empty_tools(self, fresh_state):
        """ToolDefsSection created even with empty tools list."""
        body = _make_body_with_tools([])
        blocks = format_request(body, fresh_state)
        tool_def_sections = [b for b in blocks if isinstance(b, ToolDefsSection)]
        assert len(tool_def_sections) == 1
        assert tool_def_sections[0].children == []
        assert tool_def_sections[0].total_tokens == 0

    def test_tool_descriptions_stored_in_state(self, fresh_state):
        """state['tool_descriptions'] populated after format_request."""
        body = _make_body_with_tools(SAMPLE_TOOLS)
        format_request(body, fresh_state)
        assert "tool_descriptions" in fresh_state
        assert fresh_state["tool_descriptions"]["Read"] == "Read a file from disk"
        assert fresh_state["tool_descriptions"]["Write"] == "Write content to a file"

    def test_tool_def_block_instantiation(self):
        """ToolDefBlock can be instantiated with expected fields."""
        block = ToolDefBlock(
            name="Foo",
            description="Does foo things",
            input_schema={"type": "object"},
            token_estimate=100,
        )
        assert isinstance(block, FormattedBlock)
        assert block.name == "Foo"
        assert block.token_estimate == 100


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
        tool_uses = _find_blocks(blocks, ToolUseBlock)
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
        tool_uses = _find_blocks(blocks, ToolUseBlock)
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
        tool_uses = _find_blocks(blocks, ToolUseBlock)
        assert len(tool_uses) == 1
        assert tool_uses[0].description == ""


# ─── OpenAI Formatting Tests ─────────────────────────────────────────────────

from cc_dump.core.formatting import (
    format_openai_request,
    format_openai_complete_response,
    format_request_for_provider,
    Category,
)


def _fresh_openai_state():
    return {
        "request_counter": 0,
        "positions": {},
        "known_hashes": {},
        "next_id": 1,
        "next_color": 0,
    }


class TestFormatOpenAIRequest:
    """Tests for format_openai_request block generation."""

    def test_basic_request_produces_expected_blocks(self):
        """Basic OpenAI request produces header, metadata, and message blocks."""
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        blocks = format_openai_request(body, _fresh_openai_state())

        assert _has_block(blocks, HeaderBlock)
        assert _has_block(blocks, MetadataBlock)
        assert _has_block(blocks, MetadataSection)
        assert _has_block(blocks, MessageBlock)
        assert _has_block(blocks, TurnBudgetBlock)

        # Header says OpenAI
        headers = _find_blocks(blocks, HeaderBlock)
        assert any("OpenAI" in h.label for h in headers)

        # MetadataBlock has model
        meta = _find_blocks(blocks, MetadataBlock)
        assert len(meta) == 1
        assert meta[0].model == "gpt-4o"

    def test_request_with_tools(self):
        """Tool definitions extracted from OpenAI format."""
        body = {
            "model": "gpt-4o",
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get weather for a city",
                        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
                    },
                },
            ],
            "messages": [{"role": "user", "content": "Weather?"}],
        }
        blocks = format_openai_request(body, _fresh_openai_state())

        tool_defs = _find_blocks(blocks, ToolDefBlock)
        assert len(tool_defs) == 1
        assert tool_defs[0].name == "get_weather"
        assert tool_defs[0].description == "Get weather for a city"

        tool_sections = _find_blocks(blocks, ToolDefsSection)
        assert len(tool_sections) == 1
        assert tool_sections[0].tool_count == 1

    def test_system_message_in_system_section(self):
        """System message from messages array placed in SystemSection."""
        body = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hi"},
            ],
        }
        blocks = format_openai_request(body, _fresh_openai_state())

        system_sections = _find_blocks(blocks, SystemSection)
        assert len(system_sections) == 1
        # System section should have tracked content
        assert len(system_sections[0].children) > 0

        # System message should NOT appear as a conversation MessageBlock
        msg_blocks = _find_blocks(blocks, MessageBlock)
        roles = [m.role for m in msg_blocks]
        assert "system" not in roles

    def test_assistant_tool_calls_produce_tool_use_blocks(self):
        """tool_calls on assistant messages produce ToolUseBlock children."""
        body = {
            "model": "gpt-4o",
            "messages": [
                {
                    "role": "assistant",
                    "content": "Let me check.",
                    "tool_calls": [
                        {
                            "id": "call_abc",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path": "test.py"}',
                            },
                        },
                    ],
                },
            ],
        }
        blocks = format_openai_request(body, _fresh_openai_state())

        tool_uses = _find_blocks(blocks, ToolUseBlock)
        assert len(tool_uses) == 1
        assert tool_uses[0].name == "read_file"
        assert tool_uses[0].tool_use_id == "call_abc"
        assert tool_uses[0].tool_input == {"path": "test.py"}

    def test_tool_role_messages_as_message_blocks(self):
        """role='tool' messages produce MessageBlock with role='tool'."""
        body = {
            "model": "gpt-4o",
            "messages": [
                {"role": "tool", "tool_call_id": "call_abc", "content": "file contents"},
            ],
        }
        blocks = format_openai_request(body, _fresh_openai_state())

        msg_blocks = _find_blocks(blocks, MessageBlock)
        tool_msgs = [m for m in msg_blocks if m.role == "tool"]
        assert len(tool_msgs) == 1

        # Content should be in a TextContentBlock child
        text_blocks = _find_blocks([tool_msgs[0]], TextContentBlock)
        assert len(text_blocks) == 1
        assert text_blocks[0].content == "file contents"

    def test_increments_request_counter(self):
        """Request counter incremented per call."""
        state = _fresh_openai_state()
        body = {"model": "gpt-4o", "messages": [{"role": "user", "content": "1"}]}

        format_openai_request(body, state)
        assert state["request_counter"] == 1

        format_openai_request(body, state)
        assert state["request_counter"] == 2

    def test_multi_turn_conversation(self):
        """Multiple conversation messages produce separate MessageBlocks."""
        body = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
                {"role": "user", "content": "How are you?"},
            ],
        }
        blocks = format_openai_request(body, _fresh_openai_state())

        msg_blocks = _find_blocks(blocks, MessageBlock)
        assert len(msg_blocks) == 3
        assert msg_blocks[0].role == "user"
        assert msg_blocks[1].role == "assistant"
        assert msg_blocks[2].role == "user"


class TestProviderDispatchFormatting:
    def test_copilot_uses_openai_family_formatter(self):
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        blocks = format_request_for_provider("copilot", body, _fresh_openai_state())
        headers = _find_blocks(blocks, HeaderBlock)
        assert any("Copilot" in h.label for h in headers)


class TestFormatOpenAICompleteResponse:
    """Tests for format_openai_complete_response block generation."""

    def test_text_response(self):
        """Text content produces TextContentBlock in MessageBlock."""
        msg = {
            "id": "chatcmpl-abc",
            "model": "gpt-4o",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                },
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        blocks = format_openai_complete_response(msg)

        assert _has_block(blocks, StreamInfoBlock)
        assert _has_block(blocks, MessageBlock)
        assert _has_block(blocks, StopReasonBlock)

        info = _find_blocks(blocks, StreamInfoBlock)
        assert info[0].model == "gpt-4o"

        text = _find_blocks(blocks, TextContentBlock)
        assert len(text) == 1
        assert text[0].content == "Hello!"

        stop = _find_blocks(blocks, StopReasonBlock)
        assert stop[0].reason == "stop"

    def test_tool_calls_response(self):
        """Tool calls produce ToolUseBlock children."""
        msg = {
            "id": "chatcmpl-xyz",
            "model": "gpt-4o",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"city": "NYC"}',
                                },
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                },
            ],
        }
        blocks = format_openai_complete_response(msg)

        tool_uses = _find_blocks(blocks, ToolUseBlock)
        assert len(tool_uses) == 1
        assert tool_uses[0].name == "get_weather"
        assert tool_uses[0].tool_use_id == "call_123"
        assert tool_uses[0].tool_input == {"city": "NYC"}

        stop = _find_blocks(blocks, StopReasonBlock)
        assert stop[0].reason == "tool_calls"

    def test_empty_choices(self):
        """Empty choices still produce structure blocks."""
        msg = {"model": "gpt-4o", "choices": []}
        blocks = format_openai_complete_response(msg)

        assert _has_block(blocks, StreamInfoBlock)
        assert _has_block(blocks, MessageBlock)
        assert _has_block(blocks, StopReasonBlock)

    def test_text_with_tool_calls(self):
        """Response with both text and tool_calls produces both block types."""
        msg = {
            "model": "gpt-4o",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "I'll check that for you.",
                        "tool_calls": [
                            {
                                "id": "call_456",
                                "function": {"name": "search", "arguments": '{"q": "test"}'},
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                },
            ],
        }
        blocks = format_openai_complete_response(msg)

        text = _find_blocks(blocks, TextContentBlock)
        tools = _find_blocks(blocks, ToolUseBlock)
        assert len(text) == 1
        assert text[0].content == "I'll check that for you."
        assert len(tools) == 1
        assert tools[0].name == "search"
