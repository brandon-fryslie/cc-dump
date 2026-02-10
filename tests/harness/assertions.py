"""State query helpers for Textual in-process tests.

Pure functions that return values — tests compose with assert.
No internal assertions.
"""

from cc_dump.formatting import Level
from cc_dump.tui.app import CcDumpApp


def get_vis_level(app: CcDumpApp, category: str) -> Level:
    """Read the reactive vis_{category} value as a Level."""
    return Level(getattr(app, f"vis_{category}"))


def get_all_levels(app: CcDumpApp) -> dict[str, Level]:
    """Read all 7 category visibility levels."""
    categories = ["headers", "user", "assistant", "tools", "system", "budget", "metadata"]
    return {cat: get_vis_level(app, cat) for cat in categories}


def get_category_expanded(app: CcDumpApp, category: str) -> bool:
    """Read the _category_expanded state for a category."""
    return app._category_expanded[category]


def get_filters(app: CcDumpApp) -> dict:
    """Get the active filter state (category -> (Level, expanded))."""
    return app.active_filters


def is_panel_visible(app: CcDumpApp, panel: str) -> bool:
    """Check if a panel reactive is True (economics, timeline, logs)."""
    return getattr(app, f"show_{panel}")


def get_turn_count(app: CcDumpApp) -> int:
    """Get number of turns in the conversation view."""
    conv = app._get_conv()
    return len(conv._turns) if conv is not None else 0


def get_turn_blocks(app: CcDumpApp, turn_index: int) -> list:
    """Get the block list for a specific turn."""
    conv = app._get_conv()
    if conv is not None and turn_index < len(conv._turns):
        return conv._turns[turn_index].blocks
    return []


def get_total_lines(app: CcDumpApp) -> int:
    """Get the total virtual line count."""
    conv = app._get_conv()
    return conv._total_lines if conv is not None else 0


def is_follow_mode(app: CcDumpApp) -> bool:
    """Check if follow mode is active."""
    conv = app._get_conv()
    return conv._follow_mode if conv is not None else True
