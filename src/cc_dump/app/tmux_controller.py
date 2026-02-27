"""Tmux integration for cc-dump — split panes, launch external tools, auto-zoom.

This module is STABLE — holds live pane references, never hot-reloaded.
All libtmux usage is lazy-imported and wrapped in try/except.

// [LAW:locality-or-seam] All tmux logic isolated here; rest of app uses is_available() + TmuxController.
// [LAW:dataflow-not-control-flow] Zoom decisions via _ZOOM_DECISIONS lookup table.
"""

from __future__ import annotations

import logging
import os
import shlex
import time
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import libtmux

from snarfx import Observable, watch

from cc_dump.pipeline.event_types import (
    PipelineEvent,
    PipelineEventKind,
    ResponseCompleteEvent,
    StopReason,
)

logger = logging.getLogger(__name__)


class TmuxState(Enum):
    """Controller state machine."""

    NOT_IN_TMUX = auto()
    NO_LIBTMUX = auto()
    READY = auto()
    TOOL_RUNNING = auto()


# ─── Launch result ────────────────────────────────────────────────────────────


class LaunchAction(Enum):
    """What launch_tool decided to do."""

    LAUNCHED = "launched"
    FOCUSED = "focused"
    BLOCKED = "blocked"


class LaunchResult:
    """Result of launch_tool — what happened and why.

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


class LogTailAction(Enum):
    """What open_log_tail decided to do."""

    SPLIT_BELOW = "split_below"
    SPLIT_RIGHT = "split_right"
    NEW_WINDOW = "new_window"
    BLOCKED = "blocked"


class LogTailResult:
    """Result of open_log_tail — what happened and why.

    // [LAW:dataflow-not-control-flow] Pane-routing choice is represented as a value.
    """

    __slots__ = ("action", "detail", "success", "command")

    def __init__(self, action: LogTailAction, detail: str, success: bool, command: str = ""):
        self.action = action
        self.detail = detail
        self.success = success
        self.command = command

    def __repr__(self) -> str:
        parts = "action={}, detail={!r}, success={}".format(
            self.action.value, self.detail, self.success
        )
        if self.command:
            parts += ", command={!r}".format(self.command)
        return "LogTailResult({})".format(parts)


# ─── Zoom decision table ─────────────────────────────────────────────────────
# Key: (PipelineEventKind, StopReason | None)
# Value: True = zoom, False = unzoom, None = no-op
# // [LAW:dataflow-not-control-flow] Table lookup, not if/elif chains.

_ZOOM_DECISIONS: dict[tuple[PipelineEventKind, StopReason | None], bool | None] = {
    (PipelineEventKind.REQUEST, None): True,
    (PipelineEventKind.RESPONSE_COMPLETE, StopReason.END_TURN): False,
    (PipelineEventKind.RESPONSE_COMPLETE, StopReason.MAX_TOKENS): False,
    (PipelineEventKind.RESPONSE_COMPLETE, StopReason.TOOL_USE): None,
    (PipelineEventKind.ERROR, None): False,
    (PipelineEventKind.PROXY_ERROR, None): False,
}


def _extract_decision_key(
    event: PipelineEvent,
) -> tuple[PipelineEventKind, StopReason | None]:
    """Extract the lookup key from a pipeline event.

    For ResponseCompleteEvent, extract stop_reason from body dict.
    For all other events, stop_reason is None.
    """
    stop_reason: StopReason | None = None
    if isinstance(event, ResponseCompleteEvent):
        sr_str = event.body.get("stop_reason", "") or ""
        try:
            stop_reason = StopReason(sr_str)
        except ValueError:
            stop_reason = StopReason.NONE
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
    """Manages tmux pane splitting, zoom, and tool-launch lifecycle.

    // [LAW:single-enforcer] on_event() is the sole zoom decision point.
    // [LAW:single-enforcer] _validate_tool_pane() is the sole pane liveness check.
    """

    def __init__(
        self,
        launch_command: str = "claude",
        process_names: tuple[str, ...] = (),
        launch_env: dict[str, str] | None = None,
        launcher_label: str = "tool",
        auto_zoom: bool = False,
    ) -> None:
        self.state = TmuxState.NOT_IN_TMUX
        self.auto_zoom = auto_zoom
        self._is_zoomed = False
        self._port: int | None = None  # legacy fallback path
        self._launch_command = ""
        self._process_names: tuple[str, ...] = ()
        self._launch_env: dict[str, str] = {}
        self._launcher_label = launcher_label
        self._server: libtmux.Server | None = None
        self._session: libtmux.Session | None = None
        self._our_pane: libtmux.Pane | None = None
        self._tool_pane: libtmux.Pane | None = None
        self.pane_alive = Observable(False)  # reactive — True while launched pane is alive
        self.configure_launcher(
            command=launch_command,
            process_names=process_names,
            launch_env=launch_env or {},
            launcher_label=launcher_label,
        )

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
        """Set legacy proxy port fallback (used when launch_env is empty)."""
        self._port = port

    def configure_launcher(
        self,
        command: str,
        process_names: tuple[str, ...] = (),
        launch_env: dict[str, str] | None = None,
        launcher_label: str = "tool",
    ) -> None:
        """Set launcher command identity + environment.

        // [LAW:one-source-of-truth] Launcher identity and env are configured here,
        // then consumed by launch/adoption/tail logic.
        """
        normalized_command = str(command or "").strip() or "claude"
        try:
            tokenized = shlex.split(normalized_command)
        except ValueError:
            tokenized = [normalized_command]
        primary_name = os.path.basename(tokenized[0]) if tokenized else ""
        names = [primary_name, *process_names]
        deduped = tuple(dict.fromkeys(name for name in names if name))

        self._launch_command = normalized_command
        self._process_names = deduped
        self._launch_env = dict(launch_env or {})
        self._launcher_label = str(launcher_label or "").strip() or "tool"

    def set_launch_command(self, command: str) -> None:
        """Update the launcher command while preserving env/matchers."""
        self.configure_launcher(
            command=command,
            process_names=self._process_names,
            launch_env=self._launch_env,
            launcher_label=self._launcher_label,
        )

    def set_launch_env(self, launch_env: dict[str, str]) -> None:
        """Update launch environment while preserving command/matchers."""
        self.configure_launcher(
            command=self._launch_command,
            process_names=self._process_names,
            launch_env=launch_env,
            launcher_label=self._launcher_label,
        )

    def set_process_names(self, process_names: tuple[str, ...]) -> None:
        """Update pane-adoption matchers while preserving command/env."""
        self.configure_launcher(
            command=self._launch_command,
            process_names=process_names,
            launch_env=self._launch_env,
            launcher_label=self._launcher_label,
        )

    def _validate_tool_pane(self) -> bool:
        """// [LAW:single-enforcer] Sole pane liveness check.

        Returns True if launched pane is alive, False if dead/absent.
        On dead pane: clears reference and transitions to READY.
        """
        if self._tool_pane is None:
            return False
        try:
            # libtmux refresh fetches fresh state from tmux server
            self._tool_pane.refresh()
            return True
        except Exception:
            self._tool_pane = None
            self.state = TmuxState.READY
            return False

    def _find_tool_pane(self) -> "libtmux.Pane | None":
        """Scan sibling panes for a running configured tool process."""
        if self._our_pane is None:
            return None
        try:
            targets = set(self._process_names)
            if not targets:
                return None
            window = self._our_pane.window
            for pane in window.panes:
                if pane.pane_id == self._our_pane.pane_id:
                    continue
                current_cmd = getattr(pane, "pane_current_command", None) or ""
                if os.path.basename(current_cmd) in targets:
                    return pane
        except Exception as e:
            _log("_find_tool_pane error: {}".format(e))
        return None

    def _try_adopt_existing(self) -> None:
        """Adopt an existing tool pane if found. Transitions to TOOL_RUNNING."""
        found = self._find_tool_pane()
        if found is not None:
            self._tool_pane = found
            self.state = TmuxState.TOOL_RUNNING

    @property
    def launch_command(self) -> str:
        """The base launcher command."""
        return self._launch_command

    def launch_tool(self, command: str = "") -> LaunchResult:
        """Evaluate preconditions, derive action, log, execute.

        Args:
            command: Full command to run.
                     If empty, falls back to self._launch_command.

        // [LAW:dataflow-not-control-flow] All preconditions evaluated unconditionally.
        // Action is a value derived from the preconditions, not hidden in branches.
        """
        resolved_command = command or self._launch_command

        # ── Evaluate all preconditions unconditionally ──
        state_ok = self.state in (TmuxState.READY, TmuxState.TOOL_RUNNING)
        pane_alive = self._validate_tool_pane() if self._tool_pane is not None else False
        if not pane_alive:
            self._try_adopt_existing()
            pane_alive = self._tool_pane is not None

        has_launch_env = bool(self._launch_env)
        has_port_fallback = self._port is not None
        launch_target_ok = has_launch_env or has_port_fallback

        # ── Derive action from preconditions ──
        action: LaunchAction
        detail: str
        if not state_ok:
            action, detail = LaunchAction.BLOCKED, "state={}".format(self.state)
        elif pane_alive:
            pane_id = getattr(self._tool_pane, "pane_id", "?")
            action, detail = LaunchAction.FOCUSED, "existing pane {}".format(pane_id)
        elif not launch_target_ok:
            action, detail = LaunchAction.BLOCKED, "launch env not configured"
        else:
            action, detail = LaunchAction.LAUNCHED, resolved_command

        _log("launch_tool: {} ({})".format(action.value, detail))

        # ── Execute ──
        if action == LaunchAction.FOCUSED:
            ok = self.focus_tool()
            return LaunchResult(action, detail, ok)

        if action == LaunchAction.LAUNCHED:
            return self._exec_launch(resolved_command)

        return LaunchResult(action, detail, success=False)

    def _resolve_tail_split_direction(self, pane_a: "libtmux.Pane", pane_b: "libtmux.Pane"):
        """Pick opposite split direction from a 2-pane layout.

        // [LAW:dataflow-not-control-flow] Direction derives from pane coordinates.
        """
        import libtmux

        a_left = int(getattr(pane_a, "pane_left", 0) or 0)
        a_top = int(getattr(pane_a, "pane_top", 0) or 0)
        b_left = int(getattr(pane_b, "pane_left", 0) or 0)
        b_top = int(getattr(pane_b, "pane_top", 0) or 0)

        is_top_bottom_split = (a_left == b_left) and (a_top != b_top)
        return (
            libtmux.constants.PaneDirection.Right
            if is_top_bottom_split
            else libtmux.constants.PaneDirection.Below
        )

    def _resolve_tool_for_tail(self) -> "libtmux.Pane | None":
        """Return a live tool pane when one exists in our window."""
        pane_alive = self._validate_tool_pane() if self._tool_pane is not None else False
        if not pane_alive:
            self._try_adopt_existing()
        return self._tool_pane

    def open_log_tail(self, log_file: str) -> LogTailResult:
        """Open a tmux pane/window running `tail -f` for the runtime logfile.

        Routing policy:
        1. cc-dump alone in window -> split below (horizontal).
        2. cc-dump + launched tool only -> split tool pane in opposite orientation.
        3. Any other layout -> create and switch to a new tmux window.
        """
        state_ok = self.state in (TmuxState.READY, TmuxState.TOOL_RUNNING)
        has_our_pane = self._our_pane is not None
        has_session = self._session is not None
        has_log_file = bool(str(log_file or "").strip())
        blocked_reasons = []
        blocked_reasons.extend(["state={}".format(self.state)] if not state_ok else [])
        blocked_reasons.extend(["our pane missing"] if not has_our_pane else [])
        blocked_reasons.extend(["session missing"] if not has_session else [])
        blocked_reasons.extend(["log_file missing"] if not has_log_file else [])
        if blocked_reasons:
            detail = ", ".join(blocked_reasons)
            _log("open_log_tail blocked: {}".format(detail))
            return LogTailResult(LogTailAction.BLOCKED, detail, success=False)

        shell = "tail -f -- {}".format(shlex.quote(log_file))
        try:
            import libtmux

            window = self._our_pane.window
            panes = list(window.panes)
            pane_count = len(panes)
            tool_pane = self._resolve_tool_for_tail()
            is_tool_pair = (
                pane_count == 2
                and tool_pane is not None
                and self._our_pane.pane_id != tool_pane.pane_id
            )

            # // [LAW:dataflow-not-control-flow] Strategy is a derived value from pane_count/is_tool_pair.
            if pane_count == 1:
                window.split(direction=libtmux.constants.PaneDirection.Below, shell=shell)
                return LogTailResult(LogTailAction.SPLIT_BELOW, "split cc-dump pane", True, shell)

            if is_tool_pair:
                direction = self._resolve_tail_split_direction(self._our_pane, tool_pane)
                tool_pane.select()
                window.split(direction=direction, shell=shell)
                action = (
                    LogTailAction.SPLIT_RIGHT
                    if direction == libtmux.constants.PaneDirection.Right
                    else LogTailAction.SPLIT_BELOW
                )
                detail = "split {} pane".format(getattr(tool_pane, "pane_id", self._launcher_label))
                return LogTailResult(action, detail, True, shell)

            self._session.cmd("new-window", "-n", "cc-dump-logs", shell)
            return LogTailResult(LogTailAction.NEW_WINDOW, "opened cc-dump-logs window", True, shell)
        except Exception as e:
            _log("open_log_tail error: {}".format(e))
            return LogTailResult(LogTailAction.BLOCKED, str(e), success=False, command=shell)

    def _resolved_launch_env(self) -> dict[str, str]:
        """Return launch env from configured map or legacy port fallback."""
        if self._launch_env:
            return dict(self._launch_env)
        if self._port is None:
            return {}
        return {"ANTHROPIC_BASE_URL": "http://127.0.0.1:{}".format(self._port)}

    def _exec_launch(self, command: str) -> LaunchResult:
        """Split pane and run command with configured launch environment."""
        try:
            import libtmux

            window = self._our_pane.window
            env = self._resolved_launch_env()
            env_prefix = " ".join(
                "{}={}".format(key, shlex.quote(value))
                for key, value in sorted(env.items())
            )
            shell = "{} {}".format(env_prefix, command).strip()
            _log("exec: {}".format(shell))
            self._tool_pane = window.split(
                direction=libtmux.constants.PaneDirection.Below,
                shell=shell,
            )
            self._tool_pane.select()
            self.state = TmuxState.TOOL_RUNNING
            self._monitor_exit()
            return LaunchResult(LaunchAction.LAUNCHED, command, success=True, command=shell)
        except Exception as e:
            _log("launch error: {}".format(e))
            return LaunchResult(LaunchAction.BLOCKED, str(e), success=False)

    def _monitor_exit(self) -> None:
        """Start watching for launched pane exit.

        // [LAW:single-enforcer] Exit monitoring owned by the controller,
        // not the app. Callers react to pane_alive observable.
        """
        self.pane_alive.set(True)

        def _poll():
            while self._validate_tool_pane():
                time.sleep(2)
            self.pane_alive.set(False)

        watch(_poll)

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

    def focus_tool(self) -> bool:
        """Select the launched pane (bring it to foreground)."""
        if not self._validate_tool_pane():
            return False
        try:
            self._tool_pane.select()
            return True
        except Exception as e:
            _log("focus_tool error: {}".format(e))
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
        Guards: only act when TOOL_RUNNING and auto_zoom is on.
        """
        if self.state != TmuxState.TOOL_RUNNING or not self.auto_zoom:
            return

        # Validate pane is still alive before zoom logic
        if not self._validate_tool_pane():
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
        """Unzoom on shutdown. Does NOT kill the launched pane."""
        self.unzoom()


def _log(msg: str) -> None:
    """Emit tmux diagnostics through the centralized logger."""
    logger.info("[tmux] %s", msg)
