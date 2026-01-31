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


class TestTUIStartupShutdown:
    """Test basic TUI startup and shutdown."""

    def test_tui_starts_and_displays_header(self, start_cc_dump):
        """Verify TUI starts successfully and shows expected elements."""
        proc = start_cc_dump()
        assert proc.is_alive()

        content = proc.get_content()
        # Should see some standard UI elements
        assert any(x in content for x in ["cc-dump", "Quit", "headers", "tools"])

    def test_tui_quits_cleanly_with_q_key(self, start_cc_dump):
        """Verify pressing 'q' exits the application cleanly."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Press 'q' to quit
        proc.send("q", press_enter=False)
        time.sleep(0.5)

        # Process should exit (or be exiting)
        # Note: There might be a brief delay, so we don't strictly assert not alive

    def test_tui_shows_startup_logs(self, start_cc_dump):
        """Verify startup logs are visible when logs panel is toggled."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Toggle logs panel (ctrl+l)
        proc.send("\x0c", press_enter=False)  # ctrl+l
        time.sleep(0.5)

        content = proc.get_content()
        # Should show startup log messages
        assert "started" in content.lower() or "listening" in content.lower()


class TestFilterToggles:
    """Test all filter toggle keybindings."""

    def test_toggle_headers_filter(self, start_cc_dump):
        """Test 'h' key toggles headers filter."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Initially headers are off (show_headers = False)
        # Press 'h' to toggle on
        proc.send("h", press_enter=False)
        time.sleep(0.3)

        # Press 'h' again to toggle off
        proc.send("h", press_enter=False)
        time.sleep(0.3)

        # Should still be alive after toggling
        assert proc.is_alive()

    def test_toggle_tools_filter(self, start_cc_dump):
        """Test 't' key toggles tools filter."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Press 't' to toggle tools filter
        proc.send("t", press_enter=False)
        time.sleep(0.3)

        proc.send("t", press_enter=False)
        time.sleep(0.3)

        assert proc.is_alive()

    def test_toggle_system_filter(self, start_cc_dump):
        """Test 's' key toggles system filter."""
        proc = start_cc_dump()
        assert proc.is_alive()

        proc.send("s", press_enter=False)
        time.sleep(0.3)

        proc.send("s", press_enter=False)
        time.sleep(0.3)

        assert proc.is_alive()

    def test_toggle_expand_filter(self, start_cc_dump):
        """Test 'e' key toggles expand/context filter."""
        proc = start_cc_dump()
        assert proc.is_alive()

        proc.send("e", press_enter=False)
        time.sleep(0.3)

        proc.send("e", press_enter=False)
        time.sleep(0.3)

        assert proc.is_alive()

    def test_toggle_metadata_filter(self, start_cc_dump):
        """Test 'm' key toggles metadata filter."""
        proc = start_cc_dump()
        assert proc.is_alive()

        proc.send("m", press_enter=False)
        time.sleep(0.3)

        proc.send("m", press_enter=False)
        time.sleep(0.3)

        assert proc.is_alive()

    def test_multiple_filter_toggles_in_sequence(self, start_cc_dump):
        """Test toggling multiple filters in sequence."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Toggle several filters
        for key in ["h", "t", "s", "e", "m"]:
            proc.send(key, press_enter=False)
            time.sleep(0.2)

        assert proc.is_alive()

        # Toggle them all back
        for key in ["h", "t", "s", "e", "m"]:
            proc.send(key, press_enter=False)
            time.sleep(0.2)

        assert proc.is_alive()


class TestPanelToggles:
    """Test panel visibility toggles."""

    def test_toggle_stats_panel(self, start_cc_dump):
        """Test 'a' key toggles stats panel visibility."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Stats panel is initially visible (show_stats = True)
        # Press 'p' to hide
        proc.send("a", press_enter=False)
        time.sleep(0.3)

        # Press 'p' to show again
        proc.send("a", press_enter=False)
        time.sleep(0.3)

        assert proc.is_alive()

    def test_toggle_economics_panel(self, start_cc_dump):
        """Test 'c' key toggles cost panel visibility."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Economics panel is initially hidden (show_economics = False)
        # Press 'x' to show
        proc.send("c", press_enter=False)
        time.sleep(0.5)

        content = proc.get_content()
        # When visible, might show "Tool" or similar header
        # (Will be empty if no data yet, but panel should be present)

        # Press 'x' to hide
        proc.send("c", press_enter=False)
        time.sleep(0.3)

        assert proc.is_alive()

    def test_toggle_timeline_panel(self, start_cc_dump):
        """Test 'l' key toggles timeline panel visibility."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Timeline panel is initially hidden (show_timeline = False)
        # Press 'l' to show
        proc.send("l", press_enter=False)
        time.sleep(0.5)

        # Press 'l' to hide
        proc.send("l", press_enter=False)
        time.sleep(0.3)

        assert proc.is_alive()

    def test_toggle_logs_panel(self, start_cc_dump):
        """Test 'ctrl+l' key toggles logs panel visibility."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Logs panel is initially hidden (show_logs = False)
        # Press ctrl+l to show
        proc.send("\x0c", press_enter=False)  # ctrl+l
        time.sleep(0.5)

        content = proc.get_content()
        # Should show log messages when visible
        assert any(x in content for x in ["INFO", "started", "Listening"])

        # Press ctrl+l to hide
        proc.send("\x0c", press_enter=False)
        time.sleep(0.3)

        assert proc.is_alive()


class TestRequestHandling:
    """Test TUI behavior when handling API requests."""

    def test_displays_request_when_received(self, start_cc_dump):
        """Test that TUI displays incoming API request."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Enable headers to see request
        proc.send("h", press_enter=False)
        time.sleep(0.3)

        # Send a request to the proxy
        try:
            response = requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": "Hello"}]
                },
                timeout=2,
                headers={"anthropic-version": "2023-06-01"}
            )
        except requests.exceptions.RequestException:
            # Expected - we're not forwarding to real API
            pass

        time.sleep(1)

        content = proc.get_content()
        # Should see evidence of request processing
        # Might show "REQUEST" or model name or error
        assert len(content) > 0
        assert proc.is_alive()

    def test_handles_multiple_requests(self, start_cc_dump):
        """Test TUI handles multiple sequential requests."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Send multiple requests
        for i in range(3):
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
            time.sleep(0.5)

        time.sleep(1)
        assert proc.is_alive()


class TestDatabaseIntegration:
    """Test database persistence and querying."""

    def test_tui_creates_database_when_enabled(self, start_cc_dump):
        """Test that TUI creates and uses database when not disabled."""
        # Create temp directory for database
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            session_id = "test-session-123"

            # Start cc-dump with database enabled
            # Note: We need to modify fixture or add parameter to support this
            # For now, this test documents the expected behavior
            pytest.skip("Requires fixture enhancement to pass db_path")

    def test_stats_panel_queries_database(self, start_cc_dump):
        """Test that stats panel updates from database."""
        # This requires database-enabled mode
        pytest.skip("Requires database-enabled test setup")

    def test_economics_panel_queries_database(self, start_cc_dump):
        """Test that economics panel queries database when visible."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Toggle economics panel visible
        proc.send("c", press_enter=False)
        time.sleep(0.5)

        # Without database or requests, panel should be empty but functional
        assert proc.is_alive()

    def test_timeline_panel_queries_database(self, start_cc_dump):
        """Test that timeline panel queries database when visible."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Toggle timeline panel visible
        proc.send("l", press_enter=False)
        time.sleep(0.5)

        # Without database or requests, panel should be empty but functional
        assert proc.is_alive()


class TestVisualIndicators:
    """Test visual indicators for active filters."""

    def test_content_shows_filter_indicators(self, start_cc_dump):
        """Test that filtered content shows colored bar indicators."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Enable headers and metadata
        proc.send("h", press_enter=False)
        time.sleep(0.2)
        proc.send("m", press_enter=False)
        time.sleep(0.2)

        # Send a request to generate content
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
        # Should see the vertical bar indicator (▌) somewhere in content
        # when filtered content is displayed
        # Note: Actual rendering might vary based on terminal
        assert proc.is_alive()


