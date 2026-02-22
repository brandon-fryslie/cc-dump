"""Prompt registry for side-channel purposes.

// [LAW:one-source-of-truth] Purpose->prompt templates live in one registry.
"""

from __future__ import annotations

from dataclasses import dataclass

from cc_dump.side_channel_purpose import normalize_purpose


@dataclass(frozen=True)
class PromptSpec:
    purpose: str
    version: str
    instruction: str


PROMPT_REGISTRY: dict[str, PromptSpec] = {
    "block_summary": PromptSpec(
        purpose="block_summary",
        version="v1",
        instruction=(
            "Summarize this conversation concisely. "
            "Focus on accomplishments and key decisions."
        ),
    ),
    "decision_ledger": PromptSpec(
        purpose="decision_ledger",
        version="v1",
        instruction=(
            "Extract explicit decisions, rationale, alternatives, and status. "
            "Return concise bullet points."
        ),
    ),
    "action_extraction": PromptSpec(
        purpose="action_extraction",
        version="v1",
        instruction=(
            "Extract concrete action items and deferred work. "
            "Include owner hints only if explicit."
        ),
    ),
    "handoff_note": PromptSpec(
        purpose="handoff_note",
        version="v1",
        instruction=(
            "Generate a handoff note with sections: changed, decisions, open work, risks."
        ),
    ),
    "release_notes": PromptSpec(
        purpose="release_notes",
        version="v1",
        instruction="Draft release notes and a short changelog from the selected context.",
    ),
    "incident_timeline": PromptSpec(
        purpose="incident_timeline",
        version="v1",
        instruction=(
            "Create a chronological incident timeline with timestamps, actions, outcomes."
        ),
    ),
    "conversation_qa": PromptSpec(
        purpose="conversation_qa",
        version="v1",
        instruction=(
            "Answer questions using only provided conversation context; cite message excerpts."
        ),
    ),
    "checkpoint_summary": PromptSpec(
        purpose="checkpoint_summary",
        version="v1",
        instruction="Summarize the provided range as a checkpoint snapshot.",
    ),
    "compaction": PromptSpec(
        purpose="compaction",
        version="v1",
        instruction=(
            "Create an intentional compact representation preserving decisions and open work."
        ),
    ),
}


def get_prompt_spec(purpose: str) -> PromptSpec:
    """Return prompt spec for purpose with utility fallback."""
    canonical_purpose = normalize_purpose(purpose)
    spec = PROMPT_REGISTRY.get(canonical_purpose)
    if spec is not None:
        return spec
    return PromptSpec(
        purpose=canonical_purpose,
        version="v1",
        instruction="Process the provided context according to the request.",
    )
