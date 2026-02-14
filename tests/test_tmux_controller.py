"""Tests for tmux_controller — zoom decisions, state machine, event handling.

All tests mock libtmux and tmux env vars; no actual tmux required.
"""

import os
from unittest.mock import MagicMock, patch

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
    TmuxController,
    TmuxState,
    _ZOOM_DECISIONS,
    _extract_decision_key,
    is_available,
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
                # Force ImportError
                import builtins
                original_import = builtins.__import__

                def mock_import(name, *args, **kwargs):
                    if name == "libtmux":
                        raise ImportError("no libtmux")
                    return original_import(name, *args, **kwargs)

                with patch("builtins.__import__", side_effect=mock_import):
                    assert is_available() is False

    def test_tmux_set_with_libtmux(self):
        mock_libtmux = MagicMock()
        with patch.dict(os.environ, {"TMUX": "/tmp/tmux-1000/default,123,0"}):
            with patch.dict("sys.modules", {"libtmux": mock_libtmux}):
                assert is_available() is True


# ─── TmuxController state machine ───────────────────────────────────────────


class TestTmuxControllerStates:
    def test_not_in_tmux(self):
        with patch.dict(os.environ, {}, clear=True):
            ctrl = TmuxController()
            assert ctrl.state == TmuxState.NOT_IN_TMUX

    def test_not_in_tmux_cannot_launch(self):
        with patch.dict(os.environ, {}, clear=True):
            ctrl = TmuxController()
            assert ctrl.launch_claude() is False

    def test_not_in_tmux_zoom_is_noop(self):
        with patch.dict(os.environ, {}, clear=True):
            ctrl = TmuxController()
            ctrl.zoom()
            assert ctrl._is_zoomed is False


# ─── on_event behavior ──────────────────────────────────────────────────────


class TestOnEvent:
    def _make_controller(self):
        """Create a controller in CLAUDE_RUNNING state with mocked pane."""
        ctrl = TmuxController.__new__(TmuxController)
        ctrl.state = TmuxState.CLAUDE_RUNNING
        ctrl.auto_zoom = True
        ctrl._is_zoomed = False
        ctrl._port = 3344
        ctrl._server = None
        ctrl._session = None
        ctrl._our_pane = MagicMock()
        ctrl._claude_pane = MagicMock()
        return ctrl

    def test_request_triggers_zoom(self):
        ctrl = self._make_controller()
        event = RequestBodyEvent(body={})
        ctrl.on_event(event)
        assert ctrl._is_zoomed is True
        ctrl._our_pane.resize.assert_called_once_with(zoom=True)

    def test_end_turn_triggers_unzoom(self):
        ctrl = self._make_controller()
        ctrl._is_zoomed = True  # Start zoomed
        sse = MessageDeltaEvent(stop_reason=StopReason.END_TURN, stop_sequence="", output_tokens=0)
        event = ResponseSSEEvent(sse_event=sse)
        ctrl.on_event(event)
        assert ctrl._is_zoomed is False

    def test_tool_use_is_noop(self):
        ctrl = self._make_controller()
        ctrl._is_zoomed = True
        sse = MessageDeltaEvent(stop_reason=StopReason.TOOL_USE, stop_sequence="", output_tokens=0)
        event = ResponseSSEEvent(sse_event=sse)
        ctrl.on_event(event)
        # Should stay zoomed — no change
        assert ctrl._is_zoomed is True
        ctrl._our_pane.resize.assert_not_called()

    def test_error_triggers_unzoom(self):
        ctrl = self._make_controller()
        ctrl._is_zoomed = True
        event = ErrorEvent(code=500, reason="fail")
        ctrl.on_event(event)
        assert ctrl._is_zoomed is False

    def test_proxy_error_triggers_unzoom(self):
        ctrl = self._make_controller()
        ctrl._is_zoomed = True
        event = ProxyErrorEvent(error="connection refused")
        ctrl.on_event(event)
        assert ctrl._is_zoomed is False

    def test_auto_zoom_off_ignores_events(self):
        ctrl = self._make_controller()
        ctrl.auto_zoom = False
        event = RequestBodyEvent(body={})
        ctrl.on_event(event)
        assert ctrl._is_zoomed is False
        ctrl._our_pane.resize.assert_not_called()

    def test_not_claude_running_ignores_events(self):
        ctrl = self._make_controller()
        ctrl.state = TmuxState.READY
        event = RequestBodyEvent(body={})
        ctrl.on_event(event)
        assert ctrl._is_zoomed is False
        ctrl._our_pane.resize.assert_not_called()

    def test_unrelated_sse_event_no_decision(self):
        """TextDeltaEvent wrapped in ResponseSSEEvent has no table entry."""
        ctrl = self._make_controller()
        sse = TextDeltaEvent(index=0, text="hello")
        event = ResponseSSEEvent(sse_event=sse)
        ctrl.on_event(event)
        assert ctrl._is_zoomed is False
        ctrl._our_pane.resize.assert_not_called()

    def test_response_done_no_decision(self):
        """ResponseDoneEvent has no table entry — no-op."""
        ctrl = self._make_controller()
        event = ResponseDoneEvent()
        ctrl.on_event(event)
        assert ctrl._is_zoomed is False
        ctrl._our_pane.resize.assert_not_called()


