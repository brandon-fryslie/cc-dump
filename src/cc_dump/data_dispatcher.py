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
import logging

from cc_dump.checkpoints import (
    CheckpointArtifact,
    CheckpointStore,
    create_checkpoint_artifact,
    render_checkpoint_diff,
)
from cc_dump.decision_ledger import DecisionLedgerStore, parse_decision_entries, DecisionLedgerEntry
from cc_dump.prompt_registry import get_prompt_spec, PromptSpec
from cc_dump.side_channel import SideChannelManager
from cc_dump.side_channel_analytics import SideChannelAnalytics
from cc_dump.summary_cache import SummaryCache

logger = logging.getLogger(__name__)


@dataclass
class EnrichedResult:
    """Result from data enrichment, whether AI or fallback.

    // [LAW:dataflow-not-control-flow] Always present. source indicates origin.
    """

    text: str
    source: str  # "ai" | "cache" | "fallback" | "error"
    elapsed_ms: int


@dataclass
class DecisionLedgerResult:
    entries: list[DecisionLedgerEntry]
    source: str  # "ai" | "fallback" | "error"
    elapsed_ms: int
    error: str = ""


@dataclass
class CheckpointCreateResult:
    artifact: CheckpointArtifact
    source: str  # "ai" | "fallback" | "error"
    elapsed_ms: int
    error: str = ""


