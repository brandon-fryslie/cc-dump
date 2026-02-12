"""Unit tests for tool use rendering with detail field."""

import pytest

from cc_dump.formatting import (
    ToolUseBlock, ToolResultBlock, ToolUseSummaryBlock, TextContentBlock,
    RoleBlock, NewlineBlock, VisState, HIDDEN, ALWAYS_VISIBLE,
)
from cc_dump.tui.rendering import (
    _render_tool_use_oneliner, _render_tool_use_full, _render_tool_result_full,
    _render_tool_result_summary, _render_tool_use_summary,
    _render_read_content, _render_confirm_content,
    _render_tool_use_bash_full, _render_tool_use_edit_full,
    _infer_lang_from_path,
    render_blocks, collapse_tool_runs, render_turn_to_strips,
    set_theme,
)
from textual.theme import BUILTIN_THEMES


@pytest.fixture(autouse=True)
def _init_theme():
    """Initialize rendering theme for all tests in this module."""
    set_theme(BUILTIN_THEMES["textual-dark"])


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
        result = _render_tool_use_oneliner(block)

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
        result = _render_tool_use_oneliner(block)

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
        result = _render_tool_use_oneliner(block)

        assert result is not None
        plain = result.plain
        assert "Read" in plain
        assert "100 bytes" in plain

    def test_bash_detail_shown(self):
        """Bash tool with command detail shows command."""
        block = ToolUseBlock(
            name="Bash",
            input_size=200,
            msg_color_idx=1,
            detail="git status"
        )
        result = _render_tool_use_oneliner(block)

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
        result = _render_tool_use_oneliner(block)

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
        result = _render_tool_use_oneliner(block)

        assert result is not None
        # Check that the result has the dim style applied to the detail
        # Rich Text objects store style info in spans
        # We can check that dim is in the styles
        styles = [span.style for span in result.spans if span.style]
        has_dim = any("dim" in str(style) for style in styles)
        assert has_dim


class TestRenderToolResultExisting:
    """Tests for tool result rendering — existing behavior validation."""

    def test_generic_full_shows_name(self):
        """Tool result for generic tool (Bash) shows tool name."""
        block = ToolResultBlock(size=500, tool_name="Bash", msg_color_idx=0, content="output")
        result = _render_tool_result_full(block)

        assert result is not None
        assert "Bash" in result.plain
        assert "500 bytes" in result.plain

    def test_generic_full_shows_detail(self):
        """Tool result for generic tool shows detail."""
        block = ToolResultBlock(
            size=500,
            tool_name="Bash",
            detail="git status",
            msg_color_idx=0,
            content="output",
        )
        result = _render_tool_result_full(block)

        assert result is not None
        assert "Bash" in result.plain
        assert "git status" in result.plain
        assert "500 bytes" in result.plain

    def test_full_mode_without_name(self):
        """Tool result without tool_name still works (generic fallback)."""
        block = ToolResultBlock(size=500, msg_color_idx=0, content="output")
        result = _render_tool_result_full(block)

        assert result is not None
        assert "Result" in result.plain
        assert "500 bytes" in result.plain

    def test_error_result_generic(self):
        """Error result for generic tool shows error label."""
        block = ToolResultBlock(
            size=200,
            is_error=True,
            tool_name="Bash",
            msg_color_idx=0,
            content="error message",
        )
        result = _render_tool_result_full(block)

        assert result is not None
        assert "ERROR" in result.plain
        assert "200 bytes" in result.plain

    def test_summary_shows_header_only(self):
        """Summary renderer shows header, no content."""
        block = ToolResultBlock(
            size=500, tool_name="Bash", msg_color_idx=0, content="output text"
        )
        result = _render_tool_result_summary(block)

        assert result is not None
        plain = result.plain
        assert "Bash" in plain
        assert "500 bytes" in plain
        # Content should NOT appear in summary
        assert "output text" not in plain

    def test_color_preserved_from_block(self):
        """Tool result rendering uses color index from block."""
        # Different color indices — both should render successfully
        block1 = ToolResultBlock(size=500, tool_name="Bash", msg_color_idx=0, content="output")
        block2 = ToolResultBlock(size=500, tool_name="Bash", msg_color_idx=3, content="output")

        result1 = _render_tool_result_full(block1)
        result2 = _render_tool_result_full(block2)

        assert result1 is not None
        assert result2 is not None
        # Both render the same content (generic fallback for Bash)
        assert result1.plain == result2.plain