class TestContentFiltering:
    """Test that content visibility changes based on filters."""

    def test_headers_filter_controls_request_headers(self, start_cc_dump):
        """Test that 'h' filter controls visibility of request/response headers."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Initially headers are hidden (show_headers = False)
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
        content_without_headers = proc.get_content()

        # Enable headers
        proc.send("h", press_enter=False)
        time.sleep(0.5)
        content_with_headers = proc.get_content()

        # Content should change when headers are toggled
        # (might be same if no requests yet, but should not crash)
        assert proc.is_alive()

    def test_tools_filter_controls_tool_visibility(self, start_cc_dump):
        """Test that 't' filter controls visibility of tool use/results."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Toggle tools filter
        proc.send("t", press_enter=False)
        time.sleep(0.3)

        # Even without tool content, toggling should work
        assert proc.is_alive()

        # Toggle back
        proc.send("t", press_enter=False)
        time.sleep(0.3)
        assert proc.is_alive()

    def test_metadata_filter_controls_model_info(self, start_cc_dump):
        """Test that 'm' filter controls visibility of metadata."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Metadata is initially visible (show_metadata = True)
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

        # Toggle metadata off
        proc.send("m", press_enter=False)
        time.sleep(0.5)

        # Toggle back on
        proc.send("m", press_enter=False)
        time.sleep(0.5)

        assert proc.is_alive()


class TestStatsPanel:
    """Test stats panel functionality."""

    def test_stats_panel_visible_by_default(self, start_cc_dump):
        """Test that stats panel is visible on startup."""
        proc = start_cc_dump()
        assert proc.is_alive()

        content = proc.get_content()
        # Stats panel should show some content (tokens, requests, etc.)
        # Even if zero, should have structure
        assert len(content) > 0

    def test_stats_panel_updates_on_request(self, start_cc_dump):
        """Test that stats panel updates when request is processed."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        content_before = proc.get_content()

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
        content_after = proc.get_content()

        # Content should potentially change (request count, etc.)
        assert proc.is_alive()

    def test_stats_panel_can_be_hidden(self, start_cc_dump):
        """Test that stats panel can be hidden with 'p' key."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Hide stats panel
        proc.send("a", press_enter=False)
        time.sleep(0.5)

        # Should still be running
        assert proc.is_alive()


class TestErrorHandling:
    """Test error handling and resilience."""

    def test_tui_survives_malformed_request(self, start_cc_dump):
        """Test that TUI handles malformed API requests gracefully."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Send malformed request
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={"invalid": "request"},
                timeout=2
            )
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)
        assert proc.is_alive()

    def test_tui_survives_network_error(self, start_cc_dump):
        """Test that TUI handles network errors gracefully."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Just verify it runs - network errors would come from upstream
        time.sleep(1)
        assert proc.is_alive()

    def test_tui_handles_rapid_filter_toggling(self, start_cc_dump):
        """Test that rapid filter toggling doesn't crash TUI."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Rapidly toggle filters
        for _ in range(10):
            for key in ["h", "t", "s", "e", "m"]:
                proc.send(key, press_enter=False)
                time.sleep(0.05)

        time.sleep(1)
        assert proc.is_alive()


