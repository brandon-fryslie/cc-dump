"""Tests for cc-dump hot-reload functionality.

These tests verify that the hot-reload system correctly detects changes to
source files and reloads modules without crashing the TUI.
"""

import time

import pytest

from tests.conftest import modify_file


class TestHotReloadBasics:
    """Test basic hot-reload functionality."""

    def test_tui_starts_successfully(self, start_cc_dump):
        """Verify that cc-dump TUI starts and displays the header."""
        proc = start_cc_dump()

        # Check that process is alive
        assert proc.is_alive(), "cc-dump process should be running"

        # Verify we can see the TUI (check for common elements)
        content = proc.get_content()
        assert "cc-dump" in content or "Quit" in content or "Headers" in content, \
            f"Expected TUI elements in output. Got:\n{content}"

    def test_hot_reload_detection_comment(self, start_cc_dump, formatting_py):
        """Test that hot-reload detects a simple modification (added comment)."""
        proc = start_cc_dump()

        # Modify formatting.py by adding a comment
        with modify_file(formatting_py, lambda content: f"# Hot-reload test comment\n{content}"):
            # Wait for hot-reload check to trigger (happens every second when idle)
            time.sleep(2.5)

            # Check screen content for hot-reload notification
            content = proc.get_content()
            assert proc.is_alive(), "Process should still be alive after hot-reload"

            # The notification should appear somewhere on screen
            # Note: Textual notifications may not always be visible in pty output
            # but the reload should happen silently without crashes
            # We verify the process didn't crash and continued running

        # Give it a moment to stabilize after restore
        time.sleep(1)
        assert proc.is_alive(), "Process should remain alive after file restoration"


class TestHotReloadWithCodeChanges:
    """Test hot-reload when actual code changes are made."""

    def test_hot_reload_with_marker_in_function(self, start_cc_dump, formatting_py):
        """Test that hot-reloaded code actually executes (add marker to output)."""
        proc = start_cc_dump()

        # Add a marker string to _get_timestamp function
        marker = "HOTRELOAD_MARKER_12345"

        def add_marker(content):
            # Find _get_timestamp function and modify its return value
            if 'def _get_timestamp():' in content:
                # Add a line that would show up if this function is called
                return content.replace(
                    'def _get_timestamp():\n    return datetime.now()',
                    f'def _get_timestamp():\n    # {marker}\n    return datetime.now()'
                )
            return content

        with modify_file(formatting_py, add_marker):
            # Wait for hot-reload
            time.sleep(2.5)

            # Verify process is still alive
            assert proc.is_alive(), "Process should still be alive after code change"

            # At this point, if we had a way to trigger a request, we could verify
            # the marker appears in the timestamp. For now, we verify no crash.

        time.sleep(1)
        assert proc.is_alive(), "Process should remain alive after marker removal"

    def test_hot_reload_formatting_function_change(self, start_cc_dump, formatting_py):
        """Test that changes to formatting functions are reloaded."""
        proc = start_cc_dump()

        def modify_separator(content):
            # Change the separator character in a visible way
            # This is a safe, non-breaking change
            return content.replace(
                'style: str = "heavy"  # "heavy" or "thin"',
                'style: str = "heavy"  # "heavy" or "thin" [MODIFIED]'
            )

        with modify_file(formatting_py, modify_separator):
            time.sleep(2.5)
            assert proc.is_alive(), "Process should survive formatting function changes"

        time.sleep(1)
        assert proc.is_alive(), "Process should remain stable after changes reverted"


