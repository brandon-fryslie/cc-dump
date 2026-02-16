"""State query helpers for Textual in-process tests.

Pure functions that return values — tests compose with assert.
No internal assertions.
"""

from cc_dump.formatting import VisState
from cc_dump.tui.app import CcDumpApp


def get_vis_state(app: CcDumpApp, category: str) -> VisState:
    """Read the visibility state from the three reactive dicts."""
    return VisState(
        visible=app._is_visible[category],
        full=app._is_full[category],
        expanded=app._is_expanded[category],
    )


def get_all_vis_states(app: CcDumpApp, categories=None) -> dict[str, VisState]:
    """Read all category visibility states."""
    categories = categories or ["user", "assistant", "tools", "system", "budget", "metadata", "headers"]
    return {cat: get_vis_state(app, cat) for cat in categories}


# Backward compatibility aliases (deprecated)
def get_vis_level(app: CcDumpApp, category: str):
    """DEPRECATED: Use get_vis_state instead."""
    return get_vis_state(app, category)


def get_all_levels(app: CcDumpApp):
    """DEPRECATED: Use get_all_vis_states instead."""
    return get_all_vis_states(app)


def get_category_expanded(app: CcDumpApp, category: str) -> bool:
    """Read the _is_expanded state for a category."""
    return app._is_expanded[category]


def get_filters(app: CcDumpApp) -> dict:
    """Get the active filter state (category -> (Level, expanded))."""
    return app.active_filters


def is_panel_visible(app: CcDumpApp, panel: str) -> bool:
    """Check if a panel is visible.

    For cycling panels (stats, economics, timeline): checks actual widget.display.
    For toggle panels (logs, info): checks show_<panel> reactive.
    """
    from cc_dump.tui.panel_registry import PANEL_ORDER
    if panel in PANEL_ORDER:
        widget = app._get_panel(panel)
        return widget is not None and widget.display
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
