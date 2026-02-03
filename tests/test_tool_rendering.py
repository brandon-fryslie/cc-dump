"""Unit tests for tool use rendering with detail field."""

import pytest

from cc_dump.formatting import (
    ToolUseBlock, ToolResultBlock, TextContentBlock, RoleBlock,
    UnknownTypeBlock, NewlineBlock, _merge_tool_only_assistant_runs,
)
from cc_dump.tui.rendering import _render_tool_use, _render_tool_result, render_blocks


class TestRenderToolUseWithDetail:
    """Tests for _render_tool_use with detail field."""

    def test_with_detail(self):
        """Tool use block with detail shows detail between name and bytes."""
        block = ToolUseBlock(
            name="Read",
            input_size=100,
            msg_color_idx=0,
            detail="...path/file.ts"
        )
        result = _render_tool_use(block, {"tools": True})

        assert result is not None
        plain = result.plain
        assert "Read" in plain
        assert "...path/file.ts" in plain
        assert "100 bytes" in plain

        # Detail should appear between name and bytes
        name_idx = plain.index("Read")
        detail_idx = plain.index("...path/file.ts")
        bytes_idx = plain.index("100 bytes")
        assert name_idx < detail_idx < bytes_idx

    def test_without_detail(self):
        """Tool use block without detail (empty string) shows normal output."""
        block = ToolUseBlock(
            name="Read",
            input_size=100,
            msg_color_idx=0,
            detail=""
        )
        result = _render_tool_use(block, {"tools": True})

        assert result is not None
        plain = result.plain
        assert "Read" in plain
        assert "100 bytes" in plain

    def test_with_default_detail(self):
        """Tool use block created without detail parameter works correctly."""
        block = ToolUseBlock(
            name="Read",
            input_size=100,
            msg_color_idx=0
        )
        result = _render_tool_use(block, {"tools": True})

        assert result is not None
        plain = result.plain
        assert "Read" in plain
        assert "100 bytes" in plain

    def test_filtered_out_returns_none(self):
        """Tool use block filtered out by tools=False returns None."""
        block = ToolUseBlock(
            name="Read",
            input_size=100,
            msg_color_idx=0,
            detail="...path/file.ts"
        )
        result = _render_tool_use(block, {"tools": False})

        assert result is None

    def test_bash_detail_shown(self):
        """Bash tool with command detail shows command."""
        block = ToolUseBlock(
            name="Bash",
            input_size=200,
            msg_color_idx=1,
            detail="git status"
        )
        result = _render_tool_use(block, {"tools": True})

        assert result is not None
        plain = result.plain
        assert "Bash" in plain
        assert "git status" in plain
        assert "200 bytes" in plain

    def test_skill_detail_shown(self):
        """Skill tool with skill name detail shows skill."""
        block = ToolUseBlock(
            name="Skill",
            input_size=50,
            msg_color_idx=2,
            detail="commit"
        )
        result = _render_tool_use(block, {"tools": True})

        assert result is not None
        plain = result.plain
        assert "Skill" in plain
        assert "commit" in plain
        assert "50 bytes" in plain

    def test_detail_styled_dim(self):
        """Detail text is styled dim."""
        block = ToolUseBlock(
            name="Read",
            input_size=100,
            msg_color_idx=0,
            detail="...path/file.ts"
        )
        result = _render_tool_use(block, {"tools": True})

        assert result is not None
        # Check that the result has the dim style applied to the detail
        # Rich Text objects store style info in spans
        # We can check that dim is in the styles
        styles = [span.style for span in result.spans if span.style]
        has_dim = any("dim" in str(style) for style in styles)
        assert has_dim


