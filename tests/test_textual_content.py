"""Rendered content and filter tests using Textual in-process harness."""

import pytest

from cc_dump.formatting import VisState
from tests.harness import (
    run_app,
    press_and_settle,
    get_turn_count,
    get_vis_state,
    all_turns_text,
    make_replay_entry,
)

pytestmark = pytest.mark.textual

# Visibility state constants
HIDDEN = VisState(False, False, False)
FULL_EXPANDED = VisState(True, True, True)


# Shared replay data for content filtering tests
_REPLAY_DATA = [
    make_replay_entry(
        content="Hello world test message",
        response_text="Response from assistant",
        system_prompt="You are a helpful assistant.",
    )
]


async def test_replay_populates_turns():
    """Loading replay data creates turns in the conversation view."""
    async with run_app(replay_data=_REPLAY_DATA) as (pilot, app):
        count = get_turn_count(app)
        # Each replay entry produces a request turn + response turn
        assert count == 2, f"Expected 2 turns, got {count}"


async def test_replay_content_visible():
    """Replay turns contain expected text content."""
    async with run_app(replay_data=_REPLAY_DATA) as (pilot, app):
        text = all_turns_text(app)
        # User message content should appear (user defaults to FULL)
        assert "Hello world test message" in text
        # Assistant response should appear (assistant defaults to FULL)
        assert "Response from assistant" in text


async def test_filter_hides_content():
    """Toggling a category to hidden hides its content."""
    async with run_app(replay_data=_REPLAY_DATA) as (pilot, app):
        # Verify user content initially visible
        text_before = all_turns_text(app)
        assert "Hello world test message" in text_before

        # Toggle user off (visible -> hidden)
        await press_and_settle(pilot, "2")
        assert get_vis_state(app, "user").visible == False

        text_after = all_turns_text(app)
        assert "Hello world test message" not in text_after


async def test_filter_restore_shows_content():
    """Toggling a category back restores its content."""
    async with run_app(replay_data=_REPLAY_DATA) as (pilot, app):
        # Toggle user off then back on
        await press_and_settle(pilot, "2")
        assert get_vis_state(app, "user").visible == False

        await press_and_settle(pilot, "2")
        assert get_vis_state(app, "user") == FULL_EXPANDED

        text = all_turns_text(app)
        assert "Hello world test message" in text
