"""Textual in-process test harness for cc-dump.

Re-exports all public API for convenient imports:
    from tests.harness import run_app, press_and_settle, get_vis_level, ...
"""

from tests.harness.app_runner import run_app
from tests.harness.assertions import (
    get_all_levels,
    get_all_vis_states,
    get_category_expanded,
    get_filters,
    get_total_lines,
    get_turn_blocks,
    get_turn_count,
    get_vis_level,
    get_vis_state,
    is_follow_mode,
    is_panel_visible,
)
from tests.harness.builders import make_replay_data, make_replay_entry
from tests.harness.content import (
    all_turns_text,
    strips_to_text,
    turn_text,
    widget_text,
)
from tests.harness.interactions import (
    choose_from_select,
    click_and_settle,
    press_and_settle,
    press_sequence,
    resize_and_settle,
    settle,
)
from tests.harness.messages import MessageCapture

__all__ = [
    "MessageCapture",
    "all_turns_text",
    "choose_from_select",
    "click_and_settle",
    "get_all_levels",
    "get_all_vis_states",
    "get_category_expanded",
    "get_filters",
    "get_total_lines",
    "get_turn_blocks",
    "get_turn_count",
    "get_vis_level",
    "get_vis_state",
    "is_follow_mode",
    "is_panel_visible",
    "make_replay_data",
    "make_replay_entry",
    "press_and_settle",
    "press_sequence",
    "resize_and_settle",
    "run_app",
    "settle",
    "strips_to_text",
    "turn_text",
    "widget_text",
]