class DataDispatcher:
    """Routes enrichment requests to AI or fallback.

    Widgets call methods here and get EnrichedResult back,
    agnostic to whether AI was used. When side-channel is disabled,
    fallback data is returned immediately.
    """

    def __init__(self, side_channel: SideChannelManager, summary_cache: SummaryCache | None = None) -> None:
        self._side_channel = side_channel
        self._analytics = SideChannelAnalytics()
        self._summary_cache = summary_cache if summary_cache is not None else SummaryCache()
        self._decision_ledger = DecisionLedgerStore()
        self._checkpoint_store = CheckpointStore()

    def summarize_messages(self, messages: list[dict], source_session_id: str = "") -> EnrichedResult:
        """Summarize a list of API messages.

        BLOCKING — must be called from a worker thread, never from the TUI thread.

        When side-channel is disabled, returns fallback summary.
        On error, returns error text with fallback appended.
        """
        fallback_text = _fallback_summary(messages)
        fallback = EnrichedResult(
            text=fallback_text,
            source="fallback",
            elapsed_ms=0,
        )

        spec = get_prompt_spec("block_summary")
        context = _build_summary_context(messages)
        cache_key = self._summary_cache.make_key(
            purpose=spec.purpose,
            prompt_version=spec.version,
            content=context,
        )
        cached = self._summary_cache.get(cache_key)
        if cached is not None and cached.summary_text:
            return EnrichedResult(
                text=cached.summary_text,
                source="cache",
                elapsed_ms=0,
            )

        if not self._side_channel.enabled:
            return fallback

        prompt = _build_summary_prompt(context, spec)
        profile = "cache_probe_resume" if source_session_id else "ephemeral_default"
        result = self._side_channel.run(
            prompt=prompt,
            purpose="block_summary",
            prompt_version=spec.version,
            timeout=None,
            source_session_id=source_session_id,
            profile=profile,
        )
        self._analytics.record(purpose=result.purpose)

        if result.error is not None:
            if result.error.startswith("Guardrail:"):
                logger.info("side-channel blocked: %s", result.error)
                return EnrichedResult(
                    text=f"{fallback.text}\n\n[side-channel blocked] {result.error}",
                    source="fallback",
                    elapsed_ms=result.elapsed_ms,
                )
            return EnrichedResult(
                text=f"AI error: {result.error}\n\n---\n\n{fallback.text}",
                source="error",
                elapsed_ms=result.elapsed_ms,
            )
        self._summary_cache.put(
            key=cache_key,
            purpose=spec.purpose,
            prompt_version=spec.version,
            content=context,
            summary_text=result.text,
        )
        return EnrichedResult(
            text=result.text,
            source="ai",
            elapsed_ms=result.elapsed_ms,
        )

    def side_channel_usage_snapshot(self) -> dict[str, dict[str, int]]:
        """Return purpose-level side-channel usage snapshot."""
        return self._analytics.snapshot()

    def extract_decision_ledger(
        self, messages: list[dict], *, source_session_id: str = "", request_id: str = ""
    ) -> DecisionLedgerResult:
        """Extract decision ledger entries from messages."""
        if not self._side_channel.enabled:
            return DecisionLedgerResult(entries=[], source="fallback", elapsed_ms=0, error="side-channel disabled")

        spec = get_prompt_spec("decision_ledger")
        context = _build_summary_context(messages)
        prompt = _build_summary_prompt(context, spec)
        profile = "cache_probe_resume" if source_session_id else "ephemeral_default"
        result = self._side_channel.run(
            prompt=prompt,
            purpose="decision_ledger",
            prompt_version=spec.version,
            timeout=None,
            source_session_id=source_session_id,
            profile=profile,
        )
        if result.error is not None:
            if result.error.startswith("Guardrail:"):
                logger.info("decision ledger blocked: %s", result.error)
                return DecisionLedgerResult(entries=[], source="fallback", elapsed_ms=result.elapsed_ms, error=result.error)
            return DecisionLedgerResult(entries=[], source="error", elapsed_ms=result.elapsed_ms, error=result.error)

        entries = parse_decision_entries(result.text, request_id=request_id)
        merged = self._decision_ledger.upsert_many(entries)
        return DecisionLedgerResult(entries=merged, source="ai", elapsed_ms=result.elapsed_ms)

    def decision_ledger_snapshot(self) -> list[DecisionLedgerEntry]:
        return self._decision_ledger.snapshot()

    def create_checkpoint(
        self,
        messages: list[dict],
        *,
        source_start: int,
        source_end: int,
        source_session_id: str = "",
        request_id: str = "",
    ) -> CheckpointCreateResult:
        """Create checkpoint summary artifact for selected message range."""
        spec = get_prompt_spec("checkpoint_summary")
        normalized_start, normalized_end = _normalize_message_range(
            total_messages=len(messages),
            source_start=source_start,
            source_end=source_end,
        )
        selected_messages = _slice_messages_for_range(messages, normalized_start, normalized_end)
        fallback_text = _fallback_summary(selected_messages)
        profile = "cache_probe_resume" if source_session_id else "ephemeral_default"

        if not self._side_channel.enabled:
            artifact = self._checkpoint_store.add(
                create_checkpoint_artifact(
                    purpose=spec.purpose,
                    prompt_version=spec.version,
                    source_session_id=source_session_id,
                    request_id=request_id,
                    source_start=normalized_start,
                    source_end=normalized_end,
                    summary_text=fallback_text,
                )
            )
            return CheckpointCreateResult(
                artifact=artifact,
                source="fallback",
                elapsed_ms=0,
            )

        context = _build_summary_context(selected_messages)
        prompt = _build_summary_prompt(context, spec)
        result = self._side_channel.run(
            prompt=prompt,
            purpose=spec.purpose,
            prompt_version=spec.version,
            timeout=None,
            source_session_id=source_session_id,
            profile=profile,
        )
        self._analytics.record(purpose=result.purpose)
        summary_text = result.text if result.error is None else fallback_text
        source = "ai" if result.error is None else "error"
        if result.error is not None and result.error.startswith("Guardrail:"):
            logger.info("checkpoint blocked: %s", result.error)
            source = "fallback"
        artifact = self._checkpoint_store.add(
            create_checkpoint_artifact(
                purpose=spec.purpose,
                prompt_version=spec.version,
                source_session_id=source_session_id,
                request_id=request_id,
                source_start=normalized_start,
                source_end=normalized_end,
                summary_text=summary_text,
            )
        )
        return CheckpointCreateResult(
            artifact=artifact,
            source=source,
            elapsed_ms=result.elapsed_ms,
            error=result.error or "",
        )

    def checkpoint_snapshot(self) -> list[CheckpointArtifact]:
        return self._checkpoint_store.snapshot()

    def checkpoint_diff(self, *, before_checkpoint_id: str, after_checkpoint_id: str) -> str:
        before = self._checkpoint_store.get(before_checkpoint_id)
        after = self._checkpoint_store.get(after_checkpoint_id)
        if before is None or after is None:
            missing_ids = [
                checkpoint_id
                for checkpoint_id, artifact in (
                    (before_checkpoint_id, before),
                    (after_checkpoint_id, after),
                )
                if artifact is None
            ]
            return "missing_checkpoints:" + ",".join(missing_ids)
        return render_checkpoint_diff(before=before, after=after)


def _build_summary_context(messages: list[dict]) -> str:
    """Build a stable context string for prompt and cache-key derivation."""
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

    return "\n".join(lines)


def _build_summary_prompt(context: str, spec: PromptSpec) -> str:
    """Build a purpose-scoped prompt from normalized context text."""
    if not context:
        return spec.instruction
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


def _normalize_message_range(*, total_messages: int, source_start: int, source_end: int) -> tuple[int, int]:
    """Normalize inclusive range against available message count."""
    if total_messages <= 0:
        return 0, -1
    lower = max(0, min(source_start, source_end))
    upper = min(total_messages - 1, max(source_start, source_end))
    return lower, upper


def _slice_messages_for_range(messages: list[dict], source_start: int, source_end: int) -> list[dict]:
    """Return selected message range as inclusive slice."""
    if source_end < source_start:
        return []
    return messages[source_start:source_end + 1]
