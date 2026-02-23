"""Canonical side-channel purpose taxonomy.

// [LAW:one-source-of-truth] Purpose taxonomy + normalization is centralized here.
// [LAW:single-enforcer] Purpose normalization is enforced only by normalize_purpose().
"""

from __future__ import annotations

UTILITY_CUSTOM_PURPOSE = "utility_custom"

# Ordered for deterministic UI/report rendering.
SIDE_CHANNEL_PURPOSES: tuple[str, ...] = (
    "core_debug_lane",
    "block_summary",
    "decision_ledger",
    "action_extraction",
    "handoff_note",
    "release_notes",
    "incident_timeline",
    "conversation_qa",
    "checkpoint_summary",
    "compaction",
    UTILITY_CUSTOM_PURPOSE,
)

_SIDE_CHANNEL_PURPOSE_SET = frozenset(SIDE_CHANNEL_PURPOSES)


def normalize_purpose(purpose: str) -> str:
    """Return canonical purpose value for side-channel requests."""
    return purpose if purpose in _SIDE_CHANNEL_PURPOSE_SET else UTILITY_CUSTOM_PURPOSE
