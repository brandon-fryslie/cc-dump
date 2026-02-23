"""Rendering tests for special-content marker badges."""

import pytest
from textual.theme import BUILTIN_THEMES

from cc_dump.core.formatting import ConfigContentBlock, HookOutputBlock
from cc_dump.tui.rendering import (
    _render_config_content_summary,
    _render_hook_output_summary,
    set_theme,
)


@pytest.fixture(autouse=True)
def _init_theme():
    set_theme(BUILTIN_THEMES["textual-dark"])


def test_config_summary_shows_claude_md_badge():
    block = ConfigContentBlock(source="/tmp/CLAUDE.md", content="line1\nline2")
    result = _render_config_content_summary(block)
    assert result is not None
    assert "CLAUDE.md" in result.plain


def test_hook_summary_shows_skill_marker_badge():
    block = HookOutputBlock(
        hook_name="system-reminder",
        content="The following skills are available for use with the Skill tool:",
    )
    result = _render_hook_output_summary(block)
    assert result is not None
    assert "skills" in result.plain
