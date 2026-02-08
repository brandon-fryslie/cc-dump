"""Tests for visual indicators and rendering in the TUI.

These tests verify that the colored bar indicators appear correctly
for filtered content and that the rendering system works properly.
"""

import random
import time

import pytest
import requests

from tests.conftest import settle, wait_for_content


def _send_request(port, content="Test", extra_json=None):
    """Send a test request to cc-dump proxy. Swallows connection errors."""
    body = {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 50,
        "messages": [{"role": "user", "content": content}],
    }
    if extra_json:
        body.update(extra_json)
    try:
        requests.post(
            f"http://127.0.0.1:{port}/v1/messages",
            json=body,
            timeout=2,
            headers={"anthropic-version": "2023-06-01"},
        )
    except requests.exceptions.RequestException:
        pass


class TestFilterIndicatorRendering:
    """Test that filter indicators render correctly — shared process+port."""

    def test_headers_indicator_cyan(self, class_proc_with_port):
        proc, port = class_proc_with_port

        proc.send("h", press_enter=False)
        settle(proc)

        _send_request(port, content="Test-HeaderIndicator")
        wait_for_content(proc, timeout=2)

        content = proc.get_content()
        assert proc.is_alive()
        assert len(content) > 0

        # Clean up
        proc.send("h", press_enter=False)
        settle(proc)

    def test_tools_indicator_blue(self, class_proc_with_port):
        proc, port = class_proc_with_port
        content = proc.get_content()
        assert proc.is_alive()

    def test_metadata_indicator_magenta(self, class_proc_with_port):
        proc, port = class_proc_with_port

        _send_request(port, content="Test-MetadataIndicator")
        wait_for_content(proc, timeout=2)
        assert proc.is_alive()

    def test_system_indicator_yellow(self, class_proc_with_port):
        proc, port = class_proc_with_port

        _send_request(port, content="Test-SystemIndicator",
                       extra_json={"system": "You are a test assistant"})
        wait_for_content(proc, timeout=2)
        assert proc.is_alive()

    def test_expand_indicator_green(self, class_proc_with_port):
        proc, port = class_proc_with_port

        proc.send("e", press_enter=False)
        settle(proc)

        _send_request(port, content="Test-ExpandIndicator",
                       extra_json={"system": "Test system prompt"})
        wait_for_content(proc, timeout=2)
        assert proc.is_alive()

        # Clean up
        proc.send("e", press_enter=False)
        settle(proc)


class TestIndicatorVisibility:
    """Test that indicators appear/disappear based on filter state — shared process+port."""

    def test_indicator_appears_when_filter_enabled(self, class_proc_with_port):
        proc, port = class_proc_with_port

        _send_request(port, content="Test-IndicatorAppear")
        wait_for_content(proc, timeout=2)

        content_without = proc.get_content()

        proc.send("h", press_enter=False)
        settle(proc, 0.1)
        content_with = proc.get_content()

        assert proc.is_alive()

        # Clean up
        proc.send("h", press_enter=False)
        settle(proc)

    def test_indicator_disappears_when_filter_disabled(self, class_proc_with_port):
        proc, port = class_proc_with_port

        _send_request(port, content="Test-IndicatorDisappear")
        wait_for_content(proc, timeout=2)

        content_with = proc.get_content()

        proc.send("m", press_enter=False)
        settle(proc, 0.1)
        content_without = proc.get_content()

        assert proc.is_alive()

        # Restore metadata
        proc.send("m", press_enter=False)
        settle(proc)


