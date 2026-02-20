"""Tmux integration for cc-dump — split panes, auto-zoom on API activity.

This module is STABLE — holds live pane references, never hot-reloaded.
All libtmux usage is lazy-imported and wrapped in try/except.

// [LAW:locality-or-seam] All tmux logic isolated here; rest of app uses is_available() + TmuxController.
// [LAW:dataflow-not-control-flow] Zoom decisions via _ZOOM_DECISIONS lookup table.
"""

from __future__ import annotations

import os
import sys
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import libtmux

from cc_dump.event_types import (
    MessageDeltaEvent,
    PipelineEvent,
    PipelineEventKind,
    ResponseSSEEvent,
    StopReason,
)


class TmuxState(Enum):
    """Controller state machine."""

    NOT_IN_TMUX = auto()
    NO_LIBTMUX = auto()
    READY = auto()
    CLAUDE_RUNNING = auto()


# ─── Launch result ────────────────────────────────────────────────────────────


class LaunchAction(Enum):
    """What launch_claude decided to do."""
    LAUNCHED = "launched"
    FOCUSED = "focused"
    BLOCKED = "blocked"


class LaunchResult:
    """Result of launch_claude — what happened and why.

    // [LAW:dataflow-not-control-flow] The decision is a value, not hidden in branches.
    """
    __slots__ = ("action", "detail", "success", "command")

    def __init__(self, action: LaunchAction, detail: str, success: bool, command: str = ""):
        self.action = action
        self.detail = detail
        self.success = success
        self.command = command  # the shell command, if launched

    def __repr__(self) -> str:
        parts = "action={}, detail={!r}, success={}".format(
            self.action.value, self.detail, self.success
        )
        if self.command:
            parts += ", command={!r}".format(self.command)
        return "LaunchResult({})".format(parts)


# ─── Zoom decision table ─────────────────────────────────────────────────────
# Key: (PipelineEventKind, StopReason | None)
# Value: True = zoom, False = unzoom, None = no-op
# // [LAW:dataflow-not-control-flow] Table lookup, not if/elif chains.

_ZOOM_DECISIONS: dict[tuple[PipelineEventKind, StopReason | None], bool | None] = {
    (PipelineEventKind.REQUEST, None): True,
    (PipelineEventKind.RESPONSE_EVENT, StopReason.END_TURN): False,
    (PipelineEventKind.RESPONSE_EVENT, StopReason.MAX_TOKENS): False,
    (PipelineEventKind.RESPONSE_EVENT, StopReason.TOOL_USE): None,
    (PipelineEventKind.ERROR, None): False,
    (PipelineEventKind.PROXY_ERROR, None): False,
}


def _extract_decision_key(
    event: PipelineEvent,
) -> tuple[PipelineEventKind, StopReason | None]:
    """Extract the lookup key from a pipeline event.

    For ResponseSSEEvent wrapping MessageDeltaEvent, use the stop_reason.
    For all other events, stop_reason is None.
    """
    stop_reason: StopReason | None = None
    if isinstance(event, ResponseSSEEvent) and isinstance(
        event.sse_event, MessageDeltaEvent
    ):
        stop_reason = event.sse_event.stop_reason
    return (event.kind, stop_reason)


def is_available() -> bool:
    """Check if tmux integration is possible ($TMUX set + libtmux importable)."""
    if not os.environ.get("TMUX"):
        return False
    try:
        import libtmux  # noqa: F401

        return True
    except ImportError:
        return False