class TestRenderToolResultSummary:
    """Tests for _render_tool_result with summary mode."""

    def test_full_mode_shows_name(self):
        """Tool result with tools filter ON shows tool name."""
        block = ToolResultBlock(size=500, tool_name="Read", msg_color_idx=0)
        result = _render_tool_result(block, {"tools": True})

        assert result is not None
        assert "Read" in result.plain
        assert "500 bytes" in result.plain

    def test_full_mode_shows_detail(self):
        """Tool result with tools filter ON shows detail."""
        block = ToolResultBlock(
            size=500,
            tool_name="Read",
            detail="...path/file.ts",
            msg_color_idx=0
        )
        result = _render_tool_result(block, {"tools": True})

        assert result is not None
        assert "Read" in result.plain
        assert "...path/file.ts" in result.plain
        assert "500 bytes" in result.plain

    def test_full_mode_without_name(self):
        """Tool result with tools filter ON but no tool_name still works."""
        block = ToolResultBlock(size=500, msg_color_idx=0)
        result = _render_tool_result(block, {"tools": True})

        assert result is not None
        assert "Result" in result.plain
        assert "500 bytes" in result.plain

    def test_summary_mode_returns_none(self):
        """Tool result with tools filter OFF returns None (summary handled by render_blocks)."""
        block = ToolResultBlock(size=500, tool_name="Read", msg_color_idx=0)
        result = _render_tool_result(block, {"tools": False})

        assert result is None

    def test_error_result_full_mode(self):
        """Error result with tools filter ON shows error label."""
        block = ToolResultBlock(
            size=200,
            is_error=True,
            tool_name="Read",
            msg_color_idx=0
        )
        result = _render_tool_result(block, {"tools": True})

        assert result is not None
        assert "ERROR" in result.plain
        assert "200 bytes" in result.plain

    def test_error_result_summary_mode_returns_none(self):
        """Error result with tools filter OFF returns None (summary handled by render_blocks)."""
        block = ToolResultBlock(
            size=200,
            is_error=True,
            tool_name="Read",
            msg_color_idx=0
        )
        result = _render_tool_result(block, {"tools": False})

        assert result is None

    def test_full_mode_has_filter_indicator(self):
        """Tool result in full mode includes filter indicator."""
        block = ToolResultBlock(size=500, tool_name="Read", msg_color_idx=0)
        result = _render_tool_result(block, {"tools": True})

        assert result is not None
        # The filter indicator is a special character prepended
        # Check that the result has more than just the basic content
        plain = result.plain
        # Filter indicators are typically special Unicode characters
        # We can check for the presence of specific formatting
        assert len(plain) > len("tool_result Read 500 bytes")

    def test_summary_mode_no_filter_indicator(self):
        """Tool result in summary mode returns None (summary at render_blocks level)."""
        block = ToolResultBlock(size=500, tool_name="Read", msg_color_idx=0)
        result = _render_tool_result(block, {"tools": False})

        assert result is None

    def test_color_preserved_from_block(self):
        """Tool result rendering uses color index from block."""
        # Different color indices
        block1 = ToolResultBlock(size=500, tool_name="Read", msg_color_idx=0)
        block2 = ToolResultBlock(size=500, tool_name="Read", msg_color_idx=3)

        result1 = _render_tool_result(block1, {"tools": True})
        result2 = _render_tool_result(block2, {"tools": True})

        assert result1 is not None
        assert result2 is not None
        # Colors are applied as styles - hard to test directly without
        # inspecting Rich's internal style representation
        # At minimum, both should render successfully
        assert result1.plain == result2.plain  # Same content


class TestRenderBlocksToolSummary:
    """Tests for render_blocks tool-use summary when tools filter is off."""

    def test_tool_uses_collapsed_to_summary(self):
        """Consecutive ToolUseBlocks collapsed into summary when tools=False."""
        blocks = [
            TextContentBlock(text="hello"),
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
            ToolUseBlock(name="Read", input_size=200, msg_color_idx=1),
            ToolUseBlock(name="Bash", input_size=150, msg_color_idx=2),
            TextContentBlock(text="world"),
        ]
        result = render_blocks(blocks, {"tools": False})

        # Should have: text, summary, text = 3 items
        assert len(result) == 3
        # Check indices
        assert result[0][0] == 0  # first TextContentBlock
        assert result[1][0] == 1  # first ToolUseBlock index (summary)
        assert result[2][0] == 4  # second TextContentBlock

        # Check summary content
        summary_text = result[1][1]
        assert "3 tools" in summary_text.plain
        assert "Bash 2x" in summary_text.plain
        assert "Read 1x" in summary_text.plain

    def test_tool_uses_shown_individually_when_on(self):
        """ToolUseBlocks shown individually when tools=True."""
        blocks = [
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
            ToolUseBlock(name="Read", input_size=200, msg_color_idx=1),
        ]
        result = render_blocks(blocks, {"tools": True})

        assert len(result) == 2
        assert result[0][0] == 0
        assert result[1][0] == 1

    def test_single_tool_use_summary(self):
        """Single ToolUseBlock shows summary with count 1."""
        blocks = [
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
        ]
        result = render_blocks(blocks, {"tools": False})

        assert len(result) == 1
        assert result[0][0] == 0
        assert "1 tool" in result[0][1].plain

    def test_tool_result_filtered_when_tools_off(self):
        """ToolResultBlock returns None when tools filter is off."""
        blocks = [
            ToolResultBlock(size=500, tool_name="Read", msg_color_idx=0),
        ]
        result = render_blocks(blocks, {"tools": False})

        # ToolResultBlock is not a ToolUseBlock, so it goes through render_block
        # which returns None when tools=False
        assert len(result) == 0