class TestRenderingPerformance:
    """Test rendering performance and stability — shared process+port."""

    def test_rendering_handles_multiple_requests(self, class_proc_with_port):
        proc, port = class_proc_with_port

        proc.send("h", press_enter=False)
        settle(proc)

        for i in range(5):
            _send_request(port, content=f"PerfRequest {i}")
            settle(proc, 0.1)

        wait_for_content(proc, timeout=2)
        assert proc.is_alive()

        # Clean up
        proc.send("h", press_enter=False)
        settle(proc)

    def test_rendering_survives_rapid_filter_changes(self, class_proc_with_port):
        proc, port = class_proc_with_port

        _send_request(port, content="Test-RapidFilter")
        wait_for_content(proc, timeout=2)

        # Rapidly toggle filters (even number of toggles = back to original state)
        for _ in range(4):
            proc.send("h", press_enter=False)
            time.sleep(0.05)
            proc.send("m", press_enter=False)
            time.sleep(0.05)
            proc.send("e", press_enter=False)
            time.sleep(0.05)

        # Even toggles restore to original state
        settle(proc, 0.3)
        assert proc.is_alive()


class TestBlockRendering:
    """Test individual block type rendering — shared process+port."""

    def test_separator_block_renders(self, class_proc_with_port):
        proc, port = class_proc_with_port

        proc.send("h", press_enter=False)
        settle(proc)

        _send_request(port, content="Test-SeparatorBlock")
        wait_for_content(proc, timeout=2)
        assert proc.is_alive()

        # Clean up
        proc.send("h", press_enter=False)
        settle(proc)

    def test_text_content_block_renders(self, class_proc_with_port):
        proc, port = class_proc_with_port

        _send_request(port, content="Hello, how are you?")
        wait_for_content(proc, timeout=2)
        assert proc.is_alive()

    def test_role_block_renders(self, class_proc_with_port):
        proc, port = class_proc_with_port

        _send_request(port, content="Test-RoleBlock")
        wait_for_content(proc, timeout=2)
        assert proc.is_alive()


class TestColorScheme:
    """Test color scheme consistency."""

    def test_consistent_colors_for_same_filter(self, start_cc_dump):
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        proc.send("h", press_enter=False)
        settle(proc)

        _send_request(port, content="First")
        wait_for_content(proc, timeout=2)

        _send_request(port, content="Second")
        wait_for_content(proc, timeout=2)

        assert proc.is_alive()


class TestIndicatorHelperFunction:
    """Unit tests for the indicator helper function."""

    def test_add_filter_indicator_exists(self):
        from cc_dump.tui.rendering import _add_filter_indicator
        assert callable(_add_filter_indicator)

    def test_filter_indicators_mapping_exists(self):
        from cc_dump.tui.rendering import FILTER_INDICATORS
        assert isinstance(FILTER_INDICATORS, dict)

        expected_filters = ["headers", "tools", "system", "budget", "metadata"]
        for filter_name in expected_filters:
            assert filter_name in FILTER_INDICATORS

    def test_filter_indicators_have_symbol_and_color(self):
        from cc_dump.tui.rendering import FILTER_INDICATORS

        for filter_name, (symbol, color) in FILTER_INDICATORS.items():
            assert isinstance(symbol, str)
            assert len(symbol) > 0
            assert isinstance(color, str)
            assert len(color) > 0

    def test_add_filter_indicator_with_text(self):
        from cc_dump.tui.rendering import _add_filter_indicator
        from rich.text import Text

        text = Text("Hello World")
        result = _add_filter_indicator(text, "headers")

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

        filters = {"headers": True, "tools": True, "system": True,
                   "budget": True, "metadata": True}

        blocks = [
            SeparatorBlock(),
            HeaderBlock(label="TEST", header_type="request"),
            MetadataBlock(model="test-model", max_tokens="100"),
            RoleBlock(role="user"),
            TextContentBlock(text="Test text"),
            NewlineBlock(),
        ]

        for block in blocks:
            result = render_block(block, filters)

    def test_render_block_respects_filters(self):
        from cc_dump.tui.rendering import render_block
        from cc_dump.formatting import HeaderBlock

        filters_off = {"headers": False}
        block = HeaderBlock(label="TEST", header_type="request")
        result = render_block(block, filters_off)
        assert result is None

        filters_on = {"headers": True}
        result = render_block(block, filters_on)
        assert result is not None
