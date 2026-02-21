"""Behavioral state-matrix tests for block rendering.

Verifies that high-impact blocks produce distinct output across SC/SE/FC/FE.
"""

from rich.console import Console
from textual.theme import BUILTIN_THEMES

from cc_dump.formatting import (
    Category,
    HttpHeadersBlock,
    TextContentBlock,
    ToolResultBlock,
    ToolUseBlock,
    VisState,
)
from cc_dump.tui.rendering import render_turn_to_strips, set_theme


SUMMARY_COLLAPSED = VisState(True, False, False)
SUMMARY_EXPANDED = VisState(True, False, True)
FULL_COLLAPSED = VisState(True, True, False)
FULL_EXPANDED = VisState(True, True, True)


def _render_plain(block, category: str, vis: VisState, width: int = 120) -> tuple[str, int]:
    console = Console(width=width, force_terminal=True)
    strips, _, _ = render_turn_to_strips([block], {category: vis}, console, width=width)
    lines = ["".join(seg.text for seg in strip._segments) for strip in strips]
    return "\n".join(lines), len(lines)


def setup_module() -> None:
    set_theme(BUILTIN_THEMES["textual-dark"])


def test_text_content_state_matrix_is_distinct():
    code_lines = "\n".join(f"line {i}" for i in range(1, 31))
    content = f"```text\n{code_lines}\n```"
    block = TextContentBlock(content=content, category=Category.ASSISTANT)

    sc_text, sc_lines = _render_plain(block, "assistant", SUMMARY_COLLAPSED)
    se_text, se_lines = _render_plain(block, "assistant", SUMMARY_EXPANDED)
    fc_text, fc_lines = _render_plain(block, "assistant", FULL_COLLAPSED)
    fe_text, fe_lines = _render_plain(block, "assistant", FULL_EXPANDED)

    assert "(32 lines)" in sc_text
    assert "more lines" in se_text
    assert sc_text != fc_text
    assert se_text != fe_text
    assert fc_lines < fe_lines
    assert se_lines < fe_lines


def test_tool_use_state_matrix_is_distinct():
    block = ToolUseBlock(
        name="Bash",
        input_size=8,
        msg_color_idx=0,
        detail="git status",
        description="Run shell commands in a controlled environment.",
        tool_input={"command": "git status\npwd\nls -la"},
    )

    sc_text, _ = _render_plain(block, "tools", SUMMARY_COLLAPSED)
    se_text, _ = _render_plain(block, "tools", SUMMARY_EXPANDED)
    fc_text, _ = _render_plain(block, "tools", FULL_COLLAPSED)
    fe_text, _ = _render_plain(block, "tools", FULL_EXPANDED)

    assert "[Use: Bash]" in sc_text
    assert "lines" not in sc_text
    assert "git status" in se_text
    assert "lines" in se_text
    assert "$ git status" in fc_text
    assert "Run shell commands" in fe_text
    assert sc_text != fc_text
    assert se_text != fe_text


def test_tool_result_state_matrix_is_distinct():
    content = "\n".join(f"result line {i}" for i in range(1, 20))
    block = ToolResultBlock(
        size=19,
        tool_name="Read",
        detail="/tmp/example.py",
        msg_color_idx=0,
        content=content,
        tool_input={"file_path": "/tmp/example.py"},
    )

    sc_text, _ = _render_plain(block, "tools", SUMMARY_COLLAPSED)
    se_text, _ = _render_plain(block, "tools", SUMMARY_EXPANDED)
    fc_text, _ = _render_plain(block, "tools", FULL_COLLAPSED)
    fe_text, _ = _render_plain(block, "tools", FULL_EXPANDED)

    assert "[Result]" in sc_text
    assert "Read" in se_text
    assert "result line 1" in se_text
    assert "Read" in fc_text
    assert "result line 10" not in fc_text
    assert "result line 10" in fe_text
    assert sc_text != fc_text
    assert se_text != fe_text


def test_http_headers_state_matrix_is_distinct():
    headers = {f"x-header-{i}": f"value-{i}" for i in range(1, 12)}
    block = HttpHeadersBlock(headers=headers, header_type="response", status_code=200)

    sc_text, _ = _render_plain(block, "metadata", SUMMARY_COLLAPSED)
    se_text, _ = _render_plain(block, "metadata", SUMMARY_EXPANDED)
    fc_text, _ = _render_plain(block, "metadata", FULL_COLLAPSED)
    fe_text, _ = _render_plain(block, "metadata", FULL_EXPANDED)

    assert "11 headers" in sc_text
    assert "more headers" in se_text
    assert "···" in fc_text
    assert "x-header-11" in fe_text
    assert sc_text != se_text
    assert fc_text != fe_text
