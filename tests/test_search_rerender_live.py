"""Live-app search rerender tests.

Drives the real CcDumpApp through the Textual Pilot, typing a search query one
key at a time — the exact "search on every keystroke" scenario. Guards the
unified viewport-bounded rerender path that serves both filter changes and search
highlighting (see ConversationView._rerender_affected_bounded): search context is
threaded through as a value, not forked into a parallel full-scan method.
"""

import pytest

from cc_dump.tui.search import SearchPhase
from tests.harness import (
    all_turns_text,
    get_turn_count,
    make_replay_data,
    press_and_settle,
    run_app,
)

pytestmark = pytest.mark.textual

# Several turns so search runs across a real multi-turn conversation. The word
# "keystroke" is a prefix of the typed query, so partial queries match too.
_REPLAY_DATA = make_replay_data(
    n=6,
    content="user asks about the keystroke handler",
    response_text="assistant explains the keystroke pipeline",
)


async def test_search_typed_key_by_key_keeps_conversation_rendered():
    """Typing a query one key at a time must not blank the view or raise."""
    async with run_app(replay_data=_REPLAY_DATA) as (pilot, app):
        assert get_turn_count(app) > 2, "replay should populate multiple turns"
        text_before = all_turns_text(app)
        assert "keystroke" in text_before

        # Open search, then type "keystroke" one key at a time — each keystroke
        # triggers a rerender through the viewport-bounded search path.
        await press_and_settle(pilot, "/")
        assert app._search_state.phase == SearchPhase.EDITING
        for ch in "keystroke":
            await press_and_settle(pilot, ch)

        # Query captured correctly and search is still in editing phase.
        assert app._search_state.query == "keystroke"
        assert app._search_state.phase == SearchPhase.EDITING

        # The conversation is still rendered — search is style-only, it must not
        # drop turns or clear content.
        text_after = all_turns_text(app)
        assert get_turn_count(app) > 2
        assert "keystroke" in text_after


async def test_search_backspace_edits_query_without_error():
    """Deleting characters re-renders through the same path without error."""
    async with run_app(replay_data=_REPLAY_DATA) as (pilot, app):
        await press_and_settle(pilot, "/")
        for ch in "keystroke":
            await press_and_settle(pilot, ch)
        assert app._search_state.query == "keystroke"

        # Backspace to a shorter still-matching query; each delete re-renders.
        for _ in range(4):
            await press_and_settle(pilot, "backspace")

        assert app._search_state.query == "keyst"
        assert "keystroke" in all_turns_text(app)