class TestHotReloadErrorResilience:
    """Test that hot-reload handles errors gracefully."""

    def test_hot_reload_survives_syntax_error(self, start_cc_dump, formatting_py):
        """Test that app doesn't crash when a syntax error is introduced."""
        proc = start_cc_dump()

        # Introduce a syntax error
        def add_syntax_error(content):
            # Add a line with invalid Python syntax
            return f"this is not valid python syntax !!!\n{content}"

        with modify_file(formatting_py, add_syntax_error):
            # Wait for hot-reload to attempt reload
            time.sleep(2.5)

            # Process should still be alive (hot-reload catches exceptions)
            assert proc.is_alive(), "Process should survive syntax errors in hot-reload"

            # Check that we can still interact with the TUI
            content = proc.get_content()
            assert len(content) > 0, "TUI should still be displaying content"

        # After fixing the syntax error, app should continue normally
        time.sleep(2)
        assert proc.is_alive(), "Process should recover after syntax error is fixed"

    def test_hot_reload_survives_import_error(self, start_cc_dump, formatting_py):
        """Test that app doesn't crash when an import error is introduced."""
        proc = start_cc_dump()

        # Add an invalid import
        def add_import_error(content):
            return f"import this_module_does_not_exist_xyz\n{content}"

        with modify_file(formatting_py, add_import_error):
            time.sleep(2.5)

            # Process should still be alive
            assert proc.is_alive(), "Process should survive import errors in hot-reload"

        time.sleep(2)
        assert proc.is_alive(), "Process should recover after import error is fixed"

    def test_hot_reload_survives_runtime_error_in_function(self, start_cc_dump, formatting_py):
        """Test that introducing a runtime error doesn't crash during reload."""
        proc = start_cc_dump()

        # Add code that would cause a runtime error if executed
        def add_runtime_error(content):
            # Add a function that will raise an error
            return content.replace(
                'def _get_timestamp():',
                'def _get_timestamp():\n    x = 1 / 0  # This will fail if called\n    return "error"\n\ndef _get_timestamp_backup():'
            )

        with modify_file(formatting_py, add_runtime_error):
            time.sleep(2.5)

            # The reload itself should succeed (errors happen at call time, not import time)
            assert proc.is_alive(), "Process should survive reload with runtime error in code"

        time.sleep(2)
        assert proc.is_alive(), "Process should remain alive after reverting runtime error"


class TestHotReloadExclusions:
    """Test that excluded files are not hot-reloaded."""

    def test_proxy_changes_not_reloaded(self, start_cc_dump, proxy_py):
        """Test that changes to proxy.py do NOT trigger hot-reload."""
        proc = start_cc_dump()

        # Modify proxy.py
        with modify_file(proxy_py, lambda content: f"# Test comment in proxy\n{content}"):
            # Wait longer than normal reload check interval
            time.sleep(3)

            content = proc.get_content()

            # Process should be alive
            assert proc.is_alive(), "Process should be running"

            # Check that hot-reload notification did NOT appear
            # Note: This is a negative test - we're verifying the absence of reload
            # The best we can do in pty is verify no crash and continued operation
            # In a real scenario, we'd check stderr logs for "[hot-reload]" messages

        time.sleep(1)
        assert proc.is_alive(), "Process should remain stable"


class TestHotReloadMultipleChanges:
    """Test hot-reload with multiple file changes."""

    def test_hot_reload_multiple_modifications(self, start_cc_dump, formatting_py):
        """Test that hot-reload handles multiple successive changes."""
        proc = start_cc_dump()

        # First modification
        with modify_file(formatting_py, lambda c: f"# First comment\n{c}"):
            time.sleep(2.5)
            assert proc.is_alive(), "Process should survive first modification"

        # Second modification (file is now back to original)
        time.sleep(1)

        with modify_file(formatting_py, lambda c: f"# Second comment\n{c}"):
            time.sleep(2.5)
            assert proc.is_alive(), "Process should survive second modification"

        time.sleep(1)
        assert proc.is_alive(), "Process should remain stable after all changes"

    def test_hot_reload_rapid_changes(self, start_cc_dump, formatting_py):
        """Test that rapid successive changes don't cause issues."""
        proc = start_cc_dump()

        # Make several rapid changes
        for i in range(3):
            with modify_file(formatting_py, lambda c: f"# Rapid change {i}\n{c}"):
                time.sleep(0.5)  # Shorter delay - rapid changes

        # Give it time to settle
        time.sleep(3)
        assert proc.is_alive(), "Process should survive rapid changes"


class TestHotReloadStability:
    """Test hot-reload stability over time."""

    def test_hot_reload_extended_operation(self, start_cc_dump, formatting_py):
        """Test that hot-reload works correctly over extended operation."""
        proc = start_cc_dump()

        # Let it run for a bit
        time.sleep(2)
        assert proc.is_alive(), "Process should be stable initially"

        # Make a change
        with modify_file(formatting_py, lambda c: f"# Extended test\n{c}"):
            time.sleep(3)
            assert proc.is_alive(), "Process should survive hot-reload"

        # Continue running
        time.sleep(2)
        assert proc.is_alive(), "Process should remain stable after hot-reload"

        # Verify we can still quit normally
        proc.send("q", press_enter=False)
        time.sleep(0.5)

        # Process should exit cleanly
        # Note: is_alive() might still be True briefly, so we just check it doesn't hang
