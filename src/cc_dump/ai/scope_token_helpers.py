"""Shared scope/token helper primitives for AI prompt and budget flows.

// [LAW:one-source-of-truth] Message text normalization for prompt context and
// token estimation is centralized in this module.
"""

from __future__ import annotations

import math


def normalize_message_content(
    content: object,
    *,
    truncate_content_at: int | None = None,
) -> str:
    """Normalize a message content payload into plain text."""
    if isinstance(content, list):
        text_parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(str(block.get("text", "")))
        normalized = " ".join(part for part in text_parts if part)
    else:
        normalized = str(content)
    if (
        truncate_content_at is not None
        and truncate_content_at >= 0
        and len(normalized) > truncate_content_at
    ):
        return normalized[:truncate_content_at] + "..."
    return normalized


def build_message_context_lines(
    messages: list[dict],
    *,
    line_template: str,
    truncate_content_at: int | None = None,
) -> list[str]:
    """Render message lines with shared role/content normalization."""
    lines: list[str] = []
    for message in messages:
        lines.append(
            line_template.format(
                role=str(message.get("role", "unknown")),
                content=normalize_message_content(
                    message.get("content", ""),
                    truncate_content_at=truncate_content_at,
                ),
            )
        )
    return lines


def estimate_tokens_from_text(text: str) -> int:
    """Estimate token count from text length using shared policy."""
    return max(1, math.ceil(len(text) / 4))

