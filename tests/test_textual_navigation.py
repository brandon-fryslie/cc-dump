"""Scroll and navigation tests using Textual in-process harness."""

from tests.harness import (
    run_app,
    press_and_settle,
    is_follow_mode,
    get_turn_count,
)
from cc_dump.formatting import (
    HeaderBlock,
    TextContentBlock,
    Category,
)


def _make_text_turn(text: str, n_lines: int = 50) -> list:
    """Create a turn with enough content to enable scrolling."""
    long_text = (text + "\n") * n_lines
    return [
        HeaderBlock(label="REQUEST #1", request_num=1, header_type="request"),
        TextContentBlock(text=long_text, category=Category.USER),
    ]


def _make_replay_data(n_turns: int = 3) -> list:
    """Create minimal replay data for populating turns.

    Each entry: (req_headers, req_body, resp_status, resp_headers, complete_message)
    """
    entries = []
    for i in range(n_turns):
        req_body = {
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": f"Message {i}"}],
        }
        complete_message = {
            "id": f"msg_{i}",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-5-20250929",
            "content": [{"type": "text", "text": f"Response {i}"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        entries.append(
            (
                {"content-type": "application/json"},  # req_headers
                req_body,
                200,  # resp_status
                {"content-type": "application/json"},  # resp_headers
                complete_message,
            )
        )
    return entries


async def test_go_top_disables_follow():
    """Press 'g' scrolls to top and disables follow mode."""
    async with run_app(replay_data=_make_replay_data()) as (pilot, app):
        assert is_follow_mode(app)
        assert get_turn_count(app) > 0

        await press_and_settle(pilot, "g")
        assert not is_follow_mode(app)


async def test_go_bottom_enables_follow():
    """Press 'G' scrolls to bottom and enables follow mode."""
    async with run_app(replay_data=_make_replay_data()) as (pilot, app):
        # First go to top (disable follow)
        await press_and_settle(pilot, "g")
        assert not is_follow_mode(app)

        # Then go to bottom
        await press_and_settle(pilot, "G")
        assert is_follow_mode(app)


async def test_follow_mode_default_on():
    """Follow mode starts enabled."""
    async with run_app() as (pilot, app):
        assert is_follow_mode(app)
