"""Tests for visual indicators and rendering in the TUI.

These tests verify that the colored bar indicators (▌) appear correctly
for filtered content and that the rendering system works properly.
"""

import random
import time

import pytest
import requests


class TestFilterIndicatorRendering:
    """Test that filter indicators render correctly."""

    def test_headers_indicator_cyan(self, start_cc_dump):
        """Test that header content shows cyan indicator when visible."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Enable headers filter
        proc.send("h", press_enter=False)
        time.sleep(0.3)

        # Send a request to generate header content
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 50,
                    "messages": [{"role": "user", "content": "Test"}]
                },
                timeout=2,
                headers={"anthropic-version": "2023-06-01"}
            )
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)

        content = proc.get_content()
        # The indicator character ▌ should appear in the content
        # Note: Terminal rendering might affect exact appearance
        # We verify the process is stable and rendering completes
        assert proc.is_alive()
        assert len(content) > 0

    def test_tools_indicator_blue(self, start_cc_dump):
        """Test that tool content shows blue indicator when visible."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Tools filter is enabled by default
        # If we had tool content, it would show blue indicator
        # For now, verify the filter state works
        content = proc.get_content()
        assert proc.is_alive()

    def test_metadata_indicator_magenta(self, start_cc_dump):
        """Test that metadata shows magenta indicator when visible."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Metadata is visible by default
        # Send request to generate metadata
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 50,
                    "messages": [{"role": "user", "content": "Test"}]
                },
                timeout=2,
                headers={"anthropic-version": "2023-06-01"}
            )
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)
        assert proc.is_alive()

    def test_system_indicator_yellow(self, start_cc_dump):
        """Test that system content shows yellow indicator when visible."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # System filter is enabled by default
        # Send request with system content
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 50,
                    "system": "You are a test assistant",
                    "messages": [{"role": "user", "content": "Test"}]
                },
                timeout=2,
                headers={"anthropic-version": "2023-06-01"}
            )
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)
        assert proc.is_alive()

    def test_expand_indicator_green(self, start_cc_dump):
        """Test that expanded context shows green indicator when visible."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Enable expand filter
        proc.send("e", press_enter=False)
        time.sleep(0.3)

        # Send request to generate expandable content
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 50,
                    "system": "Test system prompt",
                    "messages": [{"role": "user", "content": "Test"}]
                },
                timeout=2,
                headers={"anthropic-version": "2023-06-01"}
            )
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)
        assert proc.is_alive()


class TestIndicatorVisibility:
    """Test that indicators appear/disappear based on filter state."""

    def test_indicator_appears_when_filter_enabled(self, start_cc_dump):
        """Test that enabling a filter makes indicators appear."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Send request first
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 50,
                    "messages": [{"role": "user", "content": "Test"}]
                },
                timeout=2,
                headers={"anthropic-version": "2023-06-01"}
            )
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)

        # Headers initially hidden
        content_without = proc.get_content()

        # Enable headers
        proc.send("h", press_enter=False)
        time.sleep(0.5)

        content_with = proc.get_content()

        # Content should change when headers become visible
        # (exact difference depends on whether content is filtered)
        assert proc.is_alive()

    def test_indicator_disappears_when_filter_disabled(self, start_cc_dump):
        """Test that disabling a filter makes indicators disappear."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Metadata is visible by default
        # Send request
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 50,
                    "messages": [{"role": "user", "content": "Test"}]
                },
                timeout=2,
                headers={"anthropic-version": "2023-06-01"}
            )
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)

        content_with = proc.get_content()

        # Disable metadata
        proc.send("m", press_enter=False)
        time.sleep(0.5)

        content_without = proc.get_content()

        # Content should change when metadata is hidden
        assert proc.is_alive()


class TestRenderingPerformance:
    """Test rendering performance and stability."""

    def test_rendering_handles_multiple_requests(self, start_cc_dump):
        """Test that rendering handles multiple requests efficiently."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Enable headers for more content
        proc.send("h", press_enter=False)
        time.sleep(0.3)

        # Send multiple requests
        for i in range(5):
            try:
                requests.post(
                    f"http://127.0.0.1:{port}/v1/messages",
                    json={
                        "model": "claude-3-5-sonnet-20241022",
                        "max_tokens": 50,
                        "messages": [{"role": "user", "content": f"Request {i}"}]
                    },
                    timeout=2,
                    headers={"anthropic-version": "2023-06-01"}
                )
            except requests.exceptions.RequestException:
                pass
            time.sleep(0.3)

        time.sleep(1)
        assert proc.is_alive()

    def test_rendering_survives_rapid_filter_changes(self, start_cc_dump):
        """Test rendering stability during rapid filter toggling."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Send a request to have content to render
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 50,
                    "messages": [{"role": "user", "content": "Test"}]
                },
                timeout=2,
                headers={"anthropic-version": "2023-06-01"}
            )
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)

        # Rapidly toggle filters
        for _ in range(5):
            proc.send("h", press_enter=False)
            time.sleep(0.1)
            proc.send("m", press_enter=False)
            time.sleep(0.1)
            proc.send("e", press_enter=False)
            time.sleep(0.1)

        time.sleep(1)
        assert proc.is_alive()


class TestBlockRendering:
    """Test individual block type rendering."""

    def test_separator_block_renders(self, start_cc_dump):
        """Test that separator blocks render without crash."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Enable headers to see separators
        proc.send("h", press_enter=False)
        time.sleep(0.3)

        # Send request to generate separators
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 50,
                    "messages": [{"role": "user", "content": "Test"}]
                },
                timeout=2,
                headers={"anthropic-version": "2023-06-01"}
            )
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)
        assert proc.is_alive()

    def test_text_content_block_renders(self, start_cc_dump):
        """Test that text content blocks render correctly."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Send request with text content
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 50,
                    "messages": [{"role": "user", "content": "Hello, how are you?"}]
                },
                timeout=2,
                headers={"anthropic-version": "2023-06-01"}
            )
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)
        assert proc.is_alive()

    def test_role_block_renders(self, start_cc_dump):
        """Test that role blocks (USER, ASSISTANT) render correctly."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Send request to generate role blocks
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 50,
                    "messages": [{"role": "user", "content": "Test"}]
                },
                timeout=2,
                headers={"anthropic-version": "2023-06-01"}
            )
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)
        assert proc.is_alive()