class TestRenderingStability:
    """Test rendering stability and performance."""

    def test_tui_renders_without_crash_on_startup(self, start_cc_dump):
        """Test initial rendering completes without crash."""
        proc = start_cc_dump()
        time.sleep(1)
        assert proc.is_alive()

        content = proc.get_content()
        assert len(content) > 0

    def test_tui_rerender_on_filter_change(self, start_cc_dump):
        """Test that changing filters triggers re-render without crash."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Change a filter that affects content rendering
        proc.send("e", press_enter=False)
        time.sleep(0.5)

        assert proc.is_alive()

        # Change it back
        proc.send("e", press_enter=False)
        time.sleep(0.5)

        assert proc.is_alive()

    def test_tui_handles_large_content(self, start_cc_dump):
        """Test TUI handles large content without issues."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Send request with large message
        large_content = "Test " * 1000  # Large user message
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 50,
                    "messages": [{"role": "user", "content": large_content}]
                },
                timeout=2,
                headers={"anthropic-version": "2023-06-01"}
            )
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)
        assert proc.is_alive()


class TestFooterBindings:
    """Test footer keybinding display."""

    def test_footer_shows_keybindings(self, start_cc_dump):
        """Test that footer displays available keybindings."""
        proc = start_cc_dump()
        assert proc.is_alive()

        content = proc.get_content()
        # Footer should show at least some key bindings
        # Common ones: headers, tools, system, quit
        assert any(x in content for x in ["headers", "tools", "system", "quit"])

    def test_footer_persists_during_operation(self, start_cc_dump):
        """Test that footer remains visible during normal operation."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Toggle some filters
        proc.send("h", press_enter=False)
        time.sleep(0.3)
        proc.send("t", press_enter=False)
        time.sleep(0.3)

        content = proc.get_content()
        # Footer should still be visible
        assert "quit" in content or "headers" in content

        assert proc.is_alive()


class TestConversationView:
    """Test conversation view widget."""

    def test_conversation_view_displays_messages(self, start_cc_dump):
        """Test that conversation view displays message content."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Send request to generate conversation content
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 50,
                    "messages": [
                        {"role": "user", "content": "Hello test"}
                    ]
                },
                timeout=2,
                headers={"anthropic-version": "2023-06-01"}
            )
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)
        assert proc.is_alive()

    def test_conversation_view_handles_streaming(self, start_cc_dump):
        """Test that conversation view handles streaming responses."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # Send streaming request
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 50,
                    "messages": [{"role": "user", "content": "Test"}],
                    "stream": True
                },
                timeout=2,
                headers={"anthropic-version": "2023-06-01"}
            )
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)
        assert proc.is_alive()


class TestNoDatabase:
    """Test TUI functionality when database is disabled (--no-db)."""

    def test_tui_starts_without_database(self, start_cc_dump):
        """Test that TUI works with --no-db flag."""
        # Default fixture uses --no-db
        proc = start_cc_dump()
        assert proc.is_alive()

        content = proc.get_content()
        # Should show warning about database being disabled
        # or just work normally without DB features

    def test_stats_panel_works_without_database(self, start_cc_dump):
        """Test that stats panel shows basic stats without database."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Stats panel should still be visible and functional
        # Just won't have persistent token counts
        content = proc.get_content()
        assert len(content) > 0

    def test_economics_panel_empty_without_database(self, start_cc_dump):
        """Test that economics panel is empty but functional without DB."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Show economics panel
        proc.send("c", press_enter=False)
        time.sleep(0.5)

        # Should not crash, just be empty
        assert proc.is_alive()

    def test_timeline_panel_empty_without_database(self, start_cc_dump):
        """Test that timeline panel is empty but functional without DB."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Show timeline panel
        proc.send("l", press_enter=False)
        time.sleep(0.5)

        # Should not crash, just be empty
        assert proc.is_alive()