class TestRenderBlocksToolSummary:
    """Tests for render_blocks tool-use summary when tools filter is off."""

    def test_tool_uses_collapsed_to_summary(self):
        """Consecutive ToolUseBlocks hidden when tools=EXISTENCE."""
        blocks = [
            TextContentBlock(text="hello"),
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
            ToolUseBlock(name="Read", input_size=200, msg_color_idx=1),
            ToolUseBlock(name="Bash", input_size=150, msg_color_idx=2),
            TextContentBlock(text="world"),
        ]
        result = render_blocks(blocks, {"tools": HIDDEN})

        # At EXISTENCE level, tools are fully hidden (0 lines)
        # Should have: text, text = 2 items (tools hidden)
        assert len(result) == 2
        # Check indices
        assert result[0][0] == 0  # first TextContentBlock
        assert result[1][0] == 4  # second TextContentBlock
        # Tools are completely hidden, so no summary content to check

    def test_tool_uses_shown_individually_when_on(self):
        """ToolUseBlocks shown individually when tools=FULL."""
        blocks = [
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
            ToolUseBlock(name="Read", input_size=200, msg_color_idx=1),
        ]
        result = render_blocks(blocks, {"tools": ALWAYS_VISIBLE})

        assert len(result) == 2
        assert result[0][0] == 0
        assert result[1][0] == 1

    def test_single_tool_use_summary(self):
        """Single ToolUseBlock fully hidden at EXISTENCE level."""
        blocks = [
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
        ]
        result = render_blocks(blocks, {"tools": HIDDEN})

        # At EXISTENCE level, tools are fully hidden
        assert len(result) == 0

    def test_tool_result_filtered_when_tools_off(self):
        """ToolResultBlock collapsed to summary at EXISTENCE level."""
        blocks = [
            ToolResultBlock(size=500, tool_name="Read", msg_color_idx=0),
        ]
        result = render_blocks(blocks, {"tools": HIDDEN})

        # Orphaned ToolResultBlock (no preceding ToolUseBlock) is dropped by
        # collapse_tool_runs, so no "used 0 tools" summary appears
        rendered_text = "\n".join(str(s) for s in result)
        assert "used 0 tools" not in rendered_text


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

    def test_result_only_run_produces_no_summary(self):
        """Orphaned ToolResultBlocks (no ToolUseBlock) produce no summary."""
        blocks = [
            ToolResultBlock(size=500, tool_name="Read", msg_color_idx=0),
            ToolResultBlock(size=300, tool_name="Bash", msg_color_idx=1),
        ]
        result = collapse_tool_runs(blocks, tools_on=False)
        # No ToolUseSummaryBlock should be created for result-only runs
        assert len(result) == 0

    def test_mixed_result_only_and_use_runs(self):
        """Result-only run dropped, use run summarized, text preserved."""
        blocks = [
            ToolResultBlock(size=500, tool_name="Read", msg_color_idx=0),
            TextContentBlock(text="middle"),
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=1),
            ToolResultBlock(size=300, tool_name="Bash", msg_color_idx=2),
        ]
        result = collapse_tool_runs(blocks, tools_on=False)
        # Orphaned result dropped, text preserved, use+result summarized
        assert len(result) == 2
        assert type(result[0][1]).__name__ == "TextContentBlock"
        assert type(result[1][1]).__name__ == "ToolUseSummaryBlock"
        assert result[1][1].total == 1


class TestRenderToolUseSummary:
    """Tests for _render_tool_use_summary() renderer."""

    def test_summary_format_plural(self):
        """Multiple tools shows plural format."""
        block = ToolUseSummaryBlock(
            tool_counts={"Bash": 2, "Read": 1},
            total=3,
        )
        result = _render_tool_use_summary(block)

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
        result = _render_tool_use_summary(block)

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
        result = _render_tool_use_summary(block)

        assert result is not None
        styles = [span.style for span in result.spans if span.style]
        has_dim = any("dim" in str(style) for style in styles)
        assert has_dim


