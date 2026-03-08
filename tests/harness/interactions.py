"""Pilot wrappers with settling for Textual in-process tests.

Thin wrappers that add await pilot.pause() after each interaction,
waiting for CPU idle instead of fixed sleeps.
"""

from textual.pilot import Pilot
from textual.widgets import Select


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


async def settle(pilot: Pilot, ticks: int = 1) -> None:
    """Pause one or more event-loop ticks."""
    for _ in range(max(0, ticks)):
        await pilot.pause()


async def choose_from_select(
    pilot: Pilot,
    selector: Select[str],
    *,
    navigation_keys: list[str],
    open_key: str = "enter",
    confirm_key: str = "enter",
) -> str:
    """Focus a Select, open it, navigate options, and confirm."""
    selector.focus()
    await pilot.pause()
    await press_and_settle(pilot, open_key)
    await press_sequence(pilot, navigation_keys)
    await press_and_settle(pilot, confirm_key)
    return str(selector.value)
