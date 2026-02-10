"""Pilot wrappers with settling for Textual in-process tests.

Thin wrappers that add await pilot.pause() after each interaction,
waiting for CPU idle instead of fixed sleeps.
"""

from textual.pilot import Pilot


async def press_and_settle(pilot: Pilot, *keys: str) -> None:
    """Press keys simultaneously and wait for app to settle."""
    await pilot.press(*keys)
    await pilot.pause()


async def press_sequence(pilot: Pilot, keys: list[str]) -> None:
    """Press keys one at a time, settling after each."""
    for key in keys:
        await pilot.press(key)
        await pilot.pause()


async def click_and_settle(
    pilot: Pilot, selector=None, offset: tuple[int, int] = (0, 0)
) -> None:
    """Click and wait for app to settle."""
    await pilot.click(selector=selector, offset=offset)
    await pilot.pause()


async def resize_and_settle(pilot: Pilot, width: int, height: int) -> None:
    """Resize terminal and wait for app to settle."""
    await pilot.resize_terminal(width, height)
    await pilot.pause()