class TestRenderTurnToStripsToolSummary:
    """Integration test: tool summary through render_turn_to_strips()."""

    def test_summary_in_strips(self):
        """render_turn_to_strips() with tools=EXISTENCE hides tools completely."""
        from rich.console import Console

        blocks = [
            RoleBlock(role="assistant", msg_index=0),
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0),
            ToolUseBlock(name="Read", input_size=200, msg_color_idx=1),
            ToolUseBlock(name="Bash", input_size=150, msg_color_idx=2),
            NewlineBlock(),
        ]
        console = Console(width=80, force_terminal=True)
        filters = {"tools": HIDDEN, "system": ALWAYS_VISIBLE, "headers": HIDDEN, "metadata": HIDDEN, "budget": HIDDEN}

        strips, block_strip_map = render_turn_to_strips(
            blocks, filters, console, width=80,
        )

        # Extract text from strips
        text = "".join(seg.text for strip in strips for seg in strip._segments)
        # At EXISTENCE level, tools are fully hidden
        assert "Bash" not in text
        assert "Read" not in text
        # Only assistant role should be visible
        assert "ASSISTANT" in text

    def test_individual_tools_in_strips_when_on(self):
        """render_turn_to_strips() with tools=FULL shows individual tool blocks."""
        from rich.console import Console

        blocks = [
            ToolUseBlock(name="Bash", input_size=100, msg_color_idx=0, detail="git status", tool_input={"command": "git status"}),
            ToolUseBlock(name="Read", input_size=200, msg_color_idx=1),
        ]
        console = Console(width=80, force_terminal=True)
        filters = {"tools": ALWAYS_VISIBLE, "system": ALWAYS_VISIBLE, "headers": HIDDEN, "metadata": HIDDEN, "budget": HIDDEN}

        strips, block_strip_map = render_turn_to_strips(
            blocks, filters, console, width=80,
        )

        text = "".join(seg.text for strip in strips for seg in strip._segments)
        assert "Bash" in text
        assert "Read" in text
        assert "git" in text
        # Should NOT have summary
        assert "used" not in text


# ─── New test classes for specialized tool renderers ───────────────────────────


class TestInferLangFromPath:
    """Tests for _infer_lang_from_path helper."""

    def test_python(self):
        assert _infer_lang_from_path("/foo/bar.py") == "python"

    def test_typescript(self):
        assert _infer_lang_from_path("/foo/bar.ts") == "typescript"

    def test_tsx(self):
        assert _infer_lang_from_path("/foo/Component.tsx") == "tsx"

    def test_javascript(self):
        assert _infer_lang_from_path("/foo/bar.js") == "javascript"

    def test_json(self):
        assert _infer_lang_from_path("config.json") == "json"

    def test_rust(self):
        assert _infer_lang_from_path("src/main.rs") == "rust"

    def test_go(self):
        assert _infer_lang_from_path("main.go") == "go"

    def test_yaml(self):
        assert _infer_lang_from_path("config.yaml") == "yaml"

    def test_yml(self):
        assert _infer_lang_from_path("config.yml") == "yaml"

    def test_unknown_extension(self):
        assert _infer_lang_from_path("/foo/bar.xyz") == ""

    def test_no_extension(self):
        assert _infer_lang_from_path("Makefile") == ""

    def test_case_insensitive(self):
        assert _infer_lang_from_path("/foo/BAR.PY") == "python"

    def test_empty_string(self):
        assert _infer_lang_from_path("") == ""


class TestDetailExtractors:
    """Tests for _TOOL_DETAIL_EXTRACTORS — new Write/Edit/Grep/Glob entries."""

    def test_write_extracts_file_path(self):
        from cc_dump.formatting import _tool_detail
        result = _tool_detail("Write", {"file_path": "/foo/bar/baz.py"})
        assert "baz.py" in result

    def test_edit_extracts_file_path(self):
        from cc_dump.formatting import _tool_detail
        result = _tool_detail("Edit", {"file_path": "/foo/bar/baz.ts"})
        assert "baz.ts" in result

    def test_grep_extracts_pattern(self):
        from cc_dump.formatting import _tool_detail
        result = _tool_detail("Grep", {"pattern": "import.*re"})
        assert result == "import.*re"

    def test_glob_extracts_pattern(self):
        from cc_dump.formatting import _tool_detail
        result = _tool_detail("Glob", {"pattern": "**/*.py"})
        assert result == "**/*.py"

    def test_unknown_tool_returns_empty(self):
        from cc_dump.formatting import _tool_detail
        result = _tool_detail("UnknownTool", {"foo": "bar"})
        assert result == ""


