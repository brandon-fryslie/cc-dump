"""Data dispatcher — routes enrichment requests to AI or fallback.

This module is a STABLE BOUNDARY — not hot-reloadable.
Holds reference to SideChannelManager.
Import as: import cc_dump.data_dispatcher

// [LAW:single-enforcer] Sole decision point for AI vs fallback routing.
// [LAW:dataflow-not-control-flow] Always returns EnrichedResult;
//   source field indicates origin, not branching at the caller.
"""

from __future__ import annotations

from dataclasses import dataclass

from cc_dump.prompt_registry import get_prompt_spec, PromptSpec
from cc_dump.side_channel import SideChannelManager
from cc_dump.side_channel_analytics import SideChannelAnalytics


@dataclass
class EnrichedResult:
    """Result from data enrichment, whether AI or fallback.

    // [LAW:dataflow-not-control-flow] Always present. source indicates origin.
    """

    text: str
    source: str  # "ai" | "fallback" | "error"
    elapsed_ms: int


class DataDispatcher:
    """Routes enrichment requests to AI or fallback.

    Widgets call methods here and get EnrichedResult back,
    agnostic to whether AI was used. When side-channel is disabled,
    fallback data is returned immediately.
    """

    def __init__(self, side_channel: SideChannelManager) -> None:
        self._side_channel = side_channel
        self._analytics = SideChannelAnalytics()

    def summarize_messages(self, messages: list[dict], source_session_id: str = "") -> EnrichedResult:
        """Summarize a list of API messages.

        BLOCKING — must be called from a worker thread, never from the TUI thread.

        When side-channel is disabled, returns fallback summary.
        On error, returns error text with fallback appended.
        """
        fallback = EnrichedResult(
            text=_fallback_summary(messages),
            source="fallback",
            elapsed_ms=0,
        )

        if not self._side_channel.enabled:
            return fallback

        spec = get_prompt_spec("block_summary")
        prompt = _build_summary_prompt(messages, spec)
        profile = "cache_probe_resume" if source_session_id else "ephemeral_default"
        result = self._side_channel.run(
            prompt=prompt,
            purpose="block_summary",
            prompt_version=spec.version,
            timeout=60,
            source_session_id=source_session_id,
            profile=profile,
        )
        self._analytics.record(purpose=result.purpose)

        if result.error is not None:
            return EnrichedResult(
                text=f"AI error: {result.error}\n\n---\n\n{fallback.text}",
                source="error",
                elapsed_ms=result.elapsed_ms,
            )
        return EnrichedResult(
            text=result.text,
            source="ai",
            elapsed_ms=result.elapsed_ms,
        )

    def side_channel_usage_snapshot(self) -> dict[str, dict[str, int]]:
        """Return purpose-level side-channel usage snapshot."""
        return self._analytics.snapshot()


def _build_summary_prompt(messages: list[dict], spec: PromptSpec) -> str:
    """Build a purpose-scoped prompt from conversation messages."""
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            # Extract text from content blocks
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            content = " ".join(parts)
        # Truncate individual messages to keep prompt reasonable
        if len(content) > 500:
            content = content[:500] + "..."
        lines.append(f"[{role}]: {content}")

    context = "\n".join(lines)
    return (
        f"{spec.instruction}\n\n"
        f"{context}"
    )


def _fallback_summary(messages: list[dict]) -> str:
    """Non-AI summary: message count and role breakdown."""
    if not messages:
        return "No messages to summarize."
    roles: dict[str, int] = {}
    for msg in messages:
        role = msg.get("role", "unknown")
        roles[role] = roles.get(role, 0) + 1
    parts = [f"{count} {role}" for role, count in sorted(roles.items())]
    return f"{len(messages)} messages ({', '.join(parts)})"