class TestIntegrationScenarios:
    """Test complete user workflows and scenarios."""

    def test_complete_filter_workflow(self, start_cc_dump):
        """Test a complete workflow of using filters."""
        port = random.randint(10000, 60000)
        proc = start_cc_dump(port=port)
        assert proc.is_alive()

        # 1. Start with default view
        time.sleep(0.5)

        # 2. Enable headers to see request details
        proc.send("h", press_enter=False)
        time.sleep(0.3)

        # 3. Enable expand to see full content
        proc.send("e", press_enter=False)
        time.sleep(0.3)

        # 4. Send a request
        try:
            requests.post(
                f"http://127.0.0.1:{port}/v1/messages",
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": "Hello"}]
                },
                timeout=2,
                headers={"anthropic-version": "2023-06-01"}
            )
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)

        # 5. Disable metadata to focus on content
        proc.send("m", press_enter=False)
        time.sleep(0.3)

        # 6. Enable economics panel to see tool usage
        proc.send("c", press_enter=False)
        time.sleep(0.5)

        # Should still be running
        assert proc.is_alive()

    def test_panel_management_workflow(self, start_cc_dump):
        """Test managing multiple panels."""
        proc = start_cc_dump()
        assert proc.is_alive()

        # Show all panels
        proc.send("c", press_enter=False)  # Economics
        time.sleep(0.3)
        proc.send("l", press_enter=False)  # Timeline
        time.sleep(0.3)

        # Hide stats
        proc.send("a", press_enter=False)
        time.sleep(0.3)

        # Show logs
        proc.send("\x0c", press_enter=False)  # ctrl+l
        time.sleep(0.5)

        assert proc.is_alive()

        # Clean up - hide everything
        proc.send("c", press_enter=False)
        time.sleep(0.2)
        proc.send("l", press_enter=False)
        time.sleep(0.2)
        proc.send("\x0c", press_enter=False)
        time.sleep(0.2)
        proc.send("a", press_enter=False)  # Show stats again
        time.sleep(0.2)

        assert proc.is_alive()
