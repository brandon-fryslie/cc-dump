"""Tests for tmux_controller — zoom decisions, state machine, event handling.

All tests mock libtmux and tmux env vars; no actual tmux required.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from cc_dump.event_types import (
    ErrorEvent,
    MessageDeltaEvent,
    PipelineEventKind,
    ProxyErrorEvent,
    RequestBodyEvent,
    ResponseDoneEvent,
    ResponseSSEEvent,
    StopReason,
    TextDeltaEvent,
)
from cc_dump.tmux_controller import (
    LaunchAction,
    LaunchResult,
    TmuxController,
    TmuxState,
    _ZOOM_DECISIONS,
    _extract_decision_key,
    is_available,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


_VALID_ATTRS = frozenset({
    "state", "auto_zoom", "_is_zoomed", "_port",
    "_claude_command",
    "_server", "_session", "_our_pane", "_claude_pane",
})


@pytest.fixture
def make_controller():
    """Factory fixture: creates TmuxController with TMUX unset, then applies overrides."""

    def _factory(**overrides) -> TmuxController:
        bad = set(overrides) - _VALID_ATTRS
        if bad:
            raise ValueError(f"Invalid TmuxController overrides: {bad}")
        with patch.dict(os.environ, {}, clear=True):
            ctrl = TmuxController()
        for k, v in overrides.items():
            setattr(ctrl, k, v)
        return ctrl

    return _factory


@pytest.fixture
def active_controller(make_controller):
    """Controller in CLAUDE_RUNNING state with mocked panes and auto_zoom on."""
    return make_controller(
        state=TmuxState.CLAUDE_RUNNING,
        auto_zoom=True,
        _our_pane=MagicMock(),
        _claude_pane=MagicMock(),
    )


# ─── _ZOOM_DECISIONS table ───────────────────────────────────────────────────


class TestZoomDecisions:
    """Verify the zoom decision table entries."""

    def test_request_zooms(self):
        assert _ZOOM_DECISIONS[(PipelineEventKind.REQUEST, None)] is True

    def test_end_turn_unzooms(self):
        assert _ZOOM_DECISIONS[(PipelineEventKind.RESPONSE_EVENT, StopReason.END_TURN)] is False

    def test_max_tokens_unzooms(self):
        assert _ZOOM_DECISIONS[(PipelineEventKind.RESPONSE_EVENT, StopReason.MAX_TOKENS)] is False

    def test_tool_use_is_noop(self):
        assert _ZOOM_DECISIONS[(PipelineEventKind.RESPONSE_EVENT, StopReason.TOOL_USE)] is None

    def test_error_unzooms(self):
        assert _ZOOM_DECISIONS[(PipelineEventKind.ERROR, None)] is False

    def test_proxy_error_unzooms(self):
        assert _ZOOM_DECISIONS[(PipelineEventKind.PROXY_ERROR, None)] is False


# ─── _extract_decision_key ───────────────────────────────────────────────────


class TestExtractDecisionKey:
    def test_request_body_event(self):
        event = RequestBodyEvent(body={})
        assert _extract_decision_key(event) == (PipelineEventKind.REQUEST, None)

    def test_response_sse_message_delta_end_turn(self):
        sse = MessageDeltaEvent(stop_reason=StopReason.END_TURN, stop_sequence="", output_tokens=0)
        event = ResponseSSEEvent(sse_event=sse)
        assert _extract_decision_key(event) == (PipelineEventKind.RESPONSE_EVENT, StopReason.END_TURN)

    def test_response_sse_message_delta_tool_use(self):
        sse = MessageDeltaEvent(stop_reason=StopReason.TOOL_USE, stop_sequence="", output_tokens=0)
        event = ResponseSSEEvent(sse_event=sse)
        assert _extract_decision_key(event) == (PipelineEventKind.RESPONSE_EVENT, StopReason.TOOL_USE)

    def test_response_sse_non_delta(self):
        """Non-MessageDeltaEvent SSE events get stop_reason=None."""
        sse = TextDeltaEvent(index=0, text="hello")
        event = ResponseSSEEvent(sse_event=sse)
        assert _extract_decision_key(event) == (PipelineEventKind.RESPONSE_EVENT, None)

    def test_error_event(self):
        event = ErrorEvent(code=500, reason="server error")
        assert _extract_decision_key(event) == (PipelineEventKind.ERROR, None)

    def test_proxy_error_event(self):
        event = ProxyErrorEvent(error="connection refused")
        assert _extract_decision_key(event) == (PipelineEventKind.PROXY_ERROR, None)


# ─── is_available() ──────────────────────────────────────────────────────────


class TestIsAvailable:
    def test_no_tmux_env(self):
        with patch.dict(os.environ, {}, clear=True):
            assert is_available() is False

    def test_tmux_set_no_libtmux(self):
        with patch.dict(os.environ, {"TMUX": "/tmp/tmux-1000/default,123,0"}):
            with patch.dict("sys.modules", {"libtmux": None}):
                assert is_available() is False

    def test_tmux_set_with_libtmux(self):
        mock_libtmux = MagicMock()
        with patch.dict(os.environ, {"TMUX": "/tmp/tmux-1000/default,123,0"}):
            with patch.dict("sys.modules", {"libtmux": mock_libtmux}):
                assert is_available() is True


# ─── TmuxController state machine ───────────────────────────────────────────


class TestTmuxControllerStates:
    def test_not_in_tmux(self, make_controller):
        ctrl = make_controller()
        assert ctrl.state == TmuxState.NOT_IN_TMUX

    def test_not_in_tmux_cannot_launch(self, make_controller):
        ctrl = make_controller()
        result = ctrl.launch_claude()
        assert result.action == LaunchAction.BLOCKED
        assert not result.success

    def test_not_in_tmux_zoom_is_noop(self, make_controller):
        ctrl = make_controller()
        ctrl.zoom()
        assert ctrl._is_zoomed is False


# ─── on_event behavior ──────────────────────────────────────────────────────


class TestOnEvent:
    def test_request_triggers_zoom(self, active_controller):
        event = RequestBodyEvent(body={})
        active_controller.on_event(event)
        assert active_controller._is_zoomed is True
        active_controller._our_pane.resize.assert_called_once_with(zoom=True)

    def test_end_turn_triggers_unzoom(self, make_controller):
        ctrl = make_controller(
            state=TmuxState.CLAUDE_RUNNING,
            auto_zoom=True,
            _is_zoomed=True,
            _our_pane=MagicMock(),
            _claude_pane=MagicMock(),
        )
        sse = MessageDeltaEvent(stop_reason=StopReason.END_TURN, stop_sequence="", output_tokens=0)
        event = ResponseSSEEvent(sse_event=sse)
        ctrl.on_event(event)
        assert ctrl._is_zoomed is False

    def test_tool_use_is_noop(self, make_controller):
        ctrl = make_controller(
            state=TmuxState.CLAUDE_RUNNING,
            auto_zoom=True,
            _is_zoomed=True,
            _our_pane=MagicMock(),
            _claude_pane=MagicMock(),
        )
        sse = MessageDeltaEvent(stop_reason=StopReason.TOOL_USE, stop_sequence="", output_tokens=0)
        event = ResponseSSEEvent(sse_event=sse)
        ctrl.on_event(event)
        # Should stay zoomed — no change
        assert ctrl._is_zoomed is True
        ctrl._our_pane.resize.assert_not_called()

    def test_error_triggers_unzoom(self, make_controller):
        ctrl = make_controller(
            state=TmuxState.CLAUDE_RUNNING,
            auto_zoom=True,
            _is_zoomed=True,
            _our_pane=MagicMock(),
            _claude_pane=MagicMock(),
        )
        event = ErrorEvent(code=500, reason="fail")
        ctrl.on_event(event)
        assert ctrl._is_zoomed is False

    def test_proxy_error_triggers_unzoom(self, make_controller):
        ctrl = make_controller(
            state=TmuxState.CLAUDE_RUNNING,
            auto_zoom=True,
            _is_zoomed=True,
            _our_pane=MagicMock(),
            _claude_pane=MagicMock(),
        )
        event = ProxyErrorEvent(error="connection refused")
        ctrl.on_event(event)
        assert ctrl._is_zoomed is False

    def test_auto_zoom_off_ignores_events(self, active_controller):
        active_controller.auto_zoom = False
        event = RequestBodyEvent(body={})
        active_controller.on_event(event)
        assert active_controller._is_zoomed is False
        active_controller._our_pane.resize.assert_not_called()

    def test_not_claude_running_ignores_events(self, make_controller):
        ctrl = make_controller(
            state=TmuxState.READY,
            _our_pane=MagicMock(),
            _claude_pane=MagicMock(),
        )
        event = RequestBodyEvent(body={})
        ctrl.on_event(event)
        assert ctrl._is_zoomed is False
        ctrl._our_pane.resize.assert_not_called()

    def test_unrelated_sse_event_no_decision(self, active_controller):
        """TextDeltaEvent wrapped in ResponseSSEEvent has no table entry."""
        sse = TextDeltaEvent(index=0, text="hello")
        event = ResponseSSEEvent(sse_event=sse)
        active_controller.on_event(event)
        assert active_controller._is_zoomed is False
        active_controller._our_pane.resize.assert_not_called()

    def test_response_done_no_decision(self, active_controller):
        """ResponseDoneEvent has no table entry — no-op."""
        event = ResponseDoneEvent()
        active_controller.on_event(event)
        assert active_controller._is_zoomed is False
        active_controller._our_pane.resize.assert_not_called()


# ─── Zoom idempotency ───────────────────────────────────────────────────────


class TestZoomIdempotency:
    def test_zoom_when_already_zoomed_is_noop(self, make_controller):
        ctrl = make_controller(
            _is_zoomed=True,
            _our_pane=MagicMock(),
        )
        ctrl.zoom()
        ctrl._our_pane.resize.assert_not_called()

    def test_unzoom_when_not_zoomed_is_noop(self, make_controller):
        ctrl = make_controller(_our_pane=MagicMock())
        ctrl.unzoom()
        ctrl._our_pane.resize.assert_not_called()

    def test_toggle_zoom(self, make_controller):
        ctrl = make_controller(_our_pane=MagicMock())
        ctrl.toggle_zoom()
        assert ctrl._is_zoomed is True
        ctrl.toggle_zoom()
        assert ctrl._is_zoomed is False


# ─── toggle_auto_zoom ────────────────────────────────────────────────────────


class TestToggleAutoZoom:
    def test_toggle(self, make_controller):
        ctrl = make_controller()
        assert ctrl.auto_zoom is False
        ctrl.toggle_auto_zoom()
        assert ctrl.auto_zoom is True
        ctrl.toggle_auto_zoom()
        assert ctrl.auto_zoom is False


# ─── cleanup ─────────────────────────────────────────────────────────────────


class TestCleanup:
    def test_cleanup_unzooms(self, make_controller):
        ctrl = make_controller(
            _is_zoomed=True,
            _our_pane=MagicMock(),
        )
        ctrl.cleanup()
        assert ctrl._is_zoomed is False
        ctrl._our_pane.resize.assert_called_once_with(zoom=True)

    def test_cleanup_when_not_zoomed_is_noop(self, make_controller):
        ctrl = make_controller(
            _our_pane=MagicMock(),
        )
        ctrl.cleanup()
        ctrl._our_pane.resize.assert_not_called()

# ─── _validate_claude_pane ─────────────────────────────────────────────────


class TestValidateClaudePane:
    def test_alive_pane_returns_true(self, make_controller):
        pane = MagicMock()
        ctrl = make_controller(
            state=TmuxState.CLAUDE_RUNNING,
            _claude_pane=pane,
            _our_pane=MagicMock(),
        )
        assert ctrl._validate_claude_pane() is True
        pane.refresh.assert_called_once()

    def test_dead_pane_transitions_to_ready(self, make_controller):
        pane = MagicMock()
        pane.refresh.side_effect = Exception("pane is dead")
        ctrl = make_controller(
            state=TmuxState.CLAUDE_RUNNING,
            _claude_pane=pane,
            _our_pane=MagicMock(),
        )
        assert ctrl._validate_claude_pane() is False
        assert ctrl._claude_pane is None
        assert ctrl.state == TmuxState.READY

    def test_absent_pane_returns_false(self, make_controller):
        ctrl = make_controller(state=TmuxState.READY, _our_pane=MagicMock())
        assert ctrl._validate_claude_pane() is False


# ─── _find_claude_pane ────────────────────────────────────────────────────


class TestFindClaudePane:
    def test_finds_claude_pane(self, make_controller):
        our_pane = MagicMock()
        our_pane.pane_id = "%0"
        claude_pane = MagicMock()
        claude_pane.pane_id = "%1"
        claude_pane.pane_current_command = "claude"
        window = MagicMock()
        window.panes = [our_pane, claude_pane]
        our_pane.window = window
        ctrl = make_controller(
            state=TmuxState.READY,
            _our_pane=our_pane,
        )
        assert ctrl._find_claude_pane() is claude_pane

    def test_no_claude_returns_none(self, make_controller):
        our_pane = MagicMock()
        our_pane.pane_id = "%0"
        other_pane = MagicMock()
        other_pane.pane_id = "%1"
        other_pane.pane_current_command = "bash"
        window = MagicMock()
        window.panes = [our_pane, other_pane]
        our_pane.window = window
        ctrl = make_controller(
            state=TmuxState.READY,
            _our_pane=our_pane,
        )
        assert ctrl._find_claude_pane() is None

    def test_skips_own_pane(self, make_controller):
        """Even if our own pane runs 'claude', it should not be adopted."""
        our_pane = MagicMock()
        our_pane.pane_id = "%0"
        our_pane.pane_current_command = "claude"
        window = MagicMock()
        window.panes = [our_pane]
        our_pane.window = window
        ctrl = make_controller(
            state=TmuxState.READY,
            _our_pane=our_pane,
        )
        assert ctrl._find_claude_pane() is None

    def test_matches_custom_command(self, make_controller):
        our_pane = MagicMock()
        our_pane.pane_id = "%0"
        custom_pane = MagicMock()
        custom_pane.pane_id = "%1"
        custom_pane.pane_current_command = "my-claude"
        window = MagicMock()
        window.panes = [our_pane, custom_pane]
        our_pane.window = window
        ctrl = make_controller(
            state=TmuxState.READY,
            _our_pane=our_pane,
            _claude_command="my-claude",
        )
        assert ctrl._find_claude_pane() is custom_pane

    def test_matches_basename_of_full_path(self, make_controller):
        """Command '/usr/bin/claude' should match pane running 'claude'."""
        our_pane = MagicMock()
        our_pane.pane_id = "%0"
        claude_pane = MagicMock()
        claude_pane.pane_id = "%1"
        claude_pane.pane_current_command = "claude"
        window = MagicMock()
        window.panes = [our_pane, claude_pane]
        our_pane.window = window
        ctrl = make_controller(
            state=TmuxState.READY,
            _our_pane=our_pane,
            _claude_command="/usr/bin/claude",
        )
        assert ctrl._find_claude_pane() is claude_pane


# ─── _try_adopt_existing ──────────────────────────────────────────────────


class TestTryAdoptExisting:
    def test_adopts_existing_claude_pane(self, make_controller):
        our_pane = MagicMock()
        our_pane.pane_id = "%0"
        claude_pane = MagicMock()
        claude_pane.pane_id = "%1"
        claude_pane.pane_current_command = "claude"
        window = MagicMock()
        window.panes = [our_pane, claude_pane]
        our_pane.window = window
        ctrl = make_controller(
            state=TmuxState.READY,
            _our_pane=our_pane,
        )
        ctrl._try_adopt_existing()
        assert ctrl._claude_pane is claude_pane
        assert ctrl.state == TmuxState.CLAUDE_RUNNING

    def test_no_existing_stays_ready(self, make_controller):
        our_pane = MagicMock()
        our_pane.pane_id = "%0"
        window = MagicMock()
        window.panes = [our_pane]
        our_pane.window = window
        ctrl = make_controller(
            state=TmuxState.READY,
            _our_pane=our_pane,
        )
        ctrl._try_adopt_existing()
        assert ctrl._claude_pane is None
        assert ctrl.state == TmuxState.READY


# ─── Configurable command ─────────────────────────────────────────────────


class TestConfigurableCommand:
    def test_default_command(self, make_controller):
        ctrl = make_controller()
        assert ctrl._claude_command == "claude"

    def test_custom_command_via_override(self, make_controller):
        ctrl = make_controller(_claude_command="my-claude")
        assert ctrl._claude_command == "my-claude"

    def test_set_claude_command(self, make_controller):
        ctrl = make_controller()
        ctrl.set_claude_command("custom-claude")
        assert ctrl._claude_command == "custom-claude"


# ─── launch_claude with dead pane ──────────────────────────────────────────


class TestLaunchWithDeadPane:
    def test_dead_pane_triggers_relaunch(self, make_controller):
        """launch_claude with a dead pane reference should try to adopt or relaunch."""
        dead_pane = MagicMock()
        dead_pane.refresh.side_effect = Exception("pane dead")
        our_pane = MagicMock()
        our_pane.pane_id = "%0"
        window = MagicMock()
        window.panes = [our_pane]
        our_pane.window = window

        ctrl = make_controller(
            state=TmuxState.CLAUDE_RUNNING,
            _our_pane=our_pane,
            _claude_pane=dead_pane,
            _port=8080,
        )

        # After dead pane detection: no sibling claude, should split new pane
        new_pane = MagicMock()
        window.split.return_value = new_pane

        import libtmux.constants
        result = ctrl.launch_claude()

        assert result.action == LaunchAction.LAUNCHED
        assert result.success
        assert ctrl._claude_pane is new_pane
        assert ctrl.state == TmuxState.CLAUDE_RUNNING

    def test_dead_pane_adopts_existing(self, make_controller):
        """launch_claude with dead pane should adopt if another claude exists."""
        dead_pane = MagicMock()
        dead_pane.refresh.side_effect = Exception("pane dead")
        our_pane = MagicMock()
        our_pane.pane_id = "%0"
        existing_claude = MagicMock()
        existing_claude.pane_id = "%2"
        existing_claude.pane_current_command = "claude"
        window = MagicMock()
        window.panes = [our_pane, existing_claude]
        our_pane.window = window

        ctrl = make_controller(
            state=TmuxState.CLAUDE_RUNNING,
            _our_pane=our_pane,
            _claude_pane=dead_pane,
            _port=8080,
        )

        result = ctrl.launch_claude()
        assert result.action == LaunchAction.FOCUSED
        assert result.success
        assert ctrl._claude_pane is existing_claude
        assert ctrl.state == TmuxState.CLAUDE_RUNNING
        existing_claude.select.assert_called_once()


# ─── Auto-resume: session_id → --resume in launch command ────────────────


class TestAutoResume:
    """End-to-end: session_id extraction → build_command_args → launch_claude exec."""

    def test_resume_flag_in_launched_command(self, make_controller):
        """When auto_resume is True and session_id is known, --resume appears in the command."""
        from cc_dump.launch_config import LaunchConfig, build_full_command

        our_pane = MagicMock()
        our_pane.pane_id = "%0"
        window = MagicMock()
        window.panes = [our_pane]
        our_pane.window = window
        new_pane = MagicMock()
        window.split.return_value = new_pane

        ctrl = make_controller(
            state=TmuxState.READY,
            _our_pane=our_pane,
            _port=3344,
        )

        session_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        config = LaunchConfig(auto_resume=True)
        full_command = build_full_command(config, session_id)

        result = ctrl.launch_claude(command=full_command)

        assert result.action == LaunchAction.LAUNCHED
        assert result.success
        assert "--resume {}".format(session_id) in result.command
        assert "ANTHROPIC_BASE_URL" in result.command

    def test_no_resume_without_session_id(self, make_controller):
        """Without a session_id, --resume is not in the command."""
        from cc_dump.launch_config import LaunchConfig, build_full_command

        our_pane = MagicMock()
        our_pane.pane_id = "%0"
        window = MagicMock()
        window.panes = [our_pane]
        our_pane.window = window
        new_pane = MagicMock()
        window.split.return_value = new_pane

        ctrl = make_controller(
            state=TmuxState.READY,
            _our_pane=our_pane,
            _port=3344,
        )

        config = LaunchConfig(auto_resume=True)
        full_command = build_full_command(config, "")

        result = ctrl.launch_claude(command=full_command)

        assert result.action == LaunchAction.LAUNCHED
        assert "--resume" not in result.command

    def test_no_resume_when_disabled(self, make_controller):
        """With auto_resume=False, --resume is not in the command even with session_id."""
        from cc_dump.launch_config import LaunchConfig, build_full_command

        our_pane = MagicMock()
        our_pane.pane_id = "%0"
        window = MagicMock()
        window.panes = [our_pane]
        our_pane.window = window
        new_pane = MagicMock()
        window.split.return_value = new_pane

        ctrl = make_controller(
            state=TmuxState.READY,
            _our_pane=our_pane,
            _port=3344,
        )

        config = LaunchConfig(auto_resume=False)
        full_command = build_full_command(config, "some-session-id")

        result = ctrl.launch_claude(command=full_command)

        assert result.action == LaunchAction.LAUNCHED
        assert "--resume" not in result.command

    def test_session_id_from_metadata_to_launch(self):
        """Full chain: metadata.user_id → format_request → state → build_full_command."""
        from cc_dump.formatting import format_request
        from cc_dump.launch_config import LaunchConfig, build_full_command

        state = {
            "request_counter": 0,
            "positions": {},
            "known_hashes": {},
            "next_id": 1,
            "next_color": 0,
        }
        body = {
            "model": "claude-3-opus-20240229",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": "Hello"}],
            "metadata": {
                "user_id": "user_abc123def_account_11111111-2222-3333-4444-555555555555_session_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            },
        }

        format_request(body, state)

        session_id = state["current_session"]
        assert session_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        config = LaunchConfig(auto_resume=True)
        cmd = build_full_command(config, session_id)
        assert cmd == "claude --resume aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


# ─── on_event with dead pane ─────────────────────────────────────────────


class TestOnEventWithDeadPane:
    def test_dead_pane_skips_zoom(self, make_controller):
        """on_event with dead claude pane should not attempt zoom."""
        dead_pane = MagicMock()
        dead_pane.refresh.side_effect = Exception("pane dead")
        ctrl = make_controller(
            state=TmuxState.CLAUDE_RUNNING,
            auto_zoom=True,
            _our_pane=MagicMock(),
            _claude_pane=dead_pane,
        )
        event = RequestBodyEvent(body={})
        ctrl.on_event(event)
        # Pane was dead, so state transitioned to READY
        assert ctrl.state == TmuxState.READY
        assert ctrl._is_zoomed is False