class TmuxController:
    """Manages tmux pane splitting, zoom, and claude lifecycle.

    // [LAW:single-enforcer] on_event() is the sole zoom decision point.
    // [LAW:single-enforcer] _validate_claude_pane() is the sole pane liveness check.
    """

    def __init__(self, claude_command: str = "claude", auto_zoom: bool = False) -> None:
        self.state = TmuxState.NOT_IN_TMUX
        self.auto_zoom = auto_zoom
        self._is_zoomed = False
        self._port: int | None = None
        self._claude_command = claude_command
        self._server: libtmux.Server | None = None
        self._session: libtmux.Session | None = None
        self._our_pane: libtmux.Pane | None = None
        self._claude_pane: libtmux.Pane | None = None

        if not os.environ.get("TMUX"):
            self.state = TmuxState.NOT_IN_TMUX
            return

        try:
            import libtmux

            self._server = libtmux.Server()
            pane_id = os.environ.get("TMUX_PANE")
            if not pane_id:
                self.state = TmuxState.NOT_IN_TMUX
                return

            # Find our pane by $TMUX_PANE
            for session in self._server.sessions:
                for window in session.windows:
                    for pane in window.panes:
                        if pane.pane_id == pane_id:
                            self._our_pane = pane
                            self._session = session

            if self._our_pane is None:
                _log("could not find pane with id {}".format(pane_id))
                self.state = TmuxState.NOT_IN_TMUX
                return

            self.state = TmuxState.READY
            self._try_adopt_existing()

        except ImportError:
            self.state = TmuxState.NO_LIBTMUX
        except Exception as e:
            _log("init error: {}".format(e))
            self.state = TmuxState.NOT_IN_TMUX

    def set_port(self, port: int) -> None:
        """Set the proxy port (called from cli.py after server starts)."""
        self._port = port

    def set_claude_command(self, command: str) -> None:
        """Update the Claude command at runtime."""
        self._claude_command = command

    def _validate_claude_pane(self) -> bool:
        """// [LAW:single-enforcer] Sole pane liveness check.

        Returns True if claude pane is alive, False if dead/absent.
        On dead pane: clears reference and transitions to READY.
        """
        if self._claude_pane is None:
            return False
        try:
            # libtmux refresh fetches fresh state from tmux server
            self._claude_pane.refresh()
            return True
        except Exception:
            self._claude_pane = None
            self.state = TmuxState.READY
            return False

    def _find_claude_pane(self) -> "libtmux.Pane | None":
        """Scan sibling panes for a running Claude process."""
        if self._our_pane is None:
            return None
        try:
            # Extract binary name from command (e.g. "/usr/bin/claude" -> "claude")
            target = os.path.basename(self._claude_command)
            window = self._our_pane.window
            for pane in window.panes:
                if pane.pane_id == self._our_pane.pane_id:
                    continue
                current_cmd = getattr(pane, "pane_current_command", None) or ""
                if os.path.basename(current_cmd) == target:
                    return pane
        except Exception as e:
            _log("_find_claude_pane error: {}".format(e))
        return None

    def _try_adopt_existing(self) -> None:
        """Adopt an existing Claude pane if found. Transitions to CLAUDE_RUNNING."""
        found = self._find_claude_pane()
        if found is not None:
            self._claude_pane = found
            self.state = TmuxState.CLAUDE_RUNNING

    @property
    def claude_command(self) -> str:
        """The base claude command (e.g. 'claude', 'clod')."""
        return self._claude_command

    def launch_claude(self, command: str = "") -> LaunchResult:
        """Evaluate preconditions, derive action, log, execute.

        Args:
            command: Full command to run (e.g. 'claude --resume abc' or
                     'zsh -c "source ~/.zshrc; clod --resume abc"').
                     If empty, falls back to self._claude_command.

        // [LAW:dataflow-not-control-flow] All preconditions evaluated unconditionally.
        // Action is a value derived from the preconditions, not hidden in branches.
        """
        resolved_command = command or self._claude_command

        # ── Evaluate all preconditions unconditionally ──
        state_ok = self.state in (TmuxState.READY, TmuxState.CLAUDE_RUNNING)

        pane_alive = (
            self._validate_claude_pane() if self._claude_pane is not None
            else False
        )
        if not pane_alive:
            self._try_adopt_existing()
            pane_alive = self._claude_pane is not None

        port_ok = self._port is not None

        # ── Derive action from preconditions ──
        action: LaunchAction
        detail: str
        if not state_ok:
            action, detail = LaunchAction.BLOCKED, "state={}".format(self.state)
        elif pane_alive:
            pane_id = getattr(self._claude_pane, "pane_id", "?")
            action, detail = LaunchAction.FOCUSED, "existing pane {}".format(pane_id)
        elif not port_ok:
            action, detail = LaunchAction.BLOCKED, "port not set"
        else:
            action, detail = LaunchAction.LAUNCHED, resolved_command

        _log("launch_claude: {} ({})".format(action.value, detail))

        # ── Execute ──
        if action == LaunchAction.FOCUSED:
            ok = self.focus_claude()
            return LaunchResult(action, detail, ok)

        if action == LaunchAction.LAUNCHED:
            return self._exec_launch(resolved_command)

        return LaunchResult(action, detail, success=False)

    def _exec_launch(self, command: str) -> LaunchResult:
        """Split pane and run the command with ANTHROPIC_BASE_URL set."""
        try:
            import libtmux

            window = self._our_pane.window
            shell = "ANTHROPIC_BASE_URL=http://127.0.0.1:{} {}".format(
                self._port, command
            )
            _log("exec: {}".format(shell))
            self._claude_pane = window.split(
                direction=libtmux.constants.PaneDirection.Below,
                shell=shell,
            )
            self.state = TmuxState.CLAUDE_RUNNING
            return LaunchResult(LaunchAction.LAUNCHED, command, success=True, command=shell)
        except Exception as e:
            _log("launch error: {}".format(e))
            return LaunchResult(LaunchAction.BLOCKED, str(e), success=False)

    def focus_self(self) -> bool:
        """Select the cc-dump pane."""
        if self._our_pane is None:
            return False
        try:
            self._our_pane.select()
            return True
        except Exception as e:
            _log("focus_self error: {}".format(e))
            return False

    def focus_claude(self) -> bool:
        """Select the claude pane (bring it to foreground)."""
        if not self._validate_claude_pane():
            return False
        try:
            self._claude_pane.select()
            return True
        except Exception as e:
            _log("focus_claude error: {}".format(e))
            return False

    def zoom(self) -> None:
        """Zoom cc-dump pane to full screen. Idempotent."""
        if self._is_zoomed or self._our_pane is None:
            return
        try:
            self._our_pane.resize(zoom=True)
            self._is_zoomed = True
        except Exception as e:
            _log("zoom error: {}".format(e))

    def unzoom(self) -> None:
        """Unzoom cc-dump pane (restore split). Idempotent."""
        if not self._is_zoomed or self._our_pane is None:
            return
        try:
            self._our_pane.resize(zoom=True)
            self._is_zoomed = False
        except Exception as e:
            _log("unzoom error: {}".format(e))

    def toggle_zoom(self) -> None:
        """Manual zoom toggle."""
        if self._is_zoomed:
            self.unzoom()
        else:
            self.zoom()

    def toggle_auto_zoom(self) -> None:
        """Toggle automatic zoom on API activity."""
        self.auto_zoom = not self.auto_zoom

    def on_event(self, event: PipelineEvent) -> None:
        """Subscriber callback — table lookup determines zoom/unzoom.

        // [LAW:dataflow-not-control-flow] Decision from _ZOOM_DECISIONS table.
        Guards: only act when CLAUDE_RUNNING and auto_zoom is on.
        """
        if self.state != TmuxState.CLAUDE_RUNNING or not self.auto_zoom:
            return

        # Validate pane is still alive before zoom logic
        if not self._validate_claude_pane():
            return

        key = _extract_decision_key(event)
        decision = _ZOOM_DECISIONS.get(key)

        # // [LAW:dataflow-not-control-flow] decision is True/False/None
        # None = no-op, True = zoom, False = unzoom
        _ZOOM_ACTIONS = {
            True: self.zoom,
            False: self.unzoom,
        }
        action = _ZOOM_ACTIONS.get(decision)
        if action is not None:
            action()

    def cleanup(self) -> None:
        """Unzoom on shutdown. Does NOT kill the claude pane."""
        self.unzoom()


def _log(msg: str) -> None:
    """Log to stderr (matches har_recorder.py pattern)."""
    sys.stderr.write("[tmux] {}\n".format(msg))
    sys.stderr.flush()
