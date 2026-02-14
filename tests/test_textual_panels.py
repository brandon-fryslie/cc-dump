"""Panel toggle tests using Textual in-process harness."""

import pytest

from tests.harness import (
    run_app,
    press_and_settle,
    is_panel_visible,
    is_follow_mode,
)

pytestmark = pytest.mark.textual


async def test_panel_cycling_dot():
    """Press '.' cycles active panel: stats → economics → timeline → stats."""
    async with run_app() as (pilot, app):
        assert is_panel_visible(app, "stats")
        assert not is_panel_visible(app, "economics")
        assert not is_panel_visible(app, "timeline")

        await press_and_settle(pilot, ".")
        assert not is_panel_visible(app, "stats")
        assert is_panel_visible(app, "economics")
        assert not is_panel_visible(app, "timeline")

        await press_and_settle(pilot, ".")
        assert not is_panel_visible(app, "stats")
        assert not is_panel_visible(app, "economics")
        assert is_panel_visible(app, "timeline")

        await press_and_settle(pilot, ".")
        assert is_panel_visible(app, "stats")
        assert not is_panel_visible(app, "economics")
        assert not is_panel_visible(app, "timeline")


async def test_follow_mode_toggle():
    """Press '0' toggles follow mode."""
    async with run_app() as (pilot, app):
        assert is_follow_mode(app)

        await press_and_settle(pilot, "0")
        assert not is_follow_mode(app)

        await press_and_settle(pilot, "0")
        assert is_follow_mode(app)


async def test_panels_initial_state():
    """Stats panel starts visible, economics/timeline hidden, logs hidden."""
    async with run_app() as (pilot, app):
        assert is_panel_visible(app, "stats")
        assert not is_panel_visible(app, "economics")
        assert not is_panel_visible(app, "timeline")
        assert not is_panel_visible(app, "logs")
