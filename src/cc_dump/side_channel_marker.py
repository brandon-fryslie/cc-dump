"""Side-channel request marker helpers.

// [LAW:one-source-of-truth] Marker encoding/decoding lives in one module.
// [LAW:single-enforcer] Marker parse/strip logic is centralized here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from cc_dump.side_channel_purpose import normalize_purpose

MARKER_PREFIX = "<<CC_DUMP_SIDE_CHANNEL:"
MARKER_SUFFIX = ">>"


@dataclass(frozen=True)
class SideChannelMarker:
    run_id: str
    purpose: str
    source_session_id: str = ""
    prompt_version: str = "v1"


def encode_marker(marker: SideChannelMarker) -> str:
    """Encode marker to a single-line prefix."""
    payload = {
        "run_id": marker.run_id,
        "purpose": marker.purpose,
        "source_session_id": marker.source_session_id,
        "prompt_version": marker.prompt_version,
    }
    return f"{MARKER_PREFIX}{json.dumps(payload, separators=(',', ':'))}{MARKER_SUFFIX}"


def prepend_marker(text: str, marker: SideChannelMarker) -> str:
    """Prefix text with marker line."""
    return f"{encode_marker(marker)}\n{text}"


def extract_marker(body: dict) -> SideChannelMarker | None:
    """Extract marker from the last user message in a request body."""
    messages = body.get("messages", [])
    if not isinstance(messages, list) or not messages:
        return None
    last = messages[-1]
    if not isinstance(last, dict) or last.get("role") != "user":
        return None

    content = last.get("content", "")
    text = _extract_text(content)
    if text is None:
        return None
    return _parse_marker_text(text)


def strip_marker_from_body(body: dict) -> dict:
    """Return a copy of body with side-channel marker removed from last user text."""
    marker = extract_marker(body)
    if marker is None:
        return body

    # [LAW:dataflow-not-control-flow] Always return a body object; unchanged if no marker.
    updated = dict(body)
    messages = body.get("messages", [])
    if not isinstance(messages, list) or not messages:
        return updated
    new_messages = list(messages)
    last = new_messages[-1]
    if not isinstance(last, dict):
        return updated
    new_last = dict(last)
    content = last.get("content", "")

    if isinstance(content, str):
        new_last["content"] = _strip_marker_text(content)
    elif isinstance(content, list):
        new_blocks = []
        replaced = False
        for block in content:
            if not isinstance(block, dict):
                new_blocks.append(block)
                continue
            if not replaced and block.get("type") == "text":
                text = block.get("text", "")
                if isinstance(text, str):
                    block_copy = dict(block)
                    block_copy["text"] = _strip_marker_text(text)
                    new_blocks.append(block_copy)
                    replaced = True
                    continue
            new_blocks.append(block)
        new_last["content"] = new_blocks

    new_messages[-1] = new_last
    updated["messages"] = new_messages
    return updated


def _extract_text(content: object) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = block.get("text", "")
                return text if isinstance(text, str) else None
        return None
    return None


def _parse_marker_text(text: str) -> SideChannelMarker | None:
    stripped = text.lstrip()
    if not stripped.startswith(MARKER_PREFIX):
        return None
    end = stripped.find(MARKER_SUFFIX)
    if end == -1:
        return None
    payload_raw = stripped[len(MARKER_PREFIX):end]
    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    run_id = payload.get("run_id", "")
    purpose = payload.get("purpose", "")
    source_session_id = payload.get("source_session_id", "")
    prompt_version = payload.get("prompt_version", "v1")
    if not isinstance(run_id, str) or not run_id:
        return None
    if not isinstance(purpose, str) or not purpose:
        return None
    if not isinstance(source_session_id, str):
        source_session_id = ""
    if not isinstance(prompt_version, str) or not prompt_version:
        prompt_version = "v1"
    normalized_purpose = normalize_purpose(purpose)
    return SideChannelMarker(
        run_id=run_id,
        purpose=normalized_purpose,
        source_session_id=source_session_id,
        prompt_version=prompt_version,
    )


def _strip_marker_text(text: str) -> str:
    stripped = text.lstrip()
    if not stripped.startswith(MARKER_PREFIX):
        return text
    end = stripped.find(MARKER_SUFFIX)
    if end == -1:
        return text
    remainder = stripped[end + len(MARKER_SUFFIX):]
    if remainder.startswith("\n"):
        remainder = remainder[1:]
    return remainder
