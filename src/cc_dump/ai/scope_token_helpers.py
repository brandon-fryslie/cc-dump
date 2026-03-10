"""Shared scope/token helper primitives for AI prompt and budget flows."""

from __future__ import annotations

from cc_dump.core.analysis import estimate_tokens


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
    """Estimate token count using the canonical core token policy.

    // [LAW:one-source-of-truth] Delegate to core.analysis.estimate_tokens.
    """
    return estimate_tokens(text)
