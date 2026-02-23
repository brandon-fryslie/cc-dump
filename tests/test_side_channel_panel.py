from cc_dump.tui.side_channel_panel import (
    WORKBENCH_CONTROL_GROUPS,
    SideChannelPanelState,
    _render_control_label,
    _render_purpose_usage,
    _render_result_preview,
    _render_status_line,
    _render_usage_summary,
    _resolve_action,
)


def test_render_purpose_usage_empty():
    assert _render_purpose_usage({}) == "Purpose usage: (none)"


def test_render_purpose_usage_masks_token_totals():
    usage = {
        "block_summary": {
            "turns": 2,
            "input_tokens": 10,
            "cache_read_tokens": 20,
            "cache_creation_tokens": 3,
            "output_tokens": 5,
        }
    }
    rendered = _render_purpose_usage(usage)
    assert "Purpose usage:" in rendered
    assert "block_summary" in rendered
    assert "runs=2" in rendered
    assert "in=x" in rendered
    assert "cache_read=x" in rendered
    assert "cache_create=x" in rendered
    assert "out=x" in rendered


def test_workbench_controls_are_grouped_by_intent():
    assert len(WORKBENCH_CONTROL_GROUPS) >= 4
    titles = [group.title for group in WORKBENCH_CONTROL_GROUPS]
    assert "Summarize" in titles
    assert "Ask" in titles
    assert "Extract" in titles
    assert "Draft" in titles


def test_workbench_controls_exclude_global_enable_toggle():
    labels = [
        control.label
        for group in WORKBENCH_CONTROL_GROUPS
        for control in group.controls
    ]
    assert "Toggle AI" not in labels
    assert "Enable AI" not in labels
    assert "Disable AI" not in labels


def test_status_line_reflects_disabled_loading_ready_states():
    assert _render_status_line(enabled=False, loading=False, active_action="") == (
        "Status: Disabled (enable AI in Settings)"
    )
    assert _render_status_line(
        enabled=True,
        loading=True,
        active_action="summarize_recent",
    ) == "Status: Running Summarize Recent"
    assert _render_status_line(enabled=True, loading=False, active_action="") == "Status: Ready"


def test_usage_summary_totals_runs():
    assert _render_usage_summary({}) == "Usage: no runs yet"
    assert _render_usage_summary(
        {
            "block_summary": {"turns": 2},
            "conversation_qa": {"turns": 1},
        }
    ) == "Usage: 3 runs across 2 purposes"


def test_result_preview_is_bounded():
    text = "\n".join([f"line-{i}" for i in range(24)])
    preview = _render_result_preview(text)
    assert "line-0" in preview
    assert "line-15" in preview
    assert "line-16" not in preview
    assert "more lines" in preview


def test_ready_control_disabled_when_ai_disabled():
    summarize = WORKBENCH_CONTROL_GROUPS[0].controls[0]
    state = SideChannelPanelState(
        enabled=False,
        loading=False,
        active_action="",
        result_text="",
        result_source="",
        result_elapsed_ms=0,
        purpose_usage={},
    )
    action = _resolve_action(control=summarize, state=state, is_active=False)
    label = _render_control_label(
        control=summarize,
        state=state,
        is_active=False,
        actionable=action is not None,
    )
    assert action is None
    assert "[disabled]" in label


def test_placeholder_control_remains_safe_and_clickable_when_idle():
    placeholder = WORKBENCH_CONTROL_GROUPS[1].controls[0]
    state = SideChannelPanelState(
        enabled=False,
        loading=False,
        active_action="",
        result_text="",
        result_source="",
        result_elapsed_ms=0,
        purpose_usage={},
    )
    action = _resolve_action(control=placeholder, state=state, is_active=False)
    label = _render_control_label(
        control=placeholder,
        state=state,
        is_active=False,
        actionable=action is not None,
    )
    assert action == placeholder.action
    assert placeholder.owner_ticket in label
