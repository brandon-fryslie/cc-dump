"""Side-channel manager — spawns `claude -p` for AI-powered enrichment.

This module is a STABLE BOUNDARY — not hot-reloadable.
Holds live subprocess references.
Import as: import cc_dump.side_channel

// [LAW:single-enforcer] SideChannelManager is the sole subprocess owner
// for side-channel AI queries.
// [LAW:locality-or-seam] All subprocess logic isolated here.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass

from cc_dump.side_channel_marker import SideChannelMarker, prepend_marker
from cc_dump.side_channel_purpose import normalize_purpose


@dataclass
class SideChannelResult:
    """Result from a side-channel query.

    // [LAW:dataflow-not-control-flow] Always present; .error indicates failure mode.
    """

    text: str  # response text, or ""
    error: str | None  # error message, or None for success
    elapsed_ms: int  # wall-clock time in milliseconds
    run_id: str = ""
    purpose: str = "block_summary"
    prompt_version: str = "v1"
    profile: str = "ephemeral_default"


class SideChannelManager:
    """Manages claude -p subprocess lifecycle for AI enrichment.

    // [LAW:single-enforcer] Sole owner of side-channel subprocesses.
    // [LAW:dataflow-not-control-flow] query() always returns SideChannelResult;
    //   caller decides what to do with .error, not whether to call.
    """

    def __init__(self, claude_command: str = "claude") -> None:
        self._claude_command = claude_command
        self._enabled = True
        self._global_kill = False
        self._base_url: str = ""
        self._run_slots = threading.Semaphore(1)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def set_claude_command(self, cmd: str) -> None:
        """Update the claude command (e.g., from settings change)."""
        self._claude_command = cmd

    def set_base_url(self, url: str) -> None:
        """Set ANTHROPIC_BASE_URL used for subprocess requests."""
        self._base_url = url

    def set_max_concurrent(self, value: int) -> None:
        """Set max concurrent side-channel subprocesses (placeholder control)."""
        max_runs = max(1, int(value))
        self._run_slots = threading.Semaphore(max_runs)

    @property
    def global_kill(self) -> bool:
        return self._global_kill

    @global_kill.setter
    def global_kill(self, value: bool) -> None:
        self._global_kill = bool(value)

    def query(self, prompt: str, timeout: int = 60) -> SideChannelResult:
        """Compatibility helper for existing callsites."""
        return self.run(
            prompt=prompt,
            purpose="block_summary",
            timeout=timeout,
            source_session_id="",
            profile="ephemeral_default",
            prompt_version="v1",
        )

    def run(
        self,
        *,
        prompt: str,
        purpose: str,
        timeout: int = 60,
        source_session_id: str = "",
        profile: str = "ephemeral_default",
        prompt_version: str = "v1",
    ) -> SideChannelResult:
        """Run a synchronous query against claude -p.

        BLOCKING — must be called from a worker thread, never from the TUI thread.

        Spawns a fresh subprocess per call (MVP). The interface supports
        future optimization to a persistent instance without API change.
        """
        start = time.monotonic()
        run_id = uuid.uuid4().hex
        normalized_purpose = normalize_purpose(purpose)
        if self._global_kill:
            return SideChannelResult(
                text="",
                error="Blocked by global side-channel kill switch",
                elapsed_ms=0,
                run_id=run_id,
                purpose=normalized_purpose,
                prompt_version=prompt_version,
                profile=profile,
            )
        if not self._enabled:
            return SideChannelResult(
                text="",
                error="Side-channel disabled",
                elapsed_ms=0,
                run_id=run_id,
                purpose=normalized_purpose,
                prompt_version=prompt_version,
                profile=profile,
            )

        cmd = _build_cmd(
            claude_command=self._claude_command,
            profile=profile,
            source_session_id=source_session_id,
        )
        tagged_prompt = prepend_marker(
            prompt,
            SideChannelMarker(
                run_id=run_id,
                purpose=normalized_purpose,
                source_session_id=source_session_id,
                prompt_version=prompt_version,
            ),
        )
        env = os.environ.copy()
        if self._base_url:
            env["ANTHROPIC_BASE_URL"] = self._base_url
        try:
            self._run_slots.acquire()
            result = subprocess.run(
                cmd,
                input=tagged_prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            elapsed = int((time.monotonic() - start) * 1000)
            if result.returncode != 0:
                stderr_snippet = result.stderr[:500] if result.stderr else "(no stderr)"
                return SideChannelResult(
                    text="",
                    error=f"Exit code {result.returncode}: {stderr_snippet}",
                    elapsed_ms=elapsed,
                    run_id=run_id,
                    purpose=normalized_purpose,
                    prompt_version=prompt_version,
                    profile=profile,
                )
            return SideChannelResult(
                text=result.stdout.strip(),
                error=None,
                elapsed_ms=elapsed,
                run_id=run_id,
                purpose=normalized_purpose,
                prompt_version=prompt_version,
                profile=profile,
            )
        except subprocess.TimeoutExpired:
            elapsed = int((time.monotonic() - start) * 1000)
            return SideChannelResult(
                text="",
                error=f"Timeout ({timeout}s)",
                elapsed_ms=elapsed,
                run_id=run_id,
                purpose=normalized_purpose,
                prompt_version=prompt_version,
                profile=profile,
            )
        except FileNotFoundError:
            elapsed = int((time.monotonic() - start) * 1000)
            return SideChannelResult(
                text="",
                error=f"Command not found: {self._claude_command}",
                elapsed_ms=elapsed,
                run_id=run_id,
                purpose=normalized_purpose,
                prompt_version=prompt_version,
                profile=profile,
            )
        finally:
            try:
                self._run_slots.release()
            except ValueError:
                # Release can fail only if acquisition didn't happen.
                pass


def _build_cmd(
    *,
    claude_command: str,
    profile: str,
    source_session_id: str,
) -> list[str]:
    cmd = [
        claude_command,
        "-p",
        "--model",
        "haiku",
        "--tools",
        "",
    ]

    if profile == "cache_probe_resume" and source_session_id:
        return cmd + ["--resume", source_session_id, "--fork-session"]
    if profile == "isolated_fixed_id":
        return cmd + ["--session-id", str(uuid.uuid4()), "--no-session-persistence"]
    return cmd + ["--no-session-persistence"]
