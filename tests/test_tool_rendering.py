"""Unit tests for tool use rendering with detail field."""

import pytest

from cc_dump.formatting import ToolUseBlock
from cc_dump.tui.rendering import _render_tool_use


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
