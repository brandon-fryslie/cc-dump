"""Centralized side-channel context boundary (minimization + redaction).

// [LAW:one-source-of-truth] Purpose policy definitions live in one module.
// [LAW:single-enforcer] Side-channel dispatch applies this boundary exactly once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cc_dump.ai.prompt_registry import SIDE_CHANNEL_PURPOSES, normalize_purpose


REDACTION_POLICY_VERSION = "redaction-v1"


@dataclass(frozen=True)
class SideChannelBoundaryPolicy:
    purpose: str
    max_prompt_chars: int
    policy_version: str = REDACTION_POLICY_VERSION


@dataclass(frozen=True)
class SideChannelBoundaryResult:
    prompt: str
    purpose: str
    policy_version: str
    redactions_applied: int
    truncated: bool


_DEFAULT_MAX_PROMPT_CHARS = 24_000
_MAX_PROMPT_CHARS_BY_PURPOSE: dict[str, int] = {
    purpose: _DEFAULT_MAX_PROMPT_CHARS for purpose in SIDE_CHANNEL_PURPOSES
}
_MAX_PROMPT_CHARS_BY_PURPOSE.update({
    "core_debug_lane": 12_000,
    "block_summary": 16_000,
    "conversation_qa": 24_000,
    "compaction": 40_000,
    "utility_custom": 12_000,
})

POLICY_BY_PURPOSE: dict[str, SideChannelBoundaryPolicy] = {
    purpose: SideChannelBoundaryPolicy(
        purpose=purpose,
        max_prompt_chars=max(256, int(_MAX_PROMPT_CHARS_BY_PURPOSE.get(purpose, _DEFAULT_MAX_PROMPT_CHARS))),
    )
    for purpose in SIDE_CHANNEL_PURPOSES
}

_REDACTION_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Bearer tokens in copied headers.
    (re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[a-z0-9._\-]+"), r"\1[REDACTED]"),
    # Common API-key header formats.
    (re.compile(r"(?i)(x-api-key\s*[:=]\s*)\S+"), r"\1[REDACTED]"),
    # Anthropic/OpenAI style keys frequently pasted in debugging sessions.
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "[REDACTED_API_KEY]"),
    # AWS access keys.
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    # Assignment-style password secrets.
    (re.compile(r"(?i)\b(password|passwd|pwd)\s*[:=]\s*[^\s,;]+"), r"\1=[REDACTED]"),
    # PEM private keys.
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
        ),
        "[REDACTED_PRIVATE_KEY_BLOCK]",
    ),
)


def get_boundary_policy(purpose: str) -> SideChannelBoundaryPolicy:
    """Return the canonical minimization policy for a purpose."""
    normalized = normalize_purpose(purpose)
    return POLICY_BY_PURPOSE[normalized]


def apply_boundary(prompt: str, purpose: str) -> SideChannelBoundaryResult:
    """Apply centralized redaction + size cap for side-channel dispatch."""
    policy = get_boundary_policy(purpose)
    redacted_text, redaction_count = _apply_redactions(prompt)
    bounded_prompt, truncated = _enforce_prompt_cap(redacted_text, policy.max_prompt_chars)
    return SideChannelBoundaryResult(
        prompt=bounded_prompt,
        purpose=policy.purpose,
        policy_version=policy.policy_version,
        redactions_applied=redaction_count,
        truncated=truncated,
    )


def _apply_redactions(text: str) -> tuple[str, int]:
    current = text
    replacements = 0
    for pattern, replacement in _REDACTION_RULES:
        current, n = pattern.subn(replacement, current)
        replacements += n
    return current, replacements


def _enforce_prompt_cap(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    trailer = "\n[TRUNCATED_BY_POLICY]"
    keep = max(0, max_chars - len(trailer))
    return text[:keep] + trailer, True
