from cc_dump.core.formatting import HIDDEN
from cc_dump.tui.custom_footer import StatusFooter
from cc_dump.tui.widget_factory import FollowState


def test_status_footer_update_display_is_safe_before_mount():
    footer = StatusFooter()
    footer.update_display(
        {
            "user": HIDDEN,
            "assistant": HIDDEN,
            "tools": HIDDEN,
            "system": HIDDEN,
            "metadata": HIDDEN,
            "thinking": HIDDEN,
            "follow_state": FollowState.ACTIVE,
            "active_filterset": None,
            "tmux_available": False,
            "tmux_auto_zoom": False,
            "tmux_zoomed": False,
            "active_launch_tool": "claude",
            "active_launch_config_name": "",
        }
    )

    state = footer._display_state.get()
    assert state["follow_state"] is FollowState.ACTIVE
    assert state["active_launch_tool"] == "claude"
