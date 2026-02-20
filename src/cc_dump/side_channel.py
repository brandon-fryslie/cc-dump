"""Side-channel manager — spawns `claude -p` for AI-powered enrichment.

This module is a STABLE BOUNDARY — not hot-reloadable.
Holds live subprocess references.
Import as: import cc_dump.side_channel

// [LAW:single-enforcer] SideChannelManager is the sole subprocess owner
// for side-channel AI queries.
// [LAW:locality-or-seam] All subprocess logic isolated here.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass


@dataclass
class SideChannelResult:
    """Result from a side-channel query.

    // [LAW:dataflow-not-control-flow] Always present; .error indicates failure mode.
    """

    text: str  # response text, or ""
    error: str | None  # error message, or None for success
    elapsed_ms: int  # wall-clock time in milliseconds


class SideChannelManager:
    """Manages claude -p subprocess lifecycle for AI enrichment.

    // [LAW:single-enforcer] Sole owner of side-channel subprocesses.
    // [LAW:dataflow-not-control-flow] query() always returns SideChannelResult;
    //   caller decides what to do with .error, not whether to call.
    """

    def __init__(self, claude_command: str = "claude") -> None:
        self._claude_command = claude_command
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def set_claude_command(self, cmd: str) -> None:
        """Update the claude command (e.g., from settings change)."""
        self._claude_command = cmd

    def query(self, prompt: str, timeout: int = 60) -> SideChannelResult:
        """Run a synchronous query against claude -p.

        BLOCKING — must be called from a worker thread, never from the TUI thread.

        Spawns a fresh subprocess per call (MVP). The interface supports
        future optimization to a persistent instance without API change.
        """
        start = time.monotonic()
        cmd = [
            self._claude_command,
            "-p",
            "--model",
            "haiku",
            "--allowedTools",
            "",
        ]
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            elapsed = int((time.monotonic() - start) * 1000)
            if result.returncode != 0:
                stderr_snippet = result.stderr[:500] if result.stderr else "(no stderr)"
                return SideChannelResult(
                    text="",
                    error=f"Exit code {result.returncode}: {stderr_snippet}",
                    elapsed_ms=elapsed,
                )
            return SideChannelResult(
                text=result.stdout.strip(),
                error=None,
                elapsed_ms=elapsed,
            )
        except subprocess.TimeoutExpired:
            elapsed = int((time.monotonic() - start) * 1000)
            return SideChannelResult(
                text="",
                error=f"Timeout ({timeout}s)",
                elapsed_ms=elapsed,
            )
        except FileNotFoundError:
            elapsed = int((time.monotonic() - start) * 1000)
            return SideChannelResult(
                text="",
                error=f"Command not found: {self._claude_command}",
                elapsed_ms=elapsed,
            )