class TestToolUseFullBash:
    """Tests for _render_tool_use_bash_full renderer."""

    def test_bash_full_shows_header_and_command(self):
        """Bash full renders header + $ command."""
        from rich.console import Console, Group

        block = ToolUseBlock(
            name="Bash",
            input_size=100,
            msg_color_idx=0,
            tool_input={"command": "git status"},
        )
        result = _render_tool_use_bash_full(block)

        assert result is not None
        # Should be a Group with header + Syntax
        assert isinstance(result, Group)

    def test_bash_full_via_dispatch(self):
        """_render_tool_use_full dispatches Bash to bash-specific renderer."""
        from rich.console import Group

        block = ToolUseBlock(
            name="Bash",
            input_size=100,
            msg_color_idx=0,
            tool_input={"command": "echo hello"},
        )
        result = _render_tool_use_full(block)
        assert isinstance(result, Group)

    def test_bash_full_no_command(self):
        """Bash full with empty command returns header only."""
        block = ToolUseBlock(
            name="Bash",
            input_size=50,
            msg_color_idx=0,
            tool_input={},
        )
        result = _render_tool_use_bash_full(block)
        assert result is not None
        # Without command, returns just header (Text)
        from rich.text import Text
        assert isinstance(result, Text)


class TestToolUseFullEdit:
    """Tests for _render_tool_use_edit_full renderer."""

    def test_edit_full_shows_diff_preview(self):
        """Edit full shows old/new line counts."""
        block = ToolUseBlock(
            name="Edit",
            input_size=200,
            msg_color_idx=0,
            detail="...path/file.py",
            tool_input={
                "file_path": "/foo/file.py",
                "old_string": "line1\nline2\nline3",
                "new_string": "new_line1\nnew_line2\nnew_line3\nnew_line4\nnew_line5",
            },
        )
        result = _render_tool_use_edit_full(block)

        assert result is not None
        plain = result.plain
        assert "Edit" in plain
        assert "old (3 lines)" in plain
        assert "new (5 lines)" in plain

    def test_edit_full_via_dispatch(self):
        """_render_tool_use_full dispatches Edit to edit-specific renderer."""
        block = ToolUseBlock(
            name="Edit",
            input_size=200,
            msg_color_idx=0,
            tool_input={"old_string": "a", "new_string": "b"},
        )
        result = _render_tool_use_full(block)
        assert result is not None
        from rich.text import Text
        assert isinstance(result, Text)

    def test_edit_empty_strings(self):
        """Edit with empty old/new strings renders 0 lines."""
        block = ToolUseBlock(
            name="Edit",
            input_size=50,
            msg_color_idx=0,
            tool_input={"old_string": "", "new_string": ""},
        )
        result = _render_tool_use_edit_full(block)
        assert result is not None
        plain = result.plain
        assert "old (0 lines)" in plain
        assert "new (0 lines)" in plain


class TestToolUseSummaryLevel:
    """Tests confirming ToolUseBlock at summary level uses one-liner."""

    def test_summary_uses_oneliner(self):
        """At summary level, ToolUseBlock should render as one-liner."""
        block = ToolUseBlock(
            name="Bash",
            input_size=100,
            msg_color_idx=0,
            detail="git status",
            tool_input={"command": "git status"},
        )
        result = _render_tool_use_oneliner(block)
        assert result is not None
        plain = result.plain
        assert "[Use: Bash]" in plain
        assert "git status" in plain
        assert "100 bytes" in plain

    def test_unknown_tool_falls_back_to_oneliner(self):
        """Unknown tool in _render_tool_use_full falls back to oneliner."""
        block = ToolUseBlock(
            name="UnknownTool",
            input_size=100,
            msg_color_idx=0,
        )
        result = _render_tool_use_full(block)
        assert result is not None
        from rich.text import Text
        assert isinstance(result, Text)
        assert "[Use: UnknownTool]" in result.plain