class TestMergeToolOnlyAssistantRuns:
    """Tests for _merge_tool_only_assistant_runs."""

    def test_no_merge_single_assistant(self):
        """Single tool-only assistant group is unchanged."""
        blocks = [
            RoleBlock(role="assistant", msg_index=0, timestamp="1:00 PM"),
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
            NewlineBlock(),
        ]
        result = _merge_tool_only_assistant_runs(blocks)
        assert len(result) == len(blocks)
        assert isinstance(result[0], RoleBlock)
        assert isinstance(result[1], ToolUseBlock)

    def test_merge_two_consecutive_tool_only(self):
        """Two consecutive tool-only assistant messages merge into one."""
        blocks = [
            RoleBlock(role="assistant", msg_index=0, timestamp="1:00 PM"),
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
            ToolUseBlock(name="Read", input_size=200, msg_color_idx=1),
            NewlineBlock(),
            RoleBlock(role="assistant", msg_index=2, timestamp="1:00 PM"),
            ToolUseBlock(name="Bash", input_size=150, msg_color_idx=2),
        ]
        result = _merge_tool_only_assistant_runs(blocks)

        # Should have: 1 RoleBlock + 3 ToolUseBlocks (no intermediate NewlineBlock/RoleBlock)
        role_blocks = [b for b in result if isinstance(b, RoleBlock)]
        tool_blocks = [b for b in result if isinstance(b, ToolUseBlock)]
        assert len(role_blocks) == 1
        assert len(tool_blocks) == 3
        assert role_blocks[0].msg_index == 0  # kept the first one

    def test_merge_preserves_thinking_blocks(self):
        """Thinking (UnknownTypeBlock) and text content are preserved during merge."""
        blocks = [
            RoleBlock(role="assistant", msg_index=0, timestamp="1:00 PM"),
            UnknownTypeBlock(block_type="thinking"),
            TextContentBlock(text="Let me evaluate...", indent="    "),
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
            NewlineBlock(),
            RoleBlock(role="assistant", msg_index=2, timestamp="1:00 PM"),
            UnknownTypeBlock(block_type="thinking"),
            ToolUseBlock(name="Read", input_size=200, msg_color_idx=1),
        ]
        result = _merge_tool_only_assistant_runs(blocks)

        role_blocks = [b for b in result if isinstance(b, RoleBlock)]
        tool_blocks = [b for b in result if isinstance(b, ToolUseBlock)]
        thinking_blocks = [b for b in result if isinstance(b, UnknownTypeBlock)]
        text_blocks = [b for b in result if isinstance(b, TextContentBlock)]

        assert len(role_blocks) == 1
        assert len(tool_blocks) == 2
        assert len(thinking_blocks) == 2
        assert len(text_blocks) == 1

    def test_no_merge_with_non_tool_assistant(self):
        """Assistant with real text response is not merged with tool-only."""
        blocks = [
            RoleBlock(role="assistant", msg_index=0, timestamp="1:00 PM"),
            TextContentBlock(text="Here is my answer.", indent="    "),
            NewlineBlock(),
            RoleBlock(role="assistant", msg_index=2, timestamp="1:00 PM"),
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
        ]
        result = _merge_tool_only_assistant_runs(blocks)

        # First group has text but no ToolUseBlock, so it's not tool-only.
        # Second group is tool-only but stands alone. No merging.
        role_blocks = [b for b in result if isinstance(b, RoleBlock)]
        assert len(role_blocks) == 2

    def test_no_merge_across_user_boundary(self):
        """Tool-only assistant groups separated by a user message don't merge."""
        blocks = [
            RoleBlock(role="assistant", msg_index=0, timestamp="1:00 PM"),
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
            NewlineBlock(),
            RoleBlock(role="user", msg_index=1, timestamp="1:00 PM"),
            TextContentBlock(text="hello", indent="    "),
            NewlineBlock(),
            RoleBlock(role="assistant", msg_index=2, timestamp="1:00 PM"),
            ToolUseBlock(name="Read", input_size=200, msg_color_idx=1),
        ]
        result = _merge_tool_only_assistant_runs(blocks)

        role_blocks = [b for b in result if isinstance(b, RoleBlock)]
        assert len(role_blocks) == 3  # all three preserved

    def test_merge_three_consecutive(self):
        """Three consecutive tool-only assistant groups merge into one."""
        blocks = [
            RoleBlock(role="assistant", msg_index=0, timestamp="1:00 PM"),
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
            NewlineBlock(),
            RoleBlock(role="assistant", msg_index=2, timestamp="1:00 PM"),
            ToolUseBlock(name="Read", input_size=200, msg_color_idx=1),
            NewlineBlock(),
            RoleBlock(role="assistant", msg_index=4, timestamp="1:00 PM"),
            ToolUseBlock(name="Bash", input_size=150, msg_color_idx=2),
            ToolUseBlock(name="Glob", input_size=50, msg_color_idx=3),
        ]
        result = _merge_tool_only_assistant_runs(blocks)

        role_blocks = [b for b in result if isinstance(b, RoleBlock)]
        tool_blocks = [b for b in result if isinstance(b, ToolUseBlock)]
        assert len(role_blocks) == 1
        assert len(tool_blocks) == 4

    def test_empty_blocks(self):
        """Empty input returns empty output."""
        assert _merge_tool_only_assistant_runs([]) == []

    def test_non_assistant_blocks_pass_through(self):
        """Non-assistant blocks (headers, separators, etc.) pass through unchanged."""
        from cc_dump.formatting import SeparatorBlock, HeaderBlock
        blocks = [
            SeparatorBlock(style="heavy"),
            HeaderBlock(label="REQUEST #1"),
            SeparatorBlock(style="thin"),
        ]
        result = _merge_tool_only_assistant_runs(blocks)
        assert len(result) == len(blocks)
