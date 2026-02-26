"""Unit tests for visual indicators and rendering helpers."""


class TestIndicatorHelperFunction:
    """Unit tests for the indicator helper function."""

    def test_add_filter_indicator_exists(self):
        from cc_dump.tui.rendering import _add_filter_indicator
        assert callable(_add_filter_indicator)

    def test_filter_indicators_mapping_exists(self):
        from cc_dump.tui import rendering
        assert isinstance(rendering.FILTER_INDICATORS, dict)

        expected_filters = ["tools", "system", "metadata", "user", "assistant", "thinking"]
        for filter_name in expected_filters:
            assert filter_name in rendering.FILTER_INDICATORS

    def test_filter_indicators_have_symbol_and_color(self):
        from cc_dump.tui import rendering

        for filter_name, (symbol, color) in rendering.FILTER_INDICATORS.items():
            assert isinstance(symbol, str)
            assert len(symbol) > 0
            assert isinstance(color, str)
            assert len(color) > 0

    def test_add_filter_indicator_with_text(self):
        from cc_dump.tui import rendering
        from rich.text import Text

        text = Text("Hello World")
        result = rendering._add_filter_indicator(text, "tools")

        assert isinstance(result, Text)
        assert "Hello" in str(result.plain)

    def test_add_filter_indicator_with_unknown_filter(self):
        from cc_dump.tui.rendering import _add_filter_indicator
        from rich.text import Text

        text = Text("Test")
        result = _add_filter_indicator(text, "unknown_filter")
        assert isinstance(result, Text)


class TestRenderBlockFunction:
    """Test the render_block dispatcher function."""

    def test_render_block_handles_all_block_types(self):
        from cc_dump.tui.rendering import render_block
        from cc_dump.core.formatting import (
            SeparatorBlock, HeaderBlock, MetadataBlock, MessageBlock,
            TextContentBlock, NewlineBlock
        )

        blocks = [
            SeparatorBlock(),
            HeaderBlock(label="TEST", header_type="request"),
            MetadataBlock(model="test-model", max_tokens="100"),
            MessageBlock(role="user", msg_index=0, children=[]),
            TextContentBlock(content="Test text"),
            NewlineBlock(),
        ]

        for block in blocks:
            result = render_block(block)
            # All blocks should render successfully (return some Text)
            assert result is not None

    def test_render_block_with_full_content(self):
        from cc_dump.tui.rendering import render_block
        from cc_dump.core.formatting import HeaderBlock

        block = HeaderBlock(label="TEST", header_type="request")
        result = render_block(block)
        # Should return full rendering
        assert result is not None


class TestToolDefRendering:
    """Regression tests for ToolDefBlock rendering behavior."""

    def _render_plain(self, renderable) -> str:
        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        console = Console(file=buf, width=120, force_terminal=False, color_system=None)
        console.print(renderable)
        return buf.getvalue()

    def test_tool_def_full_renderer_includes_schema_and_required_markers(self):
        from cc_dump.tui.rendering import render_block
        from cc_dump.core.formatting import ToolDefBlock

        block = ToolDefBlock(
            name="Read",
            description="Read a file from disk",
            token_estimate=123,
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "offset": {"type": "integer"},
                },
                "required": ["file_path"],
            },
        )
        text = self._render_plain(render_block(block))
        assert "Read" in text
        assert "tokens" in text
        assert "parameters:" in text
        assert "file_path*" in text
        assert "offset" in text
        assert "string" in text
        assert "integer" in text

    def test_tool_def_summary_renderer_shows_compact_header(self):
        from cc_dump.tui.rendering import RENDERERS
        from cc_dump.core.formatting import ToolDefBlock

        block = ToolDefBlock(name="Bash", token_estimate=77)
        renderer = RENDERERS[("ToolDefBlock", True, False, False)]
        text = self._render_plain(renderer(block))
        assert "Bash" in text
        assert "tokens" in text


class TestNamedDefinitionChildRendering:
    """Regression tests for shared named-child renderer behavior."""

    def _render_plain(self, renderable) -> str:
        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        console = Console(file=buf, width=120, force_terminal=False, color_system=None)
        console.print(renderable)
        return buf.getvalue()

    def test_skill_def_child_renderer(self):
        from cc_dump.tui.rendering import render_block
        from cc_dump.core.formatting import SkillDefChild

        block = SkillDefChild(name="review-pr", description="Review pull requests")
        text = self._render_plain(render_block(block))
        assert "review-pr" in text
        assert "Review pull requests" in text

    def test_agent_def_child_renderer(self):
        from cc_dump.tui.rendering import render_block
        from cc_dump.core.formatting import AgentDefChild

        block = AgentDefChild(name="researcher", description="Gather context")
        text = self._render_plain(render_block(block))
        assert "researcher" in text
        assert "Gather context" in text
