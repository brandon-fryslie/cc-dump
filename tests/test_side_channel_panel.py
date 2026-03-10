from cc_dump.tui.side_channel_panel import (
    WORKBENCH_CONTROL_GROUPS,
    SideChannelPanel,
    SideChannelPanelState,
    _utility_options,
    _render_control_label,
    _render_result_preview,
    _render_status_line,
    _resolve_action,
    render_qa_estimate_line,
    render_qa_scope_line,
)


def test_workbench_controls_are_grouped_by_intent():
    assert len(WORKBENCH_CONTROL_GROUPS) == 3
    titles = [group.title for group in WORKBENCH_CONTROL_GROUPS]
    assert "Ask" in titles
    assert "Draft" in titles
    assert "Utilities" in titles


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
        active_action="qa_submit",
    ) == "Status: Running Scoped Q&A"
    assert _render_status_line(enabled=True, loading=False, active_action="") == "Status: Ready"


def test_result_preview_is_bounded():
    text = "\n".join([f"line-{i}" for i in range(24)])
    preview = _render_result_preview(text)
    assert "line-0" in preview
    assert "line-15" in preview
    assert "line-16" not in preview
    assert "more lines" in preview


def test_ready_control_disabled_when_ai_disabled():
    estimate = WORKBENCH_CONTROL_GROUPS[0].controls[0]
    state = SideChannelPanelState(
        enabled=False,
        loading=False,
        active_action="",
        result_text="",
        result_source="",
        result_elapsed_ms=0,
    )
    action = _resolve_action(control=estimate, state=state, is_active=False)
    label = _render_control_label(
        control=estimate,
        state=state,
        is_active=False,
        actionable=action is not None,
    )
    assert action is None
    assert "[disabled]" in label


def test_qa_controls_disabled_when_ai_disabled():
    estimate_control = WORKBENCH_CONTROL_GROUPS[0].controls[0]
    submit_control = WORKBENCH_CONTROL_GROUPS[0].controls[1]
    state = SideChannelPanelState(
        enabled=False,
        loading=False,
        active_action="",
        result_text="",
        result_source="",
        result_elapsed_ms=0,
    )
    estimate_action = _resolve_action(control=estimate_control, state=state, is_active=False)
    submit_action = _resolve_action(control=submit_control, state=state, is_active=False)
    estimate_label = _render_control_label(
        control=estimate_control,
        state=state,
        is_active=False,
        actionable=estimate_action is not None,
    )
    submit_label = _render_control_label(
        control=submit_control,
        state=state,
        is_active=False,
        actionable=submit_action is not None,
    )
    assert estimate_action is None
    assert submit_action is None
    assert "[disabled]" in estimate_label
    assert "[disabled]" in submit_label


def test_render_qa_estimate_line_masks_tokens_for_ui_display():
    line = render_qa_estimate_line(
        scope_mode="selected_range",
        message_count=4,
        estimated_input_tokens=1234,
        estimated_output_tokens=320,
        estimated_total_tokens=1554,
    )
    assert line == "estimate: scope=selected_range messages=4 in=x out=x total=x"


def test_render_qa_scope_line_shows_selected_indices():
    assert render_qa_scope_line(scope_mode="selected_indices", selected_indices=(1, 3, 5)) == (
        "scope:selected_indices indices=[1, 3, 5]"
    )

def test_utility_launcher_options_are_bounded():
    options = _utility_options()
    values = [value for _label, value in options]
    assert values
    assert len(values) <= 5
    assert len(values) == len(set(values))


def test_side_channel_panel_update_display_is_safe_before_mount():
    panel = SideChannelPanel()
    panel.update_display(
        SideChannelPanelState(
            enabled=True,
            loading=False,
            active_action="qa_estimate",
            result_text="preview",
            result_source="preview",
            result_elapsed_ms=1,
        )
    )

    state = panel._display_state.get()
    assert state.active_action == "qa_estimate"
    assert state.result_source == "preview"
