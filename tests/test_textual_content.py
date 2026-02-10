"""Rendered content and filter tests using Textual in-process harness."""

from cc_dump.formatting import Level
from tests.harness import (
    run_app,
    press_and_settle,
    get_turn_count,
    get_vis_level,
    all_turns_text,
)


def _make_replay_data() -> list:
    """Create replay data with identifiable content for filter testing.

    Each entry: (req_headers, req_body, resp_status, resp_headers, complete_message)
    """
    req_body = {
        "model": "claude-sonnet-4-5-20250929",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": "Hello world test message"}],
        "system": [{"type": "text", "text": "You are a helpful assistant."}],
    }
    complete_message = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-5-20250929",
        "content": [{"type": "text", "text": "Response from assistant"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }
    return [
        (
            {"content-type": "application/json"},
            req_body,
            200,
            {"content-type": "application/json"},
            complete_message,
        )
    ]


async def test_replay_populates_turns():
    """Loading replay data creates turns in the conversation view."""
    async with run_app(replay_data=_make_replay_data()) as (pilot, app):
        count = get_turn_count(app)
        # Each replay entry produces a request turn + response turn
        assert count == 2, f"Expected 2 turns, got {count}"


async def test_replay_content_visible():
    """Replay turns contain expected text content."""
    async with run_app(replay_data=_make_replay_data()) as (pilot, app):
        text = all_turns_text(app)
        # User message content should appear (user defaults to FULL)
        assert "Hello world test message" in text
        # Assistant response should appear (assistant defaults to FULL)
        assert "Response from assistant" in text


async def test_filter_hides_content():
    """Toggling a category to EXISTENCE hides its content."""
    async with run_app(replay_data=_make_replay_data()) as (pilot, app):
        # Verify user content initially visible
        text_before = all_turns_text(app)
        assert "Hello world test message" in text_before

        # Toggle user off (FULL -> EXISTENCE)
        await press_and_settle(pilot, "2")
        assert get_vis_level(app, "user") == Level.EXISTENCE

        text_after = all_turns_text(app)
        assert "Hello world test message" not in text_after


async def test_filter_restore_shows_content():
    """Toggling a category back restores its content."""
    async with run_app(replay_data=_make_replay_data()) as (pilot, app):
        # Toggle user off then back on
        await press_and_settle(pilot, "2")
        assert get_vis_level(app, "user") == Level.EXISTENCE

        await press_and_settle(pilot, "2")
        assert get_vis_level(app, "user") == Level.FULL

        text = all_turns_text(app)
        assert "Hello world test message" in text
