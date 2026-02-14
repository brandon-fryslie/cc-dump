"""Unit tests for visual indicators and rendering helpers."""


class TestIndicatorHelperFunction:
    """Unit tests for the indicator helper function."""

    def test_add_filter_indicator_exists(self):
        from cc_dump.tui.rendering import _add_filter_indicator
        assert callable(_add_filter_indicator)

    def test_filter_indicators_mapping_exists(self):
        from cc_dump.tui import rendering
        assert isinstance(rendering.FILTER_INDICATORS, dict)

        expected_filters = ["headers", "tools", "system", "budget", "metadata"]
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
        result = rendering._add_filter_indicator(text, "headers")

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
        from cc_dump.formatting import (
            SeparatorBlock, HeaderBlock, MetadataBlock, RoleBlock,
            TextContentBlock, NewlineBlock
        )

        blocks = [
            SeparatorBlock(),
            HeaderBlock(label="TEST", header_type="request"),
            MetadataBlock(model="test-model", max_tokens="100"),
            RoleBlock(role="user"),
            TextContentBlock(content="Test text"),
            NewlineBlock(),
        ]

        for block in blocks:
            result = render_block(block)
            # All blocks should render successfully (return some Text)
            assert result is not None

    def test_render_block_with_full_content(self):
        from cc_dump.tui.rendering import render_block
        from cc_dump.formatting import HeaderBlock

        block = HeaderBlock(label="TEST", header_type="request")
        result = render_block(block)
        # Should return full rendering
        assert result is not None
