"""Visibility toggle tests using Textual in-process harness."""

from cc_dump.formatting import Level
from tests.harness import (
    run_app,
    press_and_settle,
    get_vis_level,
    get_all_levels,
)


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
    """Press '1' toggles headers: EXISTENCE -> remembered detail -> EXISTENCE."""
    async with run_app() as (pilot, app):
        assert get_vis_level(app, "headers") == Level.EXISTENCE

        # Toggle on: should go to remembered detail (default=SUMMARY)
        await press_and_settle(pilot, "1")
        assert get_vis_level(app, "headers") == Level.SUMMARY

        # Toggle off: back to EXISTENCE
        await press_and_settle(pilot, "1")
        assert get_vis_level(app, "headers") == Level.EXISTENCE


async def test_toggle_user_off_on():
    """Press '2' toggles user: FULL -> EXISTENCE -> remembered (FULL)."""
    async with run_app() as (pilot, app):
        assert get_vis_level(app, "user") == Level.FULL

        # Toggle off
        await press_and_settle(pilot, "2")
        assert get_vis_level(app, "user") == Level.EXISTENCE

        # Toggle on: restored to FULL
        await press_and_settle(pilot, "2")
        assert get_vis_level(app, "user") == Level.FULL


async def test_detail_toggle_shifts_summary_full():
    """Shift+1 (!) cycles detail between SUMMARY and FULL for headers."""
    async with run_app() as (pilot, app):
        # Headers start at EXISTENCE. Shift+1 should show at opposite of remembered.
        # Default remembered detail for headers is SUMMARY (2).
        # So pressing ! should show at FULL (opposite of SUMMARY).
        await press_and_settle(pilot, "!")
        level = get_vis_level(app, "headers")
        assert level == Level.FULL

        # Press ! again: should cycle to SUMMARY
        await press_and_settle(pilot, "!")
        assert get_vis_level(app, "headers") == Level.SUMMARY

        # Press ! again: should cycle to FULL
        await press_and_settle(pilot, "!")
        assert get_vis_level(app, "headers") == Level.FULL


async def test_toggle_remembers_detail_level():
    """Toggle off preserves detail level; toggle back restores it."""
    async with run_app() as (pilot, app):
        # Tools start at SUMMARY. Use detail toggle to set to FULL.
        await press_and_settle(pilot, "$")  # shift+4 = $ for tools detail
        assert get_vis_level(app, "tools") == Level.FULL

        # Toggle off with '4'
        await press_and_settle(pilot, "4")
        assert get_vis_level(app, "tools") == Level.EXISTENCE

        # Toggle back on — should remember FULL
        await press_and_settle(pilot, "4")
        assert get_vis_level(app, "tools") == Level.FULL


async def test_all_category_toggles():
    """Each number key toggles its category."""
    key_category = [
        ("1", "headers"),
        ("2", "user"),
        ("3", "assistant"),
        ("4", "tools"),
        ("5", "system"),
        ("6", "budget"),
        ("7", "metadata"),
    ]
    async with run_app() as (pilot, app):
        for key, cat in key_category:
            initial = get_vis_level(app, cat)
            await press_and_settle(pilot, key)
            toggled = get_vis_level(app, cat)
            # Should have changed
            assert toggled != initial, f"{cat}: {initial} should change after pressing {key}"
            # Toggle back
            await press_and_settle(pilot, key)
            restored = get_vis_level(app, cat)
            assert restored == initial, f"{cat}: should restore to {initial}, got {restored}"
