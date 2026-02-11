"""Scroll and navigation tests using Textual in-process harness."""

import pytest

from tests.harness import (
    run_app,
    press_and_settle,
    is_follow_mode,
    get_turn_count,
    make_replay_data,
)
from cc_dump.formatting import (
    HeaderBlock,
    TextContentBlock,
    Category,
)

pytestmark = pytest.mark.textual


def _make_text_turn(text: str, n_lines: int = 50) -> list:
    """Create a turn with enough content to enable scrolling."""
    long_text = (text + "\n") * n_lines
    return [
        HeaderBlock(label="REQUEST #1", request_num=1, header_type="request"),
        TextContentBlock(text=long_text, category=Category.USER),
    ]


async def test_go_top_disables_follow():
    """Press 'g' scrolls to top and disables follow mode."""
    async with run_app(replay_data=make_replay_data(3)) as (pilot, app):
        assert is_follow_mode(app)
        assert get_turn_count(app) > 0

        await press_and_settle(pilot, "g")
        assert not is_follow_mode(app)


async def test_go_bottom_enables_follow():
    """Press 'G' scrolls to bottom and enables follow mode."""
    async with run_app(replay_data=make_replay_data(3)) as (pilot, app):
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
