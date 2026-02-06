# Implementation Context: Sprint 4 - Formatting IR

## formatting.py structure after rewrite

```python
"""HTTP request/response formatting — structured intermediate representation."""

import json
from dataclasses import dataclass, field
from datetime import datetime

# ─── Structured IR ─────────────────────────────────────────────────────

@dataclass
class FormattedBlock:
    """Base class for all formatted output blocks."""
    pass

# --- Keep as-is ---
@dataclass
class SeparatorBlock(FormattedBlock): ...
@dataclass
class HeaderBlock(FormattedBlock): ...
@dataclass
class HttpHeadersBlock(FormattedBlock): ...
@dataclass
class NewlineBlock(FormattedBlock): ...
@dataclass
class ErrorBlock(FormattedBlock): ...
@dataclass
class ProxyErrorBlock(FormattedBlock): ...
@dataclass
class LogBlock(FormattedBlock): ...
@dataclass
class TextContentBlock(FormattedBlock): ...

# --- New generic HTTP blocks ---
@dataclass
class RequestHeaderBlock(FormattedBlock):
    """Request line: METHOD URL (with number and timestamp)."""
    method: str = ""
    url: str = ""
    request_num: int = 0
    timestamp: str = ""

@dataclass
class ResponseStatusBlock(FormattedBlock):
    """Response status summary."""
    status_code: int = 0
    content_type: str = ""
    size: int = 0
    duration_ms: float = 0.0

@dataclass
class JsonBodyBlock(FormattedBlock):
    """Pretty-printed JSON body."""
    body: str = ""           # pre-formatted JSON string
    truncated: bool = False
    full_size: int = 0
    body_type: str = "request"  # "request" or "response"

@dataclass
class TextBodyBlock(FormattedBlock):
    """Raw text body."""
    text: str = ""
    content_type: str = ""
    truncated: bool = False

@dataclass
class BinaryBodyBlock(FormattedBlock):
    """Binary body placeholder."""
    content_type: str = ""
    size: int = 0

@dataclass
class SSEEventBlock(FormattedBlock):
    """A single SSE event."""
    event_type: str = ""
    data_preview: str = ""
    full_size: int = 0

@dataclass
class SSEStreamSummaryBlock(FormattedBlock):
    """Collapsed SSE stream summary."""
    event_count: int = 0
    total_size: int = 0
    duration_ms: float = 0.0

# --- DELETE all of these ---
# MetadataBlock, SystemLabelBlock, TrackedContentBlock, DiffBlock,
# RoleBlock, ToolUseBlock, ToolResultBlock, ImageBlock, UnknownTypeBlock,
# StreamInfoBlock, StreamToolUseBlock, TextDeltaBlock, StopReasonBlock,
# TurnBudgetBlock
# Also delete: track_content, _make_tracked_block, make_diff_lines,
# _tool_detail, _merge_tool_only_assistant_runs, format_response_event,
# format_complete_response, MSG_COLOR_CYCLE

# ─── Format functions ──────────────────────────────────────────────────

JSON_TRUNCATE_BYTES = 4096  # Display limit for JSON bodies

def _get_timestamp():
    return datetime.now().strftime("%-I:%M:%S %p")

def _detect_body_blocks(body_bytes: bytes, content_type: str, body_type: str = "request") -> list[FormattedBlock]:
    """Detect content type and create appropriate body block."""
    if not body_bytes:
        return []

    # Try JSON
    if "json" in content_type or (not content_type and body_bytes.startswith(b"{")):
        try:
            text = body_bytes.decode("utf-8")
            parsed = json.loads(text)
            pretty = json.dumps(parsed, indent=2)
            truncated = len(pretty) > JSON_TRUNCATE_BYTES
            display = pretty[:JSON_TRUNCATE_BYTES] if truncated else pretty
            return [JsonBodyBlock(
                body=display, truncated=truncated,
                full_size=len(pretty), body_type=body_type,
            )]
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass  # Fall through to text

    # Try text
    if content_type.startswith("text/") or "xml" in content_type or "html" in content_type:
        try:
            text = body_bytes.decode("utf-8", errors="replace")
            truncated = len(text) > JSON_TRUNCATE_BYTES
            return [TextBodyBlock(
                text=text[:JSON_TRUNCATE_BYTES] if truncated else text,
                content_type=content_type, truncated=truncated,
            )]
        except Exception:
            pass

    # Binary fallback
    return [BinaryBodyBlock(content_type=content_type, size=len(body_bytes))]

def format_request(method: str, url: str, headers: dict, body_bytes: bytes, state: dict) -> list[FormattedBlock]:
    """Format any HTTP request."""
    state["request_counter"] += 1
    num = state["request_counter"]
    content_type = headers.get("content-type", "")

    blocks = [
        NewlineBlock(),
        SeparatorBlock(style="heavy"),
        RequestHeaderBlock(method=method, url=url, request_num=num, timestamp=_get_timestamp()),
        SeparatorBlock(style="heavy"),
    ]
    blocks.extend(_detect_body_blocks(body_bytes, content_type, body_type="request"))
    return blocks

def format_response_start(status_code: int, headers: dict) -> list[FormattedBlock]:
    """Format response status + headers."""
    return [HttpHeadersBlock(headers=headers, header_type="response", status_code=status_code)]

def format_response_body(body_bytes: bytes, content_type: str) -> list[FormattedBlock]:
    """Format non-streaming response body."""
    return _detect_body_blocks(body_bytes, content_type, body_type="response")

def format_sse_event(event_type: str, data: str) -> list[FormattedBlock]:
    """Format a single SSE event."""
    preview = data[:200] if len(data) > 200 else data
    return [SSEEventBlock(event_type=event_type, data_preview=preview, full_size=len(data))]

def format_request_headers(headers_dict: dict) -> list[FormattedBlock]:
    """Format HTTP request headers as blocks."""
    if not headers_dict:
        return []
    return [HttpHeadersBlock(headers=headers_dict, header_type="request")]

def format_response_headers(status_code: int, headers_dict: dict) -> list[FormattedBlock]:
    """Format HTTP response headers as blocks."""
    if not headers_dict:
        return []
    return [HttpHeadersBlock(headers=headers_dict, header_type="response", status_code=status_code)]
```

## State dict (simplified)
```python
state = {
    "request_counter": 0,
    # That's it. No more positions, known_hashes, next_id, next_color.
}
```

## Filter mapping for new blocks
```python
BLOCK_FILTER_KEY = {
    "SeparatorBlock": "headers",
    "HeaderBlock": "headers",
    "RequestHeaderBlock": None,        # Always visible (request summary line)
    "HttpHeadersBlock": "headers",
    "ResponseStatusBlock": None,       # Always visible (response summary line)
    "JsonBodyBlock": "body",
    "TextBodyBlock": "body",
    "BinaryBodyBlock": "body",
    "SSEEventBlock": "sse",
    "SSEStreamSummaryBlock": "sse",
    "TextContentBlock": None,
    "ErrorBlock": None,
    "ProxyErrorBlock": None,
    "LogBlock": None,
    "NewlineBlock": None,
}
```