# ─── Zoom idempotency ───────────────────────────────────────────────────────


class TestZoomIdempotency:
    def _make_controller(self):
        ctrl = TmuxController.__new__(TmuxController)
        ctrl.state = TmuxState.CLAUDE_RUNNING
        ctrl.auto_zoom = True
        ctrl._is_zoomed = False
        ctrl._port = 3344
        ctrl._server = None
        ctrl._session = None
        ctrl._our_pane = MagicMock()
        ctrl._claude_pane = MagicMock()
        return ctrl

    def test_zoom_when_already_zoomed_is_noop(self):
        ctrl = self._make_controller()
        ctrl._is_zoomed = True
        ctrl.zoom()
        ctrl._our_pane.resize.assert_not_called()

    def test_unzoom_when_not_zoomed_is_noop(self):
        ctrl = self._make_controller()
        ctrl._is_zoomed = False
        ctrl.unzoom()
        ctrl._our_pane.resize.assert_not_called()

    def test_toggle_zoom(self):
        ctrl = self._make_controller()
        ctrl.toggle_zoom()
        assert ctrl._is_zoomed is True
        ctrl.toggle_zoom()
        assert ctrl._is_zoomed is False


# ─── toggle_auto_zoom ────────────────────────────────────────────────────────


class TestToggleAutoZoom:
    def test_toggle(self):
        ctrl = TmuxController.__new__(TmuxController)
        ctrl.auto_zoom = True
        ctrl.toggle_auto_zoom()
        assert ctrl.auto_zoom is False
        ctrl.toggle_auto_zoom()
        assert ctrl.auto_zoom is True


# ─── cleanup ─────────────────────────────────────────────────────────────────


class TestCleanup:
    def test_cleanup_unzooms(self):
        ctrl = TmuxController.__new__(TmuxController)
        ctrl.state = TmuxState.CLAUDE_RUNNING
        ctrl.auto_zoom = True
        ctrl._is_zoomed = True
        ctrl._our_pane = MagicMock()
        ctrl._claude_pane = MagicMock()
        ctrl._original_mouse = None
        ctrl._mouse_is_on = None
        ctrl.cleanup()
        assert ctrl._is_zoomed is False
        ctrl._our_pane.resize.assert_called_once_with(zoom=True)

    def test_cleanup_when_not_zoomed_is_noop(self):
        ctrl = TmuxController.__new__(TmuxController)
        ctrl.state = TmuxState.READY
        ctrl.auto_zoom = True
        ctrl._is_zoomed = False
        ctrl._our_pane = MagicMock()
        ctrl._claude_pane = None
        ctrl._original_mouse = None
        ctrl._mouse_is_on = None
        ctrl.cleanup()
        ctrl._our_pane.resize.assert_not_called()
