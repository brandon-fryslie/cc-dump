"""Prompt registry for side-channel purposes.

// [LAW:one-source-of-truth] Purpose->prompt templates live in one registry.
"""

from __future__ import annotations

from dataclasses import dataclass

from cc_dump.side_channel_purpose import normalize_purpose, UTILITY_CUSTOM_PURPOSE


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
            "Extract explicit decisions and return strict JSON only with shape "
            "{\"decisions\":[{\"decision_id\":\"\",\"statement\":\"\",\"rationale\":\"\","
            "\"alternatives\":[],\"consequences\":[],\"status\":\"proposed|accepted|revised|deprecated\","
            "\"source_links\":[{\"message_index\":0}],\"supersedes\":[]}]}. "
            "Use empty arrays for unknown fields."
        ),
    ),
    "action_extraction": PromptSpec(
        purpose="action_extraction",
        version="v1",
        instruction=(
            "Extract action and deferred items and return strict JSON only with shape "
            "{\"items\":[{\"kind\":\"action|deferred\",\"text\":\"\",\"confidence\":0.0,"
            "\"owner\":\"\",\"due_hint\":\"\",\"source_links\":[{\"message_index\":0}]}]}. "
            "Only include explicit actions/deferred work. Use empty strings or arrays when unknown."
        ),
    ),
    "handoff_note": PromptSpec(
        purpose="handoff_note",
        version="v1",
        instruction=(
            "Generate a handoff note and return strict JSON only with shape "
            "{\"sections\":{\"changed\":[{\"text\":\"\",\"source_links\":[{\"message_index\":0}]}],"
            "\"decisions\":[],\"open_work\":[],\"risks\":[],\"next_steps\":[]}}. "
            "Every section key is required; use empty arrays when unknown."
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

_UTILITY_CUSTOM_PROMPT = PromptSpec(
    purpose=UTILITY_CUSTOM_PURPOSE,
    version="v1",
    instruction="Process the provided context according to the request.",
)


def get_prompt_spec(purpose: str) -> PromptSpec:
    """Return prompt spec for purpose with utility fallback."""
    canonical_purpose = normalize_purpose(purpose)
    spec = PROMPT_REGISTRY.get(canonical_purpose)
    if spec is not None:
        return spec
    return _UTILITY_CUSTOM_PROMPT
