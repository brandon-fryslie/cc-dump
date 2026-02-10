"""Textual in-process test harness for cc-dump.

Re-exports all public API for convenient imports:
    from tests.harness import run_app, press_and_settle, get_vis_level, ...
"""

from tests.harness.app_runner import run_app
from tests.harness.interactions import (
    press_and_settle,
    press_sequence,
    click_and_settle,
    resize_and_settle,
)
from tests.harness.assertions import (
    get_vis_level,
    get_all_levels,
    get_category_expanded,
    get_filters,
    is_panel_visible,
    get_turn_count,
    get_turn_blocks,
    get_total_lines,
    is_follow_mode,
)
from tests.harness.content import (
    strips_to_text,
    turn_text,
    all_turns_text,
    widget_text,
)
from tests.harness.messages import MessageCapture

__all__ = [
    "run_app",
    "press_and_settle",
    "press_sequence",
    "click_and_settle",
    "resize_and_settle",
    "get_vis_level",
    "get_all_levels",
    "get_category_expanded",
    "get_filters",
    "is_panel_visible",
    "get_turn_count",
    "get_turn_blocks",
    "get_total_lines",
    "is_follow_mode",
    "strips_to_text",
    "turn_text",
    "all_turns_text",
    "widget_text",
    "MessageCapture",
]