class TestToolResultFullRead:
    """Tests for _render_read_content — syntax-highlighted Read results."""

    def test_read_python_file(self):
        """Read result for .py file renders with syntax highlighting."""
        from rich.console import Group

        block = ToolResultBlock(
            size=100,
            tool_name="Read",
            msg_color_idx=0,
            content="def foo():\n    return 42\n",
            tool_input={"file_path": "/src/main.py"},
        )
        result = _render_read_content(block)
        assert result is not None
        assert isinstance(result, Group)

    def test_read_typescript_file(self):
        """Read result for .ts file renders with syntax highlighting."""
        from rich.console import Group

        block = ToolResultBlock(
            size=50,
            tool_name="Read",
            msg_color_idx=0,
            content="const x: number = 42;",
            tool_input={"file_path": "/src/app.ts"},
        )
        result = _render_read_content(block)
        assert isinstance(result, Group)

    def test_read_unknown_extension(self):
        """Read result for unknown extension uses 'text' lexer."""
        from rich.console import Group

        block = ToolResultBlock(
            size=30,
            tool_name="Read",
            msg_color_idx=0,
            content="some content",
            tool_input={"file_path": "/foo/bar.xyz"},
        )
        result = _render_read_content(block)
        assert isinstance(result, Group)

    def test_read_empty_content(self):
        """Read result with empty content returns header only."""
        from rich.text import Text

        block = ToolResultBlock(
            size=0,
            tool_name="Read",
            msg_color_idx=0,
            content="",
            tool_input={"file_path": "/foo/empty.py"},
        )
        result = _render_read_content(block)
        assert result is not None
        assert isinstance(result, Text)

    def test_read_via_dispatch(self):
        """_render_tool_result_full dispatches Read to read-specific renderer."""
        from rich.console import Group

        block = ToolResultBlock(
            size=100,
            tool_name="Read",
            msg_color_idx=0,
            content="content here",
            tool_input={"file_path": "/foo/bar.py"},
        )
        result = _render_tool_result_full(block)
        assert isinstance(result, Group)


class TestToolResultFullWriteEdit:
    """Tests for _render_confirm_content — Write/Edit success/error rendering."""

    def test_write_success_shows_checkmark(self):
        """Write success renders ✓."""
        block = ToolResultBlock(
            size=50,
            tool_name="Write",
            msg_color_idx=0,
            content="File written successfully.",
            is_error=False,
        )
        result = _render_confirm_content(block)
        assert result is not None
        assert "✓" in result.plain

    def test_edit_success_shows_checkmark(self):
        """Edit success renders ✓."""
        block = ToolResultBlock(
            size=50,
            tool_name="Edit",
            msg_color_idx=0,
            content="File edited successfully.",
            is_error=False,
        )
        result = _render_confirm_content(block)
        assert result is not None
        assert "✓" in result.plain

    def test_write_error_shows_content(self):
        """Write error renders error content."""
        block = ToolResultBlock(
            size=100,
            tool_name="Write",
            msg_color_idx=0,
            content="Permission denied: /root/file.txt",
            is_error=True,
        )
        result = _render_confirm_content(block)
        assert result is not None
        plain = result.plain
        assert "Permission denied" in plain
        assert "✓" not in plain

    def test_edit_error_shows_content(self):
        """Edit error renders error content."""
        block = ToolResultBlock(
            size=80,
            tool_name="Edit",
            msg_color_idx=0,
            content="old_string not found in file",
            is_error=True,
        )
        result = _render_confirm_content(block)
        assert result is not None
        assert "old_string not found" in result.plain
        assert "✓" not in result.plain

    def test_write_via_dispatch(self):
        """_render_tool_result_full dispatches Write to confirm renderer."""
        block = ToolResultBlock(
            size=50,
            tool_name="Write",
            msg_color_idx=0,
            content="ok",
            is_error=False,
        )
        result = _render_tool_result_full(block)
        assert result is not None
        assert "✓" in result.plain

    def test_edit_via_dispatch(self):
        """_render_tool_result_full dispatches Edit to confirm renderer."""
        block = ToolResultBlock(
            size=50,
            tool_name="Edit",
            msg_color_idx=0,
            content="ok",
            is_error=False,
        )
        result = _render_tool_result_full(block)
        assert result is not None
        assert "✓" in result.plain


