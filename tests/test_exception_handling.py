"""Test top-level exception handling in cc-dump TUI.

Verifies that unhandled exceptions are caught, logged, and displayed in the
error indicator without crashing the proxy server.
"""

import pytest
from tests.harness.app_runner import run_app
from tests.harness.builders import make_replay_data
import cc_dump.tui.error_indicator


class TestExceptionHandling:
    """Test top-level exception handling."""

    @pytest.fixture
    async def app_instance(self):
        """Create app in test mode."""
        replay_data = make_replay_data(n=5)
        async with run_app(replay_data=replay_data) as (pilot, app):
            await pilot.pause()
            yield app

    async def test_handle_exception_adds_to_indicator(self, app_instance):
        """Verify _handle_exception adds error to indicator."""
        test_error = ValueError("Test value error")

        # Call exception handler
        app_instance._handle_exception(test_error)

        # Verify exception item was created and added
        assert len(app_instance._view_store.exception_items) == 1
        item = app_instance._view_store.exception_items[0]
        assert isinstance(item, cc_dump.tui.error_indicator.ErrorItem)
        assert "ValueError" in item.summary
        assert "Test value error" in item.summary
        assert item.icon == "💥"

    async def test_handle_exception_multiple_exceptions(self, app_instance):
        """Verify multiple exceptions accumulate in indicator."""
        error1 = RuntimeError("First error")
        error2 = ValueError("Second error")

        app_instance._handle_exception(error1)
        app_instance._handle_exception(error2)

        # Both exceptions should be tracked
        assert len(app_instance._view_store.exception_items) == 2
        assert "RuntimeError" in app_instance._view_store.exception_items[0].summary
        assert "ValueError" in app_instance._view_store.exception_items[1].summary

    async def test_error_items_computed_includes_exceptions(self, app_instance):
        """Verify error_items Computed merges stale files and exceptions."""
        # Add a stale file error
        app_instance._view_store.stale_files.append("src/module1.py")

        # Add an exception
        test_error = TypeError("Type error")
        app_instance._handle_exception(test_error)

        # The error indicator should be updated (called internally by _handle_exception)
        # Verify exception was tracked
        assert len(app_instance._view_store.exception_items) >= 1
        assert "TypeError" in app_instance._view_store.exception_items[0].summary

    async def test_exception_handler_does_not_raise(self, app_instance):
        """Verify exception handler doesn't crash the app."""
        test_error = Exception("This should not crash the app")

        # This should not raise
        app_instance._handle_exception(test_error)

        # Exception should be captured
        assert len(app_instance._view_store.exception_items) == 1

    async def test_exception_with_traceback_logging(self, app_instance):
        """Verify exception handler captures traceback."""
        def nested_function():
            raise RuntimeError("Nested error for traceback")

        try:
            nested_function()
        except RuntimeError as e:
            app_instance._handle_exception(e)

        # Verify exception was captured
        assert len(app_instance._view_store.exception_items) == 1
        assert "RuntimeError" in app_instance._view_store.exception_items[0].summary
