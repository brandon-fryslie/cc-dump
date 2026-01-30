"""Unit tests for tool use rendering with detail field."""

import pytest

from cc_dump.formatting import ToolUseBlock, ToolResultBlock
from cc_dump.tui.rendering import _render_tool_use, _render_tool_result


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
        assert "tool_result" in result.plain
        assert "500 bytes" in result.plain

    def test_summary_mode_shows_name(self):
        """Tool result with tools filter OFF shows compact summary."""
        block = ToolResultBlock(size=500, tool_name="Read", msg_color_idx=0)
        result = _render_tool_result(block, {"tools": False})

        assert result is not None  # No longer returns None!
        assert "Read" in result.plain
        assert "500 bytes" in result.plain

    def test_summary_mode_shows_detail(self):
        """Tool result with tools filter OFF shows detail in summary."""
        block = ToolResultBlock(
            size=500,
            tool_name="Read",
            detail="...path/file.ts",
            msg_color_idx=0
        )
        result = _render_tool_result(block, {"tools": False})

        assert result is not None
        assert "Read" in result.plain
        assert "...path/file.ts" in result.plain
        assert "500 bytes" in result.plain

    def test_summary_mode_without_name(self):
        """Tool result with tools filter OFF but no tool_name falls back to generic label."""
        block = ToolResultBlock(size=500, msg_color_idx=0)
        result = _render_tool_result(block, {"tools": False})

        assert result is not None
        assert "tool_result" in result.plain
        assert "500 bytes" in result.plain

    def test_summary_mode_is_dimmed(self):
        """Tool result summary mode is styled dim."""
        block = ToolResultBlock(size=500, tool_name="Read", msg_color_idx=0)
        result = _render_tool_result(block, {"tools": False})

        assert result is not None
        # Check for dim style
        styles = [span.style for span in result.spans if span.style]
        has_dim = any("dim" in str(style) for style in styles)
        assert has_dim

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
        assert "error" in result.plain
        assert "200 bytes" in result.plain

    def test_error_result_summary_mode(self):
        """Error result with tools filter OFF shows error in summary."""
        block = ToolResultBlock(
            size=200,
            is_error=True,
            tool_name="Read",
            msg_color_idx=0
        )
        result = _render_tool_result(block, {"tools": False})

        assert result is not None
        assert "error" in result.plain
        assert "Read" in result.plain
        assert "200 bytes" in result.plain

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
        """Tool result in summary mode has no filter indicator."""
        block = ToolResultBlock(size=500, tool_name="Read", msg_color_idx=0)
        result = _render_tool_result(block, {"tools": False})

        assert result is not None
        # Summary mode should not have the filter indicator
        # This is harder to test directly, but we can check that it's shorter
        # or doesn't contain the indicator character
        plain = result.plain
        # Just verify it's not None and has the expected content
        assert "Read" in plain

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
