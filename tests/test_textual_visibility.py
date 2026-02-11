"""Visibility toggle tests using Textual in-process harness."""

import pytest

from cc_dump.formatting import Level
from tests.harness import (
    run_app,
    press_and_settle,
    get_vis_level,
    get_all_levels,
)

pytestmark = pytest.mark.textual


async def test_default_visibility_levels():
    """All 7 categories start at expected default levels."""
    async with run_app() as (pilot, app):
        levels = get_all_levels(app)
        assert levels["headers"] == Level.EXISTENCE
        assert levels["user"] == Level.FULL
        assert levels["assistant"] == Level.FULL
        assert levels["tools"] == Level.SUMMARY
        assert levels["system"] == Level.SUMMARY
        assert levels["budget"] == Level.EXISTENCE
        assert levels["metadata"] == Level.EXISTENCE


async def test_toggle_headers_off_on():
    """Press '1' toggles headers visibility: hidden -> visible -> hidden."""
    async with run_app() as (pilot, app):
        # Headers start hidden (visible=False, full=False -> EXISTENCE)
        assert get_vis_level(app, "headers") == Level.EXISTENCE

        # Toggle visible: should show at SUMMARY (visible=True, full=False)
        await press_and_settle(pilot, "1")
        assert get_vis_level(app, "headers") == Level.SUMMARY

        # Toggle hidden: back to EXISTENCE (visible=False, full=False)
        await press_and_settle(pilot, "1")
        assert get_vis_level(app, "headers") == Level.EXISTENCE


async def test_toggle_user_off_on():
    """Press '2' toggles user visibility: visible -> hidden -> visible."""
    async with run_app() as (pilot, app):
        # User starts visible at FULL (visible=True, full=True)
        assert get_vis_level(app, "user") == Level.FULL

        # Toggle hidden (visible=False, full=True -> EXISTENCE)
        await press_and_settle(pilot, "2")
        assert get_vis_level(app, "user") == Level.EXISTENCE

        # Toggle visible: restored to FULL (visible=True, full=True)
        await press_and_settle(pilot, "2")
        assert get_vis_level(app, "user") == Level.FULL


async def test_detail_toggle_shifts_summary_full():
    """Shift+1 (!) toggles detail between SUMMARY and FULL. Need to show headers first."""
    async with run_app() as (pilot, app):
        # Headers start hidden. Show them first with '1'
        await press_and_settle(pilot, "1")
        assert get_vis_level(app, "headers") == Level.SUMMARY  # visible=True, full=False

        # Press !: toggle to FULL (visible=True, full=True)
        await press_and_settle(pilot, "!")
        assert get_vis_level(app, "headers") == Level.FULL

        # Press ! again: toggle to SUMMARY (visible=True, full=False)
        await press_and_settle(pilot, "!")
        assert get_vis_level(app, "headers") == Level.SUMMARY

        # Press ! again: toggle to FULL (visible=True, full=True)
        await press_and_settle(pilot, "!")
        assert get_vis_level(app, "headers") == Level.FULL


async def test_toggle_remembers_detail_level():
    """Visibility toggle preserves detail level independently."""
    async with run_app() as (pilot, app):
        # Tools start at SUMMARY (visible=True, full=False)
        assert get_vis_level(app, "tools") == Level.SUMMARY

        # Toggle detail to FULL with '$' (shift+4)
        await press_and_settle(pilot, "$")
        assert get_vis_level(app, "tools") == Level.FULL  # visible=True, full=True

        # Hide with '4' (visible=False, full=True)
        await press_and_settle(pilot, "4")
        assert get_vis_level(app, "tools") == Level.EXISTENCE

        # Show again with '4' — detail state preserved (visible=True, full=True)
        await press_and_settle(pilot, "4")
        assert get_vis_level(app, "tools") == Level.FULL


@pytest.mark.parametrize(
    "key,category",
    [
        ("1", "headers"),
        ("2", "user"),
        ("3", "assistant"),
        ("4", "tools"),
        ("5", "system"),
        ("6", "budget"),
        ("7", "metadata"),
    ],
)
async def test_category_toggle(key, category):
    """Each number key toggles its category and restores on second press."""
    async with run_app() as (pilot, app):
        initial = get_vis_level(app, category)
        await press_and_settle(pilot, key)
        toggled = get_vis_level(app, category)
        # Should have changed
        assert toggled != initial, f"{category}: {initial} should change after pressing {key}"
        # Toggle back
        await press_and_settle(pilot, key)
        restored = get_vis_level(app, category)
        assert restored == initial, f"{category}: should restore to {initial}, got {restored}"
