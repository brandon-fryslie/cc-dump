"""Data dispatcher — routes enrichment requests to AI or fallback.

This module is a STABLE BOUNDARY — not hot-reloadable.
Holds reference to SideChannelManager.
Import as: import cc_dump.ai.data_dispatcher

// [LAW:single-enforcer] Sole decision point for AI vs fallback routing.
// [LAW:dataflow-not-control-flow] Always returns EnrichedResult;
//   source field indicates origin, not branching at the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from collections.abc import Callable

from cc_dump.ai.action_items import ActionItemStore, ActionWorkItem, parse_action_items
from cc_dump.ai.action_items_beads import create_beads_issue_for_item
from cc_dump.ai.checkpoints import (
    CheckpointArtifact,
    CheckpointStore,
    create_checkpoint_artifact,
    render_checkpoint_diff,
)
from cc_dump.ai.conversation_qa import (
    QAArtifact,
    QABudgetEstimate,
    QAScope,
    estimate_qa_budget,
    fallback_qa_artifact,
    normalize_scope,
    parse_qa_artifact,
    render_qa_markdown,
    select_messages,
)
from cc_dump.ai.handoff_notes import (
    HandoffArtifact,
    HandoffStore,
    fallback_handoff_artifact,
    parse_handoff_artifact,
    render_handoff_markdown,
)
from cc_dump.ai.incident_timeline import (
    IncidentTimelineArtifact,
    IncidentTimelineStore,
    fallback_incident_timeline_artifact,
    parse_incident_timeline_artifact,
    render_incident_timeline_markdown,
)
from cc_dump.ai.release_notes import (
    ReleaseNotesArtifact,
    ReleaseNotesStore,
    fallback_release_notes_artifact,
    parse_release_notes_artifact,
    render_release_notes_markdown,
)
from cc_dump.ai.prompt_registry import get_prompt_spec, PromptSpec, UTILITY_CUSTOM_PURPOSE
from cc_dump.ai.side_channel import SideChannelManager
from cc_dump.ai.side_channel_analytics import SideChannelAnalytics
from cc_dump.ai.summary_cache import SummaryCache
from cc_dump.ai.utility_catalog import UtilityRegistry, UtilitySpec, fallback_utility_output, utility_prompt

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
class CheckpointCreateResult:
    artifact: CheckpointArtifact
    source: str  # "ai" | "fallback" | "error"
    elapsed_ms: int
    error: str = ""


@dataclass
class ActionExtractionResult:
    batch_id: str
    items: list[ActionWorkItem]
    source: str  # "ai" | "fallback" | "error"
    elapsed_ms: int
    error: str = ""


@dataclass
class HandoffResult:
    artifact: HandoffArtifact
    markdown: str
    source: str  # "ai" | "fallback" | "error"
    elapsed_ms: int
    error: str = ""


@dataclass
class IncidentTimelineResult:
    artifact: IncidentTimelineArtifact
    markdown: str
    source: str  # "ai" | "fallback" | "error"
    elapsed_ms: int
    error: str = ""


@dataclass
class ConversationQAResult:
    artifact: QAArtifact
    markdown: str
    source: str  # "ai" | "fallback" | "error"
    elapsed_ms: int
    estimate: QABudgetEstimate
    error: str = ""


@dataclass
class ReleaseNotesResult:
    artifact: ReleaseNotesArtifact
    markdown: str
    source: str  # "ai" | "fallback" | "error"
    elapsed_ms: int
    variant: str
    error: str = ""


@dataclass
class UtilityResult:
    utility_id: str
    text: str
    source: str  # "ai" | "fallback" | "error"
    elapsed_ms: int
    error: str = ""


@dataclass(frozen=True)
class PreparedPrompt:
    """Resolved prompt payload for preview/edit/send workflows."""

    prompt: str
    purpose: str
    prompt_version: str
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
        self._checkpoint_store = CheckpointStore()
        self._action_items = ActionItemStore()
        self._handoff_store = HandoffStore()
        self._incident_timeline_store = IncidentTimelineStore()
        self._release_notes_store = ReleaseNotesStore()
        self._utility_registry = UtilityRegistry()

    def summarize_messages(
        self,
        messages: list[dict],
        source_session_id: str = "",
        prompt_override: str | None = None,
    ) -> EnrichedResult:
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

        prepared = self.prepare_summary_prompt(messages)
        context = _build_summary_context(messages)
        cache_key = self._summary_cache.make_key(
            purpose=prepared.purpose,
            prompt_version=prepared.prompt_version,
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

        prompt = _resolve_prompt_override(prepared.prompt, prompt_override)
        profile = "cache_probe_resume" if source_session_id else "ephemeral_default"
        result = self._side_channel.run(
            prompt=prompt,
            purpose=prepared.purpose,
            prompt_version=prepared.prompt_version,
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
            purpose=prepared.purpose,
            prompt_version=prepared.prompt_version,
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

    def extract_action_items(
        self,
        messages: list[dict],
        *,
        source_session_id: str = "",
        request_id: str = "",
        prompt_override: str | None = None,
    ) -> ActionExtractionResult:
        """Extract action/deferred candidates and stage them for explicit review."""
        if not self._side_channel.enabled:
            batch_id = self._action_items.stage([])
            return ActionExtractionResult(
                batch_id=batch_id,
                items=[],
                source="fallback",
                elapsed_ms=0,
                error="side-channel disabled",
            )

        prepared = self.prepare_action_extraction_prompt(messages)
        prompt = _resolve_prompt_override(prepared.prompt, prompt_override)
        profile = "cache_probe_resume" if source_session_id else "ephemeral_default"
        result = self._side_channel.run(
            prompt=prompt,
            purpose=prepared.purpose,
            prompt_version=prepared.prompt_version,
            timeout=None,
            source_session_id=source_session_id,
            profile=profile,
        )
        self._analytics.record(purpose=result.purpose)
        if result.error is not None:
            source = "error"
            if result.error.startswith("Guardrail:"):
                logger.info("action extraction blocked: %s", result.error)
                source = "fallback"
            batch_id = self._action_items.stage([])
            return ActionExtractionResult(
                batch_id=batch_id,
                items=[],
                source=source,
                elapsed_ms=result.elapsed_ms,
                error=result.error,
            )
        extracted = parse_action_items(result.text, request_id=request_id)
        batch_id = self._action_items.stage(extracted)
        return ActionExtractionResult(
            batch_id=batch_id,
            items=extracted,
            source="ai",
            elapsed_ms=result.elapsed_ms,
        )

    def pending_action_items(self, batch_id: str) -> list[ActionWorkItem]:
        return self._action_items.pending(batch_id)

    def accept_action_items(
        self,
        *,
        batch_id: str,
        item_ids: list[str],
        create_beads: bool = False,
        beads_hook: Callable[[ActionWorkItem], str] | None = None,
    ) -> list[ActionWorkItem]:
        """Persist accepted action/deferred items, optionally linking beads issues."""
        # [LAW:single-enforcer] create_beads gate is enforced only here.
        resolved_beads_hook = None
        if create_beads:
            resolved_beads_hook = beads_hook if beads_hook is not None else create_beads_issue_for_item
        return self._action_items.accept(
            batch_id=batch_id,
            item_ids=item_ids,
            beads_hook=resolved_beads_hook,
        )

    def accepted_action_items_snapshot(self) -> list[ActionWorkItem]:
        return self._action_items.accepted_snapshot()

    def generate_handoff_note(
        self,
        messages: list[dict],
        *,
        source_start: int,
        source_end: int,
        source_session_id: str = "",
        request_id: str = "",
    ) -> HandoffResult:
        """Generate structured handoff artifact for selected scope."""
        spec = get_prompt_spec("handoff_note")
        normalized_start, normalized_end = _normalize_message_range(
            total_messages=len(messages),
            source_start=source_start,
            source_end=source_end,
        )
        selected_messages = _slice_messages_for_range(messages, normalized_start, normalized_end)
        fallback_artifact = fallback_handoff_artifact(
            purpose=spec.purpose,
            prompt_version=spec.version,
            source_session_id=source_session_id,
            request_id=request_id,
            source_start=normalized_start,
            source_end=normalized_end,
            summary_text=_fallback_summary(selected_messages),
        )
        profile = "cache_probe_resume" if source_session_id else "ephemeral_default"

        if not self._side_channel.enabled:
            artifact = self._handoff_store.add(fallback_artifact)
            return HandoffResult(
                artifact=artifact,
                markdown=render_handoff_markdown(artifact),
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
        if result.error is not None:
            source = "error"
            if result.error.startswith("Guardrail:"):
                logger.info("handoff blocked: %s", result.error)
                source = "fallback"
            artifact = self._handoff_store.add(fallback_artifact)
            return HandoffResult(
                artifact=artifact,
                markdown=render_handoff_markdown(artifact),
                source=source,
                elapsed_ms=result.elapsed_ms,
                error=result.error,
            )

        artifact = self._handoff_store.add(
            parse_handoff_artifact(
                result.text,
                purpose=spec.purpose,
                prompt_version=spec.version,
                source_session_id=source_session_id,
                request_id=request_id,
                source_start=normalized_start,
                source_end=normalized_end,
            )
        )
        return HandoffResult(
            artifact=artifact,
            markdown=render_handoff_markdown(artifact),
            source="ai",
            elapsed_ms=result.elapsed_ms,
        )

    def latest_handoff_note(self, source_session_id: str = "") -> HandoffArtifact | None:
        return self._handoff_store.latest(source_session_id=source_session_id)

    def handoff_note_snapshot(self) -> list[HandoffArtifact]:
        return self._handoff_store.snapshot()

    def generate_incident_timeline(
        self,
        messages: list[dict],
        *,
        source_start: int,
        source_end: int,
        source_session_id: str = "",
        request_id: str = "",
        include_hypotheses: bool = False,
    ) -> IncidentTimelineResult:
        """Generate incident/debug timeline artifact for selected scope."""
        spec = get_prompt_spec("incident_timeline")
        normalized_start, normalized_end = _normalize_message_range(
            total_messages=len(messages),
            source_start=source_start,
            source_end=source_end,
        )
        selected_messages = _slice_messages_for_range(messages, normalized_start, normalized_end)
        fallback_artifact = fallback_incident_timeline_artifact(
            purpose=spec.purpose,
            prompt_version=spec.version,
            source_session_id=source_session_id,
            request_id=request_id,
            source_start=normalized_start,
            source_end=normalized_end,
            summary_text=_fallback_summary(selected_messages),
            include_hypotheses=include_hypotheses,
        )
        profile = "cache_probe_resume" if source_session_id else "ephemeral_default"

        if not self._side_channel.enabled:
            artifact = self._incident_timeline_store.add(fallback_artifact)
            return IncidentTimelineResult(
                artifact=artifact,
                markdown=render_incident_timeline_markdown(artifact, include_hypotheses=include_hypotheses),
                source="fallback",
                elapsed_ms=0,
            )

        context = _build_summary_context(selected_messages)
        prompt = _build_incident_timeline_prompt(
            context=context,
            spec=spec,
            include_hypotheses=include_hypotheses,
        )
        result = self._side_channel.run(
            prompt=prompt,
            purpose=spec.purpose,
            prompt_version=spec.version,
            timeout=None,
            source_session_id=source_session_id,
            profile=profile,
        )
        self._analytics.record(purpose=result.purpose)
        if result.error is not None:
            source = "error"
            if result.error.startswith("Guardrail:"):
                logger.info("incident timeline blocked: %s", result.error)
                source = "fallback"
            artifact = self._incident_timeline_store.add(fallback_artifact)
            return IncidentTimelineResult(
                artifact=artifact,
                markdown=render_incident_timeline_markdown(artifact, include_hypotheses=include_hypotheses),
                source=source,
                elapsed_ms=result.elapsed_ms,
                error=result.error,
            )
        artifact = self._incident_timeline_store.add(
            parse_incident_timeline_artifact(
                result.text,
                purpose=spec.purpose,
                prompt_version=spec.version,
                source_session_id=source_session_id,
                request_id=request_id,
                source_start=normalized_start,
                source_end=normalized_end,
                include_hypotheses=include_hypotheses,
            )
        )
        return IncidentTimelineResult(
            artifact=artifact,
            markdown=render_incident_timeline_markdown(artifact, include_hypotheses=include_hypotheses),
            source="ai",
            elapsed_ms=result.elapsed_ms,
        )

    def latest_incident_timeline(self, source_session_id: str = "") -> IncidentTimelineArtifact | None:
        return self._incident_timeline_store.latest(source_session_id=source_session_id)

    def incident_timeline_snapshot(self) -> list[IncidentTimelineArtifact]:
        return self._incident_timeline_store.snapshot()

    def ask_conversation_question(
        self,
        messages: list[dict],
        *,
        question: str,
        scope: QAScope | None = None,
        source_session_id: str = "",
        request_id: str = "",
        prompt_override: str | None = None,
    ) -> ConversationQAResult:
        """Run scoped Q&A over conversation history with source-linked response."""
        spec = get_prompt_spec("conversation_qa")
        normalized_scope = normalize_scope(scope, total_messages=len(messages))
        selected_messages = select_messages(messages, normalized_scope)
        estimate = estimate_qa_budget(
            question=question,
            selected_messages=selected_messages,
            scope_mode=normalized_scope.scope.mode,
        )
        if normalized_scope.error:
            fallback = fallback_qa_artifact(
                purpose=spec.purpose,
                prompt_version=spec.version,
                question=question,
                normalized_scope=normalized_scope,
                fallback_answer=f"Scope error: {normalized_scope.error}",
            )
            return ConversationQAResult(
                artifact=fallback,
                markdown=render_qa_markdown(fallback),
                source="fallback",
                elapsed_ms=0,
                estimate=estimate,
                error=normalized_scope.error,
            )

        fallback_text = _fallback_summary(selected_messages)
        fallback = fallback_qa_artifact(
            purpose=spec.purpose,
            prompt_version=spec.version,
            question=question,
            normalized_scope=normalized_scope,
            fallback_answer=f"Fallback answer based on selected scope: {fallback_text}",
        )
        profile = "cache_probe_resume" if source_session_id else "ephemeral_default"

        if not self._side_channel.enabled:
            return ConversationQAResult(
                artifact=fallback,
                markdown=render_qa_markdown(fallback),
                source="fallback",
                elapsed_ms=0,
                estimate=estimate,
                error="side-channel disabled",
            )

        prepared = self.prepare_conversation_qa_prompt(
            question=question,
            selected_messages=selected_messages,
        )
        prompt = _resolve_prompt_override(prepared.prompt, prompt_override)
        result = self._side_channel.run(
            prompt=prompt,
            purpose=prepared.purpose,
            prompt_version=prepared.prompt_version,
            timeout=None,
            source_session_id=source_session_id,
            profile=profile,
        )
        self._analytics.record(purpose=result.purpose)
        if result.error is not None:
            source = "error"
            if result.error.startswith("Guardrail:"):
                logger.info("conversation qa blocked: %s", result.error)
                source = "fallback"
            return ConversationQAResult(
                artifact=fallback,
                markdown=render_qa_markdown(fallback),
                source=source,
                elapsed_ms=result.elapsed_ms,
                estimate=estimate,
                error=result.error,
            )
        artifact = parse_qa_artifact(
            result.text,
            purpose=spec.purpose,
            prompt_version=spec.version,
            question=question,
            request_id=request_id,
            normalized_scope=normalized_scope,
        )
        return ConversationQAResult(
            artifact=artifact,
            markdown=render_qa_markdown(artifact),
            source="ai",
            elapsed_ms=result.elapsed_ms,
            estimate=estimate,
        )

    def generate_release_notes(
        self,
        messages: list[dict],
        *,
        source_start: int,
        source_end: int,
        variant: str = "user_facing",
        source_session_id: str = "",
        request_id: str = "",
    ) -> ReleaseNotesResult:
        """Generate scoped release-note/changelog draft for review/edit flow."""
        spec = get_prompt_spec("release_notes")
        normalized_start, normalized_end = _normalize_message_range(
            total_messages=len(messages),
            source_start=source_start,
            source_end=source_end,
        )
        selected_messages = _slice_messages_for_range(messages, normalized_start, normalized_end)
        fallback_artifact = fallback_release_notes_artifact(
            purpose=spec.purpose,
            prompt_version=spec.version,
            source_session_id=source_session_id,
            request_id=request_id,
            source_start=normalized_start,
            source_end=normalized_end,
            summary_text=_fallback_summary(selected_messages),
        )
        profile = "cache_probe_resume" if source_session_id else "ephemeral_default"
        if not self._side_channel.enabled:
            artifact = self._release_notes_store.add(fallback_artifact)
            return ReleaseNotesResult(
                artifact=artifact,
                markdown=render_release_notes_markdown(artifact, variant=variant),
                source="fallback",
                elapsed_ms=0,
                variant=variant,
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
        if result.error is not None:
            source = "error"
            if result.error.startswith("Guardrail:"):
                logger.info("release notes blocked: %s", result.error)
                source = "fallback"
            artifact = self._release_notes_store.add(fallback_artifact)
            return ReleaseNotesResult(
                artifact=artifact,
                markdown=render_release_notes_markdown(artifact, variant=variant),
                source=source,
                elapsed_ms=result.elapsed_ms,
                variant=variant,
                error=result.error,
            )
        artifact = self._release_notes_store.add(
            parse_release_notes_artifact(
                result.text,
                purpose=spec.purpose,
                prompt_version=spec.version,
                source_session_id=source_session_id,
                request_id=request_id,
                source_start=normalized_start,
                source_end=normalized_end,
            )
        )
        return ReleaseNotesResult(
            artifact=artifact,
            markdown=render_release_notes_markdown(artifact, variant=variant),
            source="ai",
            elapsed_ms=result.elapsed_ms,
            variant=variant,
        )

    def latest_release_notes_draft(self, source_session_id: str = "") -> ReleaseNotesArtifact | None:
        return self._release_notes_store.latest(source_session_id=source_session_id)

    def release_notes_snapshot(self) -> list[ReleaseNotesArtifact]:
        return self._release_notes_store.snapshot()

    def render_release_notes_draft(self, *, artifact_id: str, variant: str = "user_facing") -> str:
        """Render stored draft for review/edit/export flow."""
        artifact = self._release_notes_store.get(artifact_id)
        if artifact is None:
            return "missing_release_notes_artifact:" + artifact_id
        return render_release_notes_markdown(artifact, variant=variant)

    def list_utilities(self) -> list[UtilitySpec]:
        return self._utility_registry.list()

    def run_utility(
        self,
        messages: list[dict],
        *,
        utility_id: str,
        source_session_id: str = "",
        prompt_override: str | None = None,
    ) -> UtilityResult:
        """Run registered lightweight utility with fallback behavior."""
        spec = self._utility_registry.get(utility_id)
        if spec is None:
            return UtilityResult(
                utility_id=utility_id,
                text=f"Unknown utility: {utility_id}",
                source="error",
                elapsed_ms=0,
                error="unknown utility",
            )

        fallback_text = fallback_utility_output(utility_id, messages)
        if not self._side_channel.enabled:
            return UtilityResult(
                utility_id=utility_id,
                text=fallback_text,
                source="fallback",
                elapsed_ms=0,
            )

        prepared = self.prepare_utility_prompt(messages, utility_id=utility_id)
        if prepared.error:
            return UtilityResult(
                utility_id=utility_id,
                text=fallback_text,
                source="fallback",
                elapsed_ms=0,
                error=prepared.error,
            )
        prompt = _resolve_prompt_override(prepared.prompt, prompt_override)
        profile = "cache_probe_resume" if source_session_id else "ephemeral_default"
        result = self._side_channel.run(
            prompt=prompt,
            purpose=prepared.purpose,
            prompt_version=prepared.prompt_version,
            timeout=None,
            source_session_id=source_session_id,
            profile=profile,
        )
        self._analytics.record(purpose=result.purpose)
        if result.error is not None:
            source = "error"
            if result.error.startswith("Guardrail:"):
                logger.info("utility blocked: %s (%s)", utility_id, result.error)
                source = "fallback"
            return UtilityResult(
                utility_id=utility_id,
                text=fallback_text,
                source=source,
                elapsed_ms=result.elapsed_ms,
                error=result.error,
            )
        return UtilityResult(
            utility_id=utility_id,
            text=result.text,
            source="ai",
            elapsed_ms=result.elapsed_ms,
        )

    def prepare_summary_prompt(self, messages: list[dict]) -> PreparedPrompt:
        """Build canonical prompt payload for summary actions."""
        spec = get_prompt_spec("block_summary")
        context = _build_summary_context(messages)
        return PreparedPrompt(
            prompt=_build_summary_prompt(context, spec),
            purpose=spec.purpose,
            prompt_version=spec.version,
        )

    def prepare_action_extraction_prompt(self, messages: list[dict]) -> PreparedPrompt:
        """Build canonical prompt payload for action extraction."""
        spec = get_prompt_spec("action_extraction")
        context = _build_summary_context(messages)
        return PreparedPrompt(
            prompt=_build_summary_prompt(context, spec),
            purpose=spec.purpose,
            prompt_version=spec.version,
        )

    def prepare_conversation_qa_prompt(
        self,
        *,
        question: str,
        selected_messages: list[dict],
    ) -> PreparedPrompt:
        """Build canonical prompt payload for scoped conversation Q&A."""
        spec = get_prompt_spec("conversation_qa")
        context = _build_summary_context(selected_messages)
        return PreparedPrompt(
            prompt=_build_conversation_qa_prompt(question=question, context=context, spec=spec),
            purpose=spec.purpose,
            prompt_version=spec.version,
        )

    def prepare_utility_prompt(self, messages: list[dict], *, utility_id: str) -> PreparedPrompt:
        """Build canonical prompt payload for a registered utility."""
        spec = self._utility_registry.get(utility_id)
        if spec is None:
            return PreparedPrompt(
                prompt="",
                purpose=UTILITY_CUSTOM_PURPOSE,
                prompt_version="v1",
                error="unknown utility",
            )
        context = _build_summary_context(messages)
        return PreparedPrompt(
            prompt=utility_prompt(spec, context),
            purpose=UTILITY_CUSTOM_PURPOSE,
            prompt_version=spec.version,
        )


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


def _resolve_prompt_override(default_prompt: str, prompt_override: str | None) -> str:
    """Resolve optional user-edited prompt while preserving canonical fallback."""
    override = str(prompt_override or "").strip()
    return override if override else default_prompt


def _build_incident_timeline_prompt(*, context: str, spec: PromptSpec, include_hypotheses: bool) -> str:
    """Build incident prompt with explicit mode (facts-only vs facts+hypotheses)."""
    mode = "Include hypotheses section." if include_hypotheses else "Facts only. Omit hypotheses."
    if not context:
        return f"{spec.instruction}\n\n{mode}"
    return f"{spec.instruction}\n\n{mode}\n\n{context}"


def _build_conversation_qa_prompt(*, question: str, context: str, spec: PromptSpec) -> str:
    if not context:
        return f"{spec.instruction}\n\nQuestion:\n{question}"
    return f"{spec.instruction}\n\nQuestion:\n{question}\n\nContext:\n{context}"


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
