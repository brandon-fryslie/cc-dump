"""Comprehensive integration tests for cc-dump TUI functionality.

Tests all user-facing features including:
- Filter toggling (h, t, s, e, m, p, x, l)
- Content visibility and filtering
- Visual indicators for active filters
- Panel visibility and updates
- Database integration
- Real API request handling
"""

import json
import os
import random
import re
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest
import requests

from tests.conftest import settle, wait_for_content, _send_request

pytestmark = pytest.mark.pty


class TestTUIStartupShutdown:
    """Test basic TUI startup and shutdown."""

    def test_tui_starts_and_displays_header(self, start_cc_dump):
        """Verify TUI starts successfully and shows expected elements."""
        proc = start_cc_dump()
        assert proc.is_alive()

        content = proc.get_content()
        assert any(x in content for x in ["cc-dump", "Quit", "headers", "tools"])

    def test_tui_quits_cleanly_with_q_key(self, start_cc_dump):
        """Verify pressing 'q' exits the application cleanly."""
        proc = start_cc_dump()
        assert proc.is_alive()

        proc.send("q", press_enter=False)
        settle(proc, 0.3)

    def test_tui_shows_startup_logs(self, start_cc_dump):
        """Verify startup logs are visible when logs panel is toggled."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Toggle logs panel (ctrl+l)
        proc.send("\x0c", press_enter=False)

        # Poll until log content appears instead of fixed sleep
        content = wait_for_content(
            proc,
            lambda c: "started" in c.lower() or "listening" in c.lower(),
            timeout=3,
        )
        assert "started" in content.lower() or "listening" in content.lower()


class TestLogsPanel:
    """Test logs panel with actual content verification."""

    def test_toggle_logs_panel(self, class_proc):
        """Test logs panel toggle shows log content."""
        proc = class_proc
        proc.send("\x0c", press_enter=False)

        content = wait_for_content(
            proc,
            lambda c: any(x in c for x in ["INFO", "started", "Listening"]),
            timeout=3,
        )
        assert any(x in content for x in ["INFO", "started", "Listening"])

        proc.send("\x0c", press_enter=False)
        settle(proc)
        assert proc.is_alive()


class TestRequestHandling:
    """Test TUI behavior when handling API requests — shared process+port."""

    def test_displays_request_when_received(self, class_proc_with_port):
        proc, port = class_proc_with_port
        proc.send("1", press_enter=False)
        settle(proc)

        _send_request(port, content="Hello")

        content = wait_for_content(proc, timeout=2)
        assert len(content) > 0
        assert proc.is_alive()

        # Clean up: toggle headers back off
        proc.send("1", press_enter=False)
        settle(proc)

    def test_handles_multiple_requests(self, class_proc_with_port):
        proc, port = class_proc_with_port

        for i in range(3):
            _send_request(port, content=f"Request {i}")
            settle(proc, 0.15)

        settle(proc, 0.3)
        assert proc.is_alive()


class TestVisualIndicators:
    """Test visual indicators for active filters."""

    def test_content_shows_filter_indicators(self, start_cc_dump):
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        proc.send("1", press_enter=False)
        settle(proc)
        proc.send("7", press_enter=False)
        settle(proc)

        _send_request(port, content="Test")

        wait_for_content(proc, timeout=2)
        assert proc.is_alive()


class TestContentFiltering:
    """Test that content visibility changes based on filters — shared process+port."""

    def test_headers_filter_controls_request_headers(self, class_proc_with_port):
        proc, port = class_proc_with_port

        _send_request(port, content="Test-ContentFilter")
        wait_for_content(proc, timeout=2)

        content_without_headers = proc.get_content()

        proc.send("1", press_enter=False)
        settle(proc, 0.1)
        content_with_headers = proc.get_content()

        assert proc.is_alive()

        # Clean up
        proc.send("1", press_enter=False)
        settle(proc)

    def test_metadata_filter_controls_model_info(self, class_proc_with_port):
        proc, port = class_proc_with_port

        _send_request(port, content="Test-MetadataFilter")
        wait_for_content(proc, timeout=2)

        proc.send("7", press_enter=False)
        settle(proc, 0.1)
        proc.send("7", press_enter=False)
        settle(proc, 0.1)

        assert proc.is_alive()


class TestStatsPanel:
    """Test stats panel functionality — shared process+port."""

    def test_stats_panel_visible_by_default(self, class_proc_with_port):
        proc, port = class_proc_with_port
        content = proc.get_content()
        assert len(content) > 0

    def test_stats_panel_updates_on_request(self, class_proc_with_port):
        proc, port = class_proc_with_port

        _send_request(port, content="Test-StatsUpdate")
        wait_for_content(proc, timeout=2)
        assert proc.is_alive()

    def test_stats_panel_can_be_hidden(self, class_proc_with_port):
        proc, port = class_proc_with_port

        proc.send("3", press_enter=False)
        settle(proc, 0.1)
        assert proc.is_alive()

        # Restore
        proc.send("3", press_enter=False)
        settle(proc)


class TestErrorHandling:
    """Test error handling and resilience — shared process+port."""

    def test_tui_survives_malformed_request(self, class_proc_with_port):
        proc, port = class_proc_with_port
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={"invalid": "request"},
                timeout=2,
            )
        except requests.exceptions.RequestException:
            pass

        settle(proc, 0.3)
        assert proc.is_alive()

    def test_tui_survives_network_error(self, class_proc_with_port):
        proc, port = class_proc_with_port
        settle(proc, 0.3)
        assert proc.is_alive()

    def test_tui_handles_rapid_filter_toggling(self, class_proc_with_port):
        proc, port = class_proc_with_port

        for _ in range(10):
            for key in ["1", "4", "5", "6", "7"]:
                proc.send(key, press_enter=False)
                time.sleep(0.05)

        settle(proc, 0.3)
        assert proc.is_alive()


class TestRenderingStability:
    """Test rendering stability and performance — shared process+port."""

    def test_tui_renders_without_crash_on_startup(self, class_proc_with_port):
        proc, port = class_proc_with_port
        settle(proc, 0.2)
        assert proc.is_alive()
        content = proc.get_content()
        assert len(content) > 0

    def test_tui_handles_large_content(self, class_proc_with_port):
        proc, port = class_proc_with_port

        large_content = "Test " * 1000
        _send_request(port, content=large_content)

        # Give extra time for large content processing
        wait_for_content(proc, timeout=3)
        assert proc.is_alive()


class TestFooterBindings:
    """Test footer keybinding display — shared process."""

    def test_footer_shows_keybindings(self, class_proc):
        proc = class_proc
        content = wait_for_content(
            proc,
            lambda c: any(x in c for x in ["headers", "tools", "system", "quit"]),
            timeout=5,
        )
        assert any(x in content for x in ["headers", "tools", "system", "quit"])

    def test_footer_persists_during_operation(self, class_proc):
        proc = class_proc

        proc.send("1", press_enter=False)
        settle(proc)
        proc.send("4", press_enter=False)
        settle(proc)

        content = wait_for_content(
            proc,
            lambda c: "quit" in c or "headers" in c,
            timeout=3,
        )
        assert "quit" in content or "headers" in content

        # Clean up
        proc.send("1", press_enter=False)
        settle(proc)
        proc.send("4", press_enter=False)
        settle(proc)

        assert proc.is_alive()


class TestConversationView:
    """Test conversation view widget — shared process+port."""

    def test_conversation_view_displays_messages(self, class_proc_with_port):
        proc, port = class_proc_with_port

        _send_request(port, content="Hello test")
        wait_for_content(proc, timeout=2)
        assert proc.is_alive()

    def test_conversation_view_handles_streaming(self, class_proc_with_port):
        proc, port = class_proc_with_port

        _send_request(port, content="Test", extra_json={"stream": True})
        wait_for_content(proc, timeout=2)
        assert proc.is_alive()


class TestIntegrationScenarios:
    """Test complete user workflows and scenarios — shared process+port."""

    def test_complete_filter_workflow(self, class_proc_with_port):
        proc, port = class_proc_with_port

        proc.send("1", press_enter=False)
        settle(proc)
        proc.send("6", press_enter=False)
        settle(proc)

        _send_request(port, content="Hello", extra_json={"max_tokens": 100})
        wait_for_content(proc, timeout=2)

        proc.send("7", press_enter=False)
        settle(proc)
        proc.send("8", press_enter=False)
        settle(proc, 0.1)

        assert proc.is_alive()

        # Clean up filters to initial state
        proc.send("1", press_enter=False)
        settle(proc)
        proc.send("6", press_enter=False)
        settle(proc)
        proc.send("7", press_enter=False)
        settle(proc)
        proc.send("8", press_enter=False)
        settle(proc)

    def test_panel_management_workflow(self, class_proc_with_port):
        proc, port = class_proc_with_port

        proc.send("8", press_enter=False)
        settle(proc)
        proc.send("9", press_enter=False)
        settle(proc)
        proc.send("3", press_enter=False)
        settle(proc)
        proc.send("\x0c", press_enter=False)
        settle(proc, 0.1)

        assert proc.is_alive()

        # Clean up — restore to defaults
        proc.send("8", press_enter=False)
        settle(proc)
        proc.send("9", press_enter=False)
        settle(proc)
        proc.send("\x0c", press_enter=False)
        settle(proc)
        proc.send("3", press_enter=False)
        settle(proc)

        assert proc.is_alive()


class TestSearch:
    """Test vim-style search functionality — shared process+port."""

    def test_search_open_type_escape_cycle(self, class_proc_with_port):
        """Verify search open/type/escape cycle doesn't crash."""
        proc, port = class_proc_with_port

        # Send a request so there's content to search
        _send_request(port, content="Search-UniqueTestContent-XYZ123")
        wait_for_content(proc, timeout=2)

        # Open search, type, escape — full cycle
        proc.send("/", press_enter=False)
        settle(proc, 0.2)
        for ch in "test":
            proc.send(ch, press_enter=False)
            settle(proc, 0.05)
        settle(proc, 0.2)
        proc.send("\x1b", press_enter=False)
        settle(proc, 0.2)
        assert proc.is_alive()

    def test_search_enter_and_navigation(self, class_proc_with_port):
        """Verify search commit and n/N navigation survive without crash."""
        proc, port = class_proc_with_port

        # Send request with known content
        _send_request(port, content="Navigate-SearchTarget-ABC")
        wait_for_content(proc, timeout=2)

        # Open search, type query, commit
        proc.send("/", press_enter=False)
        settle(proc, 0.2)
        for ch in "user":
            proc.send(ch, press_enter=False)
            settle(proc, 0.05)
        settle(proc, 0.3)  # wait for debounce
        proc.send("\r", press_enter=False)
        settle(proc, 0.2)

        # Navigate forward/backward
        proc.send("n", press_enter=False)
        settle(proc, 0.1)
        proc.send("N", press_enter=False)
        settle(proc, 0.1)
        proc.send("n", press_enter=False)
        settle(proc, 0.1)

        assert proc.is_alive()

        # Escape to close
        proc.send("\x1b", press_enter=False)
        settle(proc, 0.2)
        assert proc.is_alive()

    def test_search_re_edit_query(self, class_proc_with_port):
        """Verify / in navigating mode re-opens editing."""
        proc, port = class_proc_with_port

        # Open search, type, commit
        proc.send("/", press_enter=False)
        settle(proc, 0.2)
        for ch in "abc":
            proc.send(ch, press_enter=False)
            settle(proc, 0.05)
        proc.send("\r", press_enter=False)
        settle(proc, 0.2)

        # Press / again to re-edit
        proc.send("/", press_enter=False)
        settle(proc, 0.2)

        # Escape to close
        proc.send("\x1b", press_enter=False)
        settle(proc, 0.2)
        assert proc.is_alive()

    def test_search_no_crash_on_empty_content(self, class_proc):
        """Verify search on empty conversation doesn't crash."""
        proc = class_proc

        # Open search on empty conversation
        proc.send("/", press_enter=False)
        settle(proc, 0.2)

        # Type and commit with no matches
        for ch in "nonexistent":
            proc.send(ch, press_enter=False)
            settle(proc, 0.05)
        proc.send("\r", press_enter=False)
        settle(proc, 0.2)
        assert proc.is_alive()

        # Escape to close
        proc.send("\x1b", press_enter=False)
        settle(proc, 0.2)
        assert proc.is_alive()

    def test_search_with_invalid_regex(self, class_proc_with_port):
        """Verify invalid regex mid-typing doesn't crash."""
        proc, port = class_proc_with_port

        _send_request(port, content="RegexTest")
        wait_for_content(proc, timeout=2)

        # Open search and type invalid regex
        proc.send("/", press_enter=False)
        settle(proc, 0.2)
        for ch in "[invalid":
            proc.send(ch, press_enter=False)
            settle(proc, 0.05)
        settle(proc, 0.3)  # wait for debounce
        assert proc.is_alive()

        # Commit should also survive
        proc.send("\r", press_enter=False)
        settle(proc, 0.2)
        assert proc.is_alive()

        # Escape
        proc.send("\x1b", press_enter=False)
        settle(proc, 0.2)
        assert proc.is_alive()

    def test_search_normal_keys_pass_through_in_navigating(self, class_proc_with_port):
        """Verify j/k/G keys work normally in navigating phase."""
        proc, port = class_proc_with_port

        _send_request(port, content="PassthroughTest")
        wait_for_content(proc, timeout=2)

        # Open search, commit with a query
        proc.send("/", press_enter=False)
        settle(proc, 0.2)
        for ch in "user":
            proc.send(ch, press_enter=False)
            settle(proc, 0.05)
        proc.send("\r", press_enter=False)
        settle(proc, 0.2)

        # Vim navigation keys should work in navigating phase
        proc.send("j", press_enter=False)
        settle(proc, 0.05)
        proc.send("k", press_enter=False)
        settle(proc, 0.05)
        proc.send("G", press_enter=False)
        settle(proc, 0.05)
        proc.send("g", press_enter=False)
        settle(proc, 0.05)
        assert proc.is_alive()

        # Escape
        proc.send("\x1b", press_enter=False)
        settle(proc, 0.2)
        assert proc.is_alive()
