"""Unit tests for tool use rendering with detail field."""

import pytest

from cc_dump.formatting import (
    ToolUseBlock, ToolResultBlock, ToolUseSummaryBlock, TextContentBlock,
    RoleBlock, NewlineBlock,
)
from cc_dump.tui.rendering import (
    _render_tool_use, _render_tool_result, _render_tool_use_summary,
    render_blocks, collapse_tool_runs, render_turn_to_strips,
)


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


class TestCollapseToolRuns:
    """Tests for collapse_tool_runs() pre-pass function."""

    def test_passthrough_when_tools_on(self):
        """tools_on=True returns all blocks with correct indices."""
        blocks = [
            TextContentBlock(text="hello"),
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
            ToolUseBlock(name="Read", input_size=200, msg_color_idx=1),
        ]
        result = collapse_tool_runs(blocks, tools_on=True)

        assert len(result) == 3
        for i, (idx, block) in enumerate(result):
            assert idx == i
            assert block is blocks[i]

    def test_collapse_consecutive_tool_uses(self):
        """3 consecutive ToolUseBlocks become 1 ToolUseSummaryBlock."""
        blocks = [
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
            ToolUseBlock(name="Read", input_size=200, msg_color_idx=1),
            ToolUseBlock(name="Bash", input_size=150, msg_color_idx=2),
        ]
        result = collapse_tool_runs(blocks, tools_on=False)

        assert len(result) == 1
        idx, block = result[0]
        assert idx == 0
        assert type(block).__name__ == "ToolUseSummaryBlock"
        assert block.total == 3
        assert block.tool_counts == {"Bash": 2, "Read": 1}

    def test_mixed_blocks_preserved(self):
        """Text, ToolUse, ToolUse, Text -> Text, Summary, Text."""
        blocks = [
            TextContentBlock(text="before"),
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
            ToolUseBlock(name="Read", input_size=200, msg_color_idx=1),
            TextContentBlock(text="after"),
        ]
        result = collapse_tool_runs(blocks, tools_on=False)

        assert len(result) == 3
        assert result[0][0] == 0
        assert type(result[0][1]).__name__ == "TextContentBlock"
        assert result[1][0] == 1  # first ToolUseBlock index
        assert type(result[1][1]).__name__ == "ToolUseSummaryBlock"
        assert result[1][1].total == 2
        assert result[2][0] == 3
        assert type(result[2][1]).__name__ == "TextContentBlock"

    def test_empty_list(self):
        """Empty input returns empty output."""
        result = collapse_tool_runs([], tools_on=False)
        assert result == []

    def test_single_tool_use(self):
        """Single ToolUseBlock becomes ToolUseSummaryBlock with total=1."""
        blocks = [ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0)]
        result = collapse_tool_runs(blocks, tools_on=False)

        assert len(result) == 1
        idx, block = result[0]
        assert idx == 0
        assert type(block).__name__ == "ToolUseSummaryBlock"
        assert block.total == 1
        assert block.tool_counts == {"Bash": 1}

    def test_non_consecutive_runs(self):
        """ToolUse, Text, ToolUse -> Summary, Text, Summary (two separate runs)."""
        blocks = [
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
            TextContentBlock(text="middle"),
            ToolUseBlock(name="Read", input_size=200, msg_color_idx=1),
        ]
        result = collapse_tool_runs(blocks, tools_on=False)

        assert len(result) == 3
        assert type(result[0][1]).__name__ == "ToolUseSummaryBlock"
        assert result[0][1].total == 1
        assert type(result[1][1]).__name__ == "TextContentBlock"
        assert type(result[2][1]).__name__ == "ToolUseSummaryBlock"
        assert result[2][1].total == 1

    def test_indices_correct(self):
        """Verify orig_idx values are correct for each returned item."""
        blocks = [
            TextContentBlock(text="a"),       # 0
            ToolUseBlock(name="B", input_size=1, msg_color_idx=0),  # 1
            ToolUseBlock(name="C", input_size=1, msg_color_idx=0),  # 2
            ToolUseBlock(name="D", input_size=1, msg_color_idx=0),  # 3
            TextContentBlock(text="e"),       # 4
            ToolUseBlock(name="F", input_size=1, msg_color_idx=0),  # 5
        ]
        result = collapse_tool_runs(blocks, tools_on=False)

        indices = [idx for idx, _ in result]
        assert indices == [0, 1, 4, 5]

    def test_input_not_mutated(self):
        """Input list is never mutated."""
        blocks = [
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
            ToolUseBlock(name="Read", input_size=200, msg_color_idx=1),
        ]
        original_len = len(blocks)
        collapse_tool_runs(blocks, tools_on=False)
        assert len(blocks) == original_len


class TestRenderToolUseSummary:
    """Tests for _render_tool_use_summary() renderer."""

    def test_summary_format_plural(self):
        """Multiple tools shows plural format."""
        block = ToolUseSummaryBlock(
            tool_counts={"Bash": 2, "Read": 1},
            total=3,
        )
        result = _render_tool_use_summary(block, {})

        assert result is not None
        plain = result.plain
        assert "used 3 tools" in plain
        assert "Bash 2x" in plain
        assert "Read 1x" in plain

    def test_summary_format_singular(self):
        """Single tool shows singular format."""
        block = ToolUseSummaryBlock(
            tool_counts={"Bash": 1},
            total=1,
        )
        result = _render_tool_use_summary(block, {})

        assert result is not None
        plain = result.plain
        assert "used 1 tool:" in plain
        assert "Bash 1x" in plain

    def test_summary_styled_dim(self):
        """Summary text is styled dim."""
        block = ToolUseSummaryBlock(
            tool_counts={"Bash": 1},
            total=1,
        )
        result = _render_tool_use_summary(block, {})

        assert result is not None
        styles = [span.style for span in result.spans if span.style]
        has_dim = any("dim" in str(style) for style in styles)
        assert has_dim


class TestRenderTurnToStripsToolSummary:
    """Integration test: tool summary through render_turn_to_strips()."""

    def test_summary_in_strips(self):
        """render_turn_to_strips() with tools=False produces summary in strip output."""
        from rich.console import Console

        blocks = [
            RoleBlock(role="assistant", msg_index=0),
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
            ToolUseBlock(name="Read", input_size=200, msg_color_idx=1),
            ToolUseBlock(name="Bash", input_size=150, msg_color_idx=2),
            NewlineBlock(),
        ]
        console = Console(width=80, force_terminal=True)
        filters = {"tools": False, "system": True, "headers": False, "metadata": False, "expand": False}

        strips, block_strip_map = render_turn_to_strips(
            blocks, filters, console, width=80,
        )

        # Extract text from strips
        text = "".join(seg.text for strip in strips for seg in strip._segments)
        assert "used 3 tools" in text
        assert "Bash 2x" in text
        assert "Read 1x" in text

    def test_individual_tools_in_strips_when_on(self):
        """render_turn_to_strips() with tools=True shows individual tool blocks."""
        from rich.console import Console

        blocks = [
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0, detail="git status"),
            ToolUseBlock(name="Read", input_size=200, msg_color_idx=1),
        ]
        console = Console(width=80, force_terminal=True)
        filters = {"tools": True, "system": True, "headers": False, "metadata": False, "expand": False}

        strips, block_strip_map = render_turn_to_strips(
            blocks, filters, console, width=80,
        )

        text = "".join(seg.text for strip in strips for seg in strip._segments)
        assert "Bash" in text
        assert "Read" in text
        assert "git status" in text
        # Should NOT have summary
        assert "used" not in text
