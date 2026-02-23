"""Sentinel interceptor — detects $$ prefix in user messages, short-circuits response.

// [LAW:locality-or-seam] All sentinel logic isolated here; proxy uses make_interceptor().
// [LAW:dataflow-not-control-flow] extract_sentinel_command is a pure function on body data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cc_dump.app.tmux_controller import TmuxController

SENTINEL = "$$"


def extract_sentinel_command(body: dict) -> str | None:
    """Extract command text after $$ from the last user message, or None.

    Handles both string content and block-list content formats.
    Only triggers on the last message with role == "user".
    """
    messages = body.get("messages", [])
    if not messages:
        return None

    last = messages[-1]
    if not isinstance(last, dict):
        return None
    if last.get("role") != "user":
        return None

    content = last.get("content", "")

    # String content: "$$command"
    if isinstance(content, str):
        text = content.strip()
        if text.startswith(SENTINEL):
            return text[len(SENTINEL):]
        return None

    # Block-list content: [{"type": "text", "text": "$$command"}, ...]
    if isinstance(content, list):
        # Check first text block only
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = block.get("text", "")
                if isinstance(text, str):
                    text = text.strip()
                    if text.startswith(SENTINEL):
                        return text[len(SENTINEL):]
                return None  # First text block didn't match

    return None


def make_interceptor(tmux_controller: TmuxController | None = None):
    """Create a sentinel interceptor closure.

    Returns a callable (body) -> str | None that:
    1. Checks for $$ sentinel in last user message
    2. Focuses cc-dump tmux pane if available
    3. Returns "[cc-dump]" response text, or None if not a sentinel message
    """

    def interceptor(body: dict) -> str | None:
        command = extract_sentinel_command(body)
        if command is None:
            return None

        # Focus cc-dump pane
        if tmux_controller is not None:
            tmux_controller.focus_self()

        return "[cc-dump]"

    return interceptor