class TestToolResultFullBash:
    """Tests for generic tool result rendering (Bash, Grep, Glob)."""

    def test_bash_result_dim_content(self):
        """Bash result renders header + dim content (generic fallback)."""
        block = ToolResultBlock(
            size=200,
            tool_name="Bash",
            msg_color_idx=0,
            content="On branch main\nnothing to commit",
        )
        result = _render_tool_result_full(block)
        assert result is not None
        plain = result.plain
        assert "Bash" in plain
        assert "On branch main" in plain

    def test_grep_result_generic(self):
        """Grep result uses generic fallback."""
        block = ToolResultBlock(
            size=100,
            tool_name="Grep",
            msg_color_idx=0,
            content="file.py:10:match",
        )
        result = _render_tool_result_full(block)
        assert result is not None
        assert "Grep" in result.plain
        assert "file.py:10:match" in result.plain


class TestToolResultSummaryRenderer:
    """Tests for _render_tool_result_summary — header only, no content."""

    def test_summary_header_only(self):
        """Summary shows header, not content."""
        block = ToolResultBlock(
            size=500,
            tool_name="Read",
            msg_color_idx=0,
            content="def foo(): pass\n" * 20,
            detail="...path/file.py",
        )
        result = _render_tool_result_summary(block)
        assert result is not None
        plain = result.plain
        assert "Read" in plain
        assert "500 bytes" in plain
        assert "...path/file.py" in plain
        # Content should NOT appear
        assert "def foo" not in plain

    def test_summary_error_shows_label(self):
        """Summary for error shows ERROR label."""
        block = ToolResultBlock(
            size=100,
            tool_name="Bash",
            msg_color_idx=0,
            content="error detail here",
            is_error=True,
        )
        result = _render_tool_result_summary(block)
        assert result is not None
        assert "ERROR" in result.plain
        # Content should NOT appear even for errors
        assert "error detail here" not in result.plain


class TestRenderTurnToStripsToolLevels:
    """Integration: render_turn_to_strips with tool blocks at various VisStates."""

    def _render_strips_text(self, blocks, filters):
        """Helper: render blocks and extract plain text from strips."""
        from rich.console import Console
        console = Console(width=80, force_terminal=True)
        strips, _ = render_turn_to_strips(blocks, filters, console, width=80)
        return "".join(seg.text for strip in strips for seg in strip._segments)

    def test_tool_result_full_collapsed_header_only(self):
        """At full collapsed level, tool result shows header only (no content)."""
        blocks = [
            ToolUseBlock(
                name="Read",
                input_size=50,
                msg_color_idx=0,
                detail="...file.py",
            ),
            ToolResultBlock(
                size=500,
                tool_name="Read",
                msg_color_idx=0,
                content="lots of content here\n" * 10,
                detail="...file.py",
            ),
        ]
        # Full collapsed = visible, full, not expanded
        text = self._render_strips_text(
            blocks, {"tools": VisState(True, True, False)}
        )
        assert "Read" in text
        assert "500 bytes" in text
        # Content should NOT appear at full collapsed level (header only)
        assert "lots of content" not in text

    def test_tool_use_full_bash(self):
        """At full level, Bash ToolUse shows syntax-highlighted command."""
        blocks = [
            ToolUseBlock(
                name="Bash",
                input_size=100,
                msg_color_idx=0,
                detail="git status",
                tool_input={"command": "git status"},
            ),
        ]
        text = self._render_strips_text(
            blocks, {"tools": ALWAYS_VISIBLE}
        )
        assert "Bash" in text
        # The command should appear (rendered by Syntax, but extractable)
        assert "git" in text

    def test_tool_result_full_read_syntax(self):
        """At full level, Read result shows syntax-highlighted content."""
        blocks = [
            ToolResultBlock(
                size=100,
                tool_name="Read",
                msg_color_idx=0,
                content="def hello():\n    return 'world'\n",
                tool_input={"file_path": "/foo/bar.py"},
            ),
        ]
        text = self._render_strips_text(
            blocks, {"tools": ALWAYS_VISIBLE}
        )
        assert "Read" in text
        assert "hello" in text

    def test_tool_result_full_write_checkmark(self):
        """At full level, Write result shows checkmark."""
        blocks = [
            ToolResultBlock(
                size=50,
                tool_name="Write",
                msg_color_idx=0,
                content="ok",
                is_error=False,
            ),
        ]
        text = self._render_strips_text(
            blocks, {"tools": ALWAYS_VISIBLE}
        )
        assert "Write" in text
        assert "✓" in text
