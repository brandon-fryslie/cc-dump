"""Unit tests for formatting.py - block generation and content tracking."""

import pytest

from cc_dump.formatting import (
    DiffBlock,
    ErrorBlock,
    FormattedBlock,
    HeaderBlock,
    ImageBlock,
    LogBlock,
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
    ToolResultBlock,
    ToolUseBlock,
    TrackedContentBlock,
    TurnBudgetBlock,
    UnknownTypeBlock,
    format_request,
    format_response_event,
    make_diff_lines,
    track_content,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def fresh_state():
    """Fresh state dict for content tracking."""
    return {
        "positions": {},
        "known_hashes": {},
        "next_id": 0,
        "next_color": 0,
        "request_counter": 0,
    }


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
    data = {
        "message": {
            "model": "claude-3-opus-20240229",
        },
    }
    blocks = format_response_event("message_start", data)

    assert len(blocks) == 1
    assert isinstance(blocks[0], StreamInfoBlock)
    assert blocks[0].model == "claude-3-opus-20240229"


def test_format_response_event_content_block_start_tool():
    """content_block_start with tool_use creates StreamToolUseBlock."""
    data = {
        "content_block": {
            "type": "tool_use",
            "name": "read_file",
        },
    }
    blocks = format_response_event("content_block_start", data)

    assert len(blocks) == 1
    assert isinstance(blocks[0], StreamToolUseBlock)
    assert blocks[0].name == "read_file"


def test_format_response_event_content_block_start_text():
    """content_block_start with text returns empty (no block needed)."""
    data = {
        "content_block": {
            "type": "text",
        },
    }
    blocks = format_response_event("content_block_start", data)
    assert len(blocks) == 0


def test_format_response_event_content_block_delta():
    """content_block_delta creates TextDeltaBlock."""
    data = {
        "delta": {
            "type": "text_delta",
            "text": "Hello",
        },
    }
    blocks = format_response_event("content_block_delta", data)

    assert len(blocks) == 1
    assert isinstance(blocks[0], TextDeltaBlock)
    assert blocks[0].text == "Hello"


def test_format_response_event_content_block_delta_empty():
    """content_block_delta with empty text returns empty list."""
    data = {
        "delta": {
            "type": "text_delta",
            "text": "",
        },
    }
    blocks = format_response_event("content_block_delta", data)
    assert len(blocks) == 0


def test_format_response_event_message_delta():
    """message_delta with stop_reason creates StopReasonBlock."""
    data = {
        "delta": {
            "stop_reason": "end_turn",
        },
    }
    blocks = format_response_event("message_delta", data)

    assert len(blocks) == 1
    assert isinstance(blocks[0], StopReasonBlock)
    assert blocks[0].reason == "end_turn"


def test_format_response_event_message_delta_no_stop():
    """message_delta without stop_reason returns empty list."""
    data = {
        "delta": {},
    }
    blocks = format_response_event("message_delta", data)
    assert len(blocks) == 0


def test_format_response_event_message_stop():
    """message_stop returns empty list."""
    blocks = format_response_event("message_stop", {})
    assert len(blocks) == 0


# ─── track_content Tests ──────────────────────────────────────────────────────


def test_track_content_new(fresh_state):
    """First occurrence tagged 'new'."""
    result = track_content("Hello world", "system:0", fresh_state)

    assert result[0] == "new"
    tag_id = result[1]
    color_idx = result[2]
    content = result[3]

    assert tag_id.startswith("sp-")
    assert isinstance(color_idx, int)
    assert content == "Hello world"

    # State should be updated
    assert "system:0" in fresh_state["positions"]
    assert fresh_state["next_id"] == 1


def test_track_content_ref(fresh_state):
    """Second occurrence of same content tagged 'ref'."""
    # First call
    track_content("Hello", "system:0", fresh_state)

    # Second call with same content at different position
    result = track_content("Hello", "msg:1", fresh_state)

    assert result[0] == "ref"
    tag_id = result[1]
    color_idx = result[2]

    assert tag_id.startswith("sp-")
    assert isinstance(color_idx, int)


def test_track_content_changed(fresh_state):
    """Modified content at same position tagged 'changed'."""
    # First call
    track_content("Original", "system:0", fresh_state)

    # Second call with different content at same position
    result = track_content("Modified", "system:0", fresh_state)

    assert result[0] == "changed"
    tag_id = result[1]
    color_idx = result[2]
    old_content = result[3]
    new_content = result[4]

    assert old_content == "Original"
    assert new_content == "Modified"
    assert tag_id.startswith("sp-")


def test_track_content_multiple_positions_same_content(fresh_state):
    """Same content at multiple positions shares tag."""
    result1 = track_content("Shared", "pos:1", fresh_state)
    result2 = track_content("Shared", "pos:2", fresh_state)

    # First is new
    assert result1[0] == "new"
    tag_id_1 = result1[1]

    # Second is ref to same tag
    assert result2[0] == "ref"
    tag_id_2 = result2[1]

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
    assert isinstance(MetadataBlock(model="claude"), FormattedBlock)
    assert isinstance(SystemLabelBlock(), FormattedBlock)
    assert isinstance(RoleBlock(role="user"), FormattedBlock)
    assert isinstance(TextContentBlock(text="Hello"), FormattedBlock)
    assert isinstance(ToolUseBlock(name="tool"), FormattedBlock)
    assert isinstance(ToolResultBlock(size=100), FormattedBlock)
    assert isinstance(ImageBlock(media_type="image/png"), FormattedBlock)
    assert isinstance(UnknownTypeBlock(block_type="unknown"), FormattedBlock)
    assert isinstance(StreamInfoBlock(model="claude"), FormattedBlock)
    assert isinstance(StreamToolUseBlock(name="tool"), FormattedBlock)
    assert isinstance(TextDeltaBlock(text="delta"), FormattedBlock)
    assert isinstance(StopReasonBlock(reason="end_turn"), FormattedBlock)
    assert isinstance(ErrorBlock(code=500), FormattedBlock)
    assert isinstance(ProxyErrorBlock(error="error"), FormattedBlock)
    assert isinstance(LogBlock(command="GET"), FormattedBlock)
    assert isinstance(NewlineBlock(), FormattedBlock)
    assert isinstance(TrackedContentBlock(status="new"), FormattedBlock)
    assert isinstance(DiffBlock(), FormattedBlock)
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
    color1 = result1[2]

    # Track same content at different position
    result2 = track_content("Shared content", "pos:2", fresh_state)
    color2 = result2[2]

    # Should have same color
    assert color1 == color2
