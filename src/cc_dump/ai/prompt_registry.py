"""Prompt registry for side-channel purposes.

// [LAW:one-source-of-truth] Purpose->prompt templates live in one registry.
"""

from __future__ import annotations

from dataclasses import dataclass

UTILITY_CUSTOM_PURPOSE = "utility_custom"

@dataclass(frozen=True)
class PromptSpec:
    purpose: str
    version: str
    instruction: str


PROMPT_REGISTRY: dict[str, PromptSpec] = {
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
    "conversation_qa": PromptSpec(
        purpose="conversation_qa",
        version="v1",
        instruction=(
            "Answer questions using only provided context and return strict JSON only with shape "
            "{\"answer\":\"\",\"source_links\":[{\"message_index\":0,\"quote\":\"\"}]}. "
            "Cite the most relevant source messages."
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

# Ordered for deterministic UI/report rendering.
SIDE_CHANNEL_PURPOSES: tuple[str, ...] = (
    "core_debug_lane",
    "handoff_note",
    "conversation_qa",
    "checkpoint_summary",
    "compaction",
    UTILITY_CUSTOM_PURPOSE,
)

_SIDE_CHANNEL_PURPOSE_SET = frozenset(SIDE_CHANNEL_PURPOSES)


def normalize_purpose(purpose: str) -> str:
    """Return canonical purpose value for side-channel requests.

    // [LAW:single-enforcer] Purpose normalization is enforced only here.
    """
    return purpose if purpose in _SIDE_CHANNEL_PURPOSE_SET else UTILITY_CUSTOM_PURPOSE


def get_prompt_spec(purpose: str) -> PromptSpec:
    """Return prompt spec for purpose with utility fallback."""
    canonical_purpose = normalize_purpose(purpose)
    spec = PROMPT_REGISTRY.get(canonical_purpose)
    if spec is not None:
        return spec
    return _UTILITY_CUSTOM_PROMPT