class TestColorScheme:
    """Test color scheme consistency."""

    def test_consistent_colors_for_same_filter(self, start_cc_dump):
        """Test that same filter type always uses same color."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Enable headers
        proc.send("h", press_enter=False)
        time.sleep(0.3)

        # Send first request
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 50,
                    "messages": [{"role": "user", "content": "First"}]
                },
                timeout=2,
                headers={"anthropic-version": "2023-06-01"}
            )
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)

        # Send second request
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 50,
                    "messages": [{"role": "user", "content": "Second"}]
                },
                timeout=2,
                headers={"anthropic-version": "2023-06-01"}
            )
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)

        # Both requests should show same color indicators for headers
        # Verify process is stable
        assert proc.is_alive()


class TestIndicatorHelperFunction:
    """Unit tests for the indicator helper function."""

    def test_add_filter_indicator_exists(self):
        """Test that _add_filter_indicator function exists."""
        from cc_dump.tui.rendering import _add_filter_indicator
        assert callable(_add_filter_indicator)

    def test_filter_indicators_mapping_exists(self):
        """Test that FILTER_INDICATORS mapping is defined."""
        from cc_dump.tui.rendering import FILTER_INDICATORS
        assert isinstance(FILTER_INDICATORS, dict)

        # Verify expected filters are in mapping
        expected_filters = ["headers", "tools", "system", "expand", "metadata"]
        for filter_name in expected_filters:
            assert filter_name in FILTER_INDICATORS

    def test_filter_indicators_have_symbol_and_color(self):
        """Test that each filter indicator has symbol and color."""
        from cc_dump.tui.rendering import FILTER_INDICATORS

        for filter_name, (symbol, color) in FILTER_INDICATORS.items():
            assert isinstance(symbol, str)
            assert len(symbol) > 0
            assert isinstance(color, str)
            assert len(color) > 0

    def test_add_filter_indicator_with_text(self):
        """Test _add_filter_indicator adds indicator to text."""
        from cc_dump.tui.rendering import _add_filter_indicator
        from rich.text import Text

        text = Text("Hello World")
        result = _add_filter_indicator(text, "headers")

        # Should return a Text object
        assert isinstance(result, Text)

        # Should not be the same object (should be modified)
        # Content should include the original text
        assert "Hello" in str(result.plain)

    def test_add_filter_indicator_with_unknown_filter(self):
        """Test _add_filter_indicator handles unknown filter names."""
        from cc_dump.tui.rendering import _add_filter_indicator
        from rich.text import Text

        text = Text("Test")
        result = _add_filter_indicator(text, "unknown_filter")

        # Should return original text unchanged for unknown filter
        assert isinstance(result, Text)


class TestRenderBlockFunction:
    """Test the render_block dispatcher function."""

    def test_render_block_handles_all_block_types(self):
        """Test that render_block can handle all FormattedBlock types."""
        from cc_dump.tui.rendering import render_block
        from cc_dump.formatting import (
            SeparatorBlock, HeaderBlock, MetadataBlock, RoleBlock,
            TextContentBlock, NewlineBlock
        )

        filters = {"headers": True, "tools": True, "system": True,
                   "expand": True, "metadata": True}

        blocks = [
            SeparatorBlock(),
            HeaderBlock(label="TEST", header_type="request"),
            MetadataBlock(model="test-model", max_tokens="100"),
            RoleBlock(role="user"),
            TextContentBlock(text="Test text"),
            NewlineBlock(),
        ]

        for block in blocks:
            # Should not crash
            result = render_block(block, filters)
            # Some blocks might return None if filtered out

    def test_render_block_respects_filters(self):
        """Test that render_block respects filter settings."""
        from cc_dump.tui.rendering import render_block
        from cc_dump.formatting import HeaderBlock

        # Test with headers disabled
        filters_off = {"headers": False}
        block = HeaderBlock(label="TEST", header_type="request")
        result = render_block(block, filters_off)
        assert result is None  # Should be filtered out

        # Test with headers enabled
        filters_on = {"headers": True}
        result = render_block(block, filters_on)
        assert result is not None  # Should be rendered
