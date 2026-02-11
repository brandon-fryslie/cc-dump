"""Panel toggle tests using Textual in-process harness."""

import pytest

from tests.harness import (
    run_app,
    press_and_settle,
    is_panel_visible,
    is_follow_mode,
)

pytestmark = pytest.mark.textual


async def test_economics_panel_toggle():
    """Press '8' toggles economics panel visibility."""
    async with run_app() as (pilot, app):
        assert not is_panel_visible(app, "economics")

        await press_and_settle(pilot, "8")
        assert is_panel_visible(app, "economics")

        await press_and_settle(pilot, "8")
        assert not is_panel_visible(app, "economics")


async def test_timeline_panel_toggle():
    """Press '9' toggles timeline panel visibility."""
    async with run_app() as (pilot, app):
        assert not is_panel_visible(app, "timeline")

        await press_and_settle(pilot, "9")
        assert is_panel_visible(app, "timeline")

        await press_and_settle(pilot, "9")
        assert not is_panel_visible(app, "timeline")


async def test_follow_mode_toggle():
    """Press '0' toggles follow mode."""
    async with run_app() as (pilot, app):
        assert is_follow_mode(app)

        await press_and_settle(pilot, "0")
        assert not is_follow_mode(app)

        await press_and_settle(pilot, "0")
        assert is_follow_mode(app)


async def test_panels_start_hidden():
    """All optional panels start hidden."""
    async with run_app() as (pilot, app):
        assert not is_panel_visible(app, "economics")
        assert not is_panel_visible(app, "timeline")
        assert not is_panel_visible(app, "logs")
