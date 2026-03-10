"""Tests for tmux_controller launch/adopt/log-tail behavior.

All tests mock libtmux and tmux env vars; no actual tmux required.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from cc_dump.pipeline.event_types import RequestBodyEvent
from cc_dump.app.tmux_controller import (
    LogTailAction,
    LaunchAction,
    TmuxController,
    TmuxState,
    is_available,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


_VALID_ATTRS = frozenset({
    "state",
    "_launch_command", "_process_names", "_launch_env", "_launcher_label",
    "_server", "_session", "_our_pane", "_tool_pane",
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
        command_override = overrides.pop("_launch_command", None)
        for k, v in overrides.items():
            setattr(ctrl, k, v)
        if command_override is not None:
            ctrl.set_launch_command(command_override)
        return ctrl

    return _factory


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
        result = ctrl.launch_tool()
        assert result.action == LaunchAction.BLOCKED
        assert not result.success

class TestEventHooks:
    def test_on_event_is_noop(self, make_controller):
        ctrl = make_controller(
            state=TmuxState.TOOL_RUNNING,
            _our_pane=MagicMock(),
            _tool_pane=MagicMock(),
        )
        ctrl.on_event(RequestBodyEvent(body={}))
        assert ctrl.state == TmuxState.TOOL_RUNNING

    def test_cleanup_is_noop(self, make_controller):
        ctrl = make_controller(
            state=TmuxState.TOOL_RUNNING,
            _our_pane=MagicMock(),
            _tool_pane=MagicMock(),
        )
        ctrl.cleanup()
        assert ctrl.state == TmuxState.TOOL_RUNNING

# ─── _validate_tool_pane ─────────────────────────────────────────────────


class TestValidateClaudePane:
    def test_alive_pane_returns_true(self, make_controller):
        pane = MagicMock()
        ctrl = make_controller(
            state=TmuxState.TOOL_RUNNING,
            _tool_pane=pane,
            _our_pane=MagicMock(),
        )
        assert ctrl._validate_tool_pane() is True
        pane.refresh.assert_called_once()

    def test_dead_pane_transitions_to_ready(self, make_controller):
        pane = MagicMock()
        pane.refresh.side_effect = Exception("pane is dead")
        ctrl = make_controller(
            state=TmuxState.TOOL_RUNNING,
            _tool_pane=pane,
            _our_pane=MagicMock(),
        )
        assert ctrl._validate_tool_pane() is False
        assert ctrl._tool_pane is None
        assert ctrl.state == TmuxState.READY

    def test_absent_pane_returns_false(self, make_controller):
        ctrl = make_controller(state=TmuxState.READY, _our_pane=MagicMock())
        assert ctrl._validate_tool_pane() is False


# ─── _find_tool_pane ────────────────────────────────────────────────────


class TestFindClaudePane:
    def test_finds_tool_pane(self, make_controller):
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
        assert ctrl._find_tool_pane() is claude_pane

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
        assert ctrl._find_tool_pane() is None

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
        assert ctrl._find_tool_pane() is None

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
            _launch_command="my-claude",
        )
        assert ctrl._find_tool_pane() is custom_pane

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
            _launch_command="/usr/bin/claude",
        )
        assert ctrl._find_tool_pane() is claude_pane


# ─── _try_adopt_existing ──────────────────────────────────────────────────


class TestTryAdoptExisting:
    def test_adopts_existing_tool_pane(self, make_controller):
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
        assert ctrl._tool_pane is claude_pane
        assert ctrl.state == TmuxState.TOOL_RUNNING

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
        assert ctrl._tool_pane is None
        assert ctrl.state == TmuxState.READY


# ─── Configurable command ─────────────────────────────────────────────────


class TestConfigurableCommand:
    def test_default_command(self, make_controller):
        ctrl = make_controller()
        assert ctrl._launch_command == "claude"

    def test_custom_command_via_override(self, make_controller):
        ctrl = make_controller(_launch_command="my-claude")
        assert ctrl._launch_command == "my-claude"

    def test_set_launch_command(self, make_controller):
        ctrl = make_controller()
        ctrl.set_launch_command("custom-claude")
        assert ctrl._launch_command == "custom-claude"


# ─── open_log_tail ──────────────────────────────────────────────────────────


class TestOpenLogTail:
    def test_blocked_without_tmux_ready_state(self, make_controller):
        ctrl = make_controller(state=TmuxState.NOT_IN_TMUX)
        result = ctrl.open_log_tail("/tmp/cc-dump.log")
        assert result.action == LogTailAction.BLOCKED
        assert not result.success

    def test_single_pane_splits_below(self, make_controller):
        import libtmux.constants

        our_pane = MagicMock()
        our_pane.pane_id = "%0"
        window = MagicMock()
        window.panes = [our_pane]
        our_pane.window = window
        session = MagicMock()
        ctrl = make_controller(
            state=TmuxState.READY,
            _our_pane=our_pane,
            _session=session,
        )

        result = ctrl.open_log_tail("/tmp/cc-dump.log")

        assert result.action == LogTailAction.SPLIT_BELOW
        assert result.success
        window.split.assert_called_once_with(
            direction=libtmux.constants.PaneDirection.Below,
            shell="tail -f -- /tmp/cc-dump.log",
        )
        session.cmd.assert_not_called()

    def test_clod_pair_top_bottom_splits_right(self, make_controller):
        import libtmux.constants

        our_pane = MagicMock()
        our_pane.pane_id = "%0"
        our_pane.pane_left = "0"
        our_pane.pane_top = "0"

        clod_pane = MagicMock()
        clod_pane.pane_id = "%1"
        clod_pane.pane_current_command = "clod"
        clod_pane.pane_left = "0"
        clod_pane.pane_top = "15"

        window = MagicMock()
        window.panes = [our_pane, clod_pane]
        our_pane.window = window
        session = MagicMock()
        ctrl = make_controller(
            state=TmuxState.READY,
            _our_pane=our_pane,
            _session=session,
            _launch_command="clod",
        )

        result = ctrl.open_log_tail("/tmp/cc-dump.log")

        assert result.action == LogTailAction.SPLIT_RIGHT
        assert result.success
        clod_pane.select.assert_called_once()
        window.split.assert_called_once_with(
            direction=libtmux.constants.PaneDirection.Right,
            shell="tail -f -- /tmp/cc-dump.log",
        )
        session.cmd.assert_not_called()

    def test_clod_pair_side_by_side_splits_below(self, make_controller):
        import libtmux.constants

        our_pane = MagicMock()
        our_pane.pane_id = "%0"
        our_pane.pane_left = "0"
        our_pane.pane_top = "0"

        clod_pane = MagicMock()
        clod_pane.pane_id = "%1"
        clod_pane.pane_current_command = "clod"
        clod_pane.pane_left = "100"
        clod_pane.pane_top = "0"

        window = MagicMock()
        window.panes = [our_pane, clod_pane]
        our_pane.window = window
        session = MagicMock()
        ctrl = make_controller(
            state=TmuxState.READY,
            _our_pane=our_pane,
            _session=session,
            _launch_command="clod",
        )

        result = ctrl.open_log_tail("/tmp/cc-dump.log")

        assert result.action == LogTailAction.SPLIT_BELOW
        assert result.success
        clod_pane.select.assert_called_once()
        window.split.assert_called_once_with(
            direction=libtmux.constants.PaneDirection.Below,
            shell="tail -f -- /tmp/cc-dump.log",
        )
        session.cmd.assert_not_called()

    def test_non_pair_layout_creates_new_window(self, make_controller):
        our_pane = MagicMock()
        our_pane.pane_id = "%0"

        clod_pane = MagicMock()
        clod_pane.pane_id = "%1"
        clod_pane.pane_current_command = "clod"

        extra_pane = MagicMock()
        extra_pane.pane_id = "%2"
        extra_pane.pane_current_command = "bash"

        window = MagicMock()
        window.panes = [our_pane, clod_pane, extra_pane]
        our_pane.window = window
        session = MagicMock()
        ctrl = make_controller(
            state=TmuxState.READY,
            _our_pane=our_pane,
            _session=session,
            _launch_command="clod",
        )

        result = ctrl.open_log_tail("/tmp/cc-dump.log")

        assert result.action == LogTailAction.NEW_WINDOW
        assert result.success
        session.cmd.assert_called_once_with(
            "new-window",
            "-n",
            "cc-dump-logs",
            "tail -f -- /tmp/cc-dump.log",
        )
        window.split.assert_not_called()


# ─── launch_tool with dead pane ──────────────────────────────────────────


class TestLaunchWithDeadPane:
    def test_dead_pane_triggers_relaunch(self, make_controller):
        """launch_tool with a dead pane reference should try to adopt or relaunch."""
        dead_pane = MagicMock()
        dead_pane.refresh.side_effect = Exception("pane dead")
        our_pane = MagicMock()
        our_pane.pane_id = "%0"
        window = MagicMock()
        window.panes = [our_pane]
        our_pane.window = window

        ctrl = make_controller(
            state=TmuxState.TOOL_RUNNING,
            _our_pane=our_pane,
            _tool_pane=dead_pane,
            _launch_env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:8080"},
        )

        # After dead pane detection: no sibling claude, should split new pane
        new_pane = MagicMock()
        window.split.return_value = new_pane

        result = ctrl.launch_tool()

        assert result.action == LaunchAction.LAUNCHED
        assert result.success
        assert ctrl._tool_pane is new_pane
        assert ctrl.state == TmuxState.TOOL_RUNNING

    def test_dead_pane_adopts_existing(self, make_controller):
        """launch_tool with dead pane should adopt if another claude exists."""
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
            state=TmuxState.TOOL_RUNNING,
            _our_pane=our_pane,
            _tool_pane=dead_pane,
            _launch_env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:8080"},
        )

        result = ctrl.launch_tool()
        assert result.action == LaunchAction.FOCUSED
        assert result.success
        assert ctrl._tool_pane is existing_claude
        assert ctrl.state == TmuxState.TOOL_RUNNING
        existing_claude.select.assert_called_once()


# ─── Auto-resume: session_id → --resume in launch command ────────────────


class TestAutoResume:
    """End-to-end: session_id extraction → build_command_args → launch_tool exec."""

    def test_resume_flag_in_launched_command(self, make_controller):
        """When auto_resume is True and session_id is known, --resume appears in the command."""
        from cc_dump.app.launch_config import LaunchConfig, build_full_command

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
            _launch_env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:3344"},
        )

        session_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        config = LaunchConfig(options={"auto_resume": True})
        full_command = build_full_command(config, session_id)

        result = ctrl.launch_tool(command=full_command)

        assert result.action == LaunchAction.LAUNCHED
        assert result.success
        assert "--resume {}".format(session_id) in result.command
        assert "ANTHROPIC_BASE_URL" in result.command

    def test_no_resume_without_session_id(self, make_controller):
        """Without a session_id, --resume is not in the command."""
        from cc_dump.app.launch_config import LaunchConfig, build_full_command

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
            _launch_env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:3344"},
        )

        config = LaunchConfig(options={"auto_resume": True})
        full_command = build_full_command(config, "")

        result = ctrl.launch_tool(command=full_command)

        assert result.action == LaunchAction.LAUNCHED
        assert "--resume" not in result.command

    def test_no_resume_when_disabled(self, make_controller):
        """With auto_resume=False, --resume is not in the command even with session_id."""
        from cc_dump.app.launch_config import LaunchConfig, build_full_command

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
            _launch_env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:3344"},
        )

        config = LaunchConfig(options={"auto_resume": False})
        full_command = build_full_command(config, "some-session-id")

        result = ctrl.launch_tool(command=full_command)

        assert result.action == LaunchAction.LAUNCHED
        assert "--resume" not in result.command

    def test_session_id_from_metadata_to_launch(self):
        """Full chain: metadata.user_id → format_request → state → build_full_command."""
        from cc_dump.core.formatting import format_request
        from cc_dump.app.launch_config import LaunchConfig, build_full_command

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

        config = LaunchConfig(options={"auto_resume": True})
        cmd = build_full_command(config, session_id)
        assert cmd == "claude --resume aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


# ─── on_event with dead pane ─────────────────────────────────────────────


class TestOnEventWithDeadPane:
    def test_dead_pane_is_untouched_by_noop_event_hook(self, make_controller):
        dead_pane = MagicMock()
        dead_pane.refresh.side_effect = Exception("pane dead")
        ctrl = make_controller(
            state=TmuxState.TOOL_RUNNING,
            _our_pane=MagicMock(),
            _tool_pane=dead_pane,
        )
        ctrl.on_event(RequestBodyEvent(body={}))
        # on_event no longer mutates pane state; pane validation remains launch/focus-owned.
        assert ctrl.state == TmuxState.TOOL_RUNNING
        assert ctrl._tool_pane is dead_pane
