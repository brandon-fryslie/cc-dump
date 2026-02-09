"""HAR recording subscriber for HTTP Archive format output.

Accumulates streaming SSE events and reconstructs complete HTTP request/response
pairs in HAR 1.2 format for replay and analysis in standard tools.
"""

import json
import os
import sys
from datetime import datetime, timezone


def build_har_request(method: str, url: str, headers: dict, body: dict) -> dict:
    """Build HAR request entry from HTTP headers and JSON body.

    Args:
        method: HTTP method (e.g., "POST")
        url: Full URL
        headers: Request headers dict
        body: Request body dict (will be modified to set stream=false for clarity)

    Returns:
        HAR request structure with method, url, headers, postData
    """
    # Create synthetic non-streaming request body for clarity in HAR viewers
    synthetic_body = body.copy()
    synthetic_body["stream"] = False

    # Convert headers dict to HAR format (list of name/value pairs)
    har_headers = [{"name": k, "value": v} for k, v in headers.items()]

    return {
        "method": method,
        "url": url,
        "httpVersion": "HTTP/1.1",
        "headers": har_headers,
        "queryString": [],
        "postData": {
            "mimeType": "application/json",
            "text": json.dumps(synthetic_body),
        },
        "headersSize": -1,
        "bodySize": len(json.dumps(synthetic_body).encode("utf-8")),
    }


def build_har_response(
    status: int, headers: dict, complete_message: dict, time_ms: float
) -> dict:
    """Build HAR response entry from reconstructed complete message.

    Args:
        status: HTTP status code
        headers: Response headers dict (synthetic application/json)
        complete_message: Complete Claude message (non-streaming format)
        time_ms: Total request time in milliseconds

    Returns:
        HAR response structure with status, headers, content, timings
    """
    response_text = json.dumps(complete_message)

    # Synthetic headers for non-streaming response
    har_headers = [
        {"name": "content-type", "value": "application/json"},
        {"name": "content-length", "value": str(len(response_text.encode("utf-8")))},
    ]

    # Add additional headers if provided
    for k, v in headers.items():
        if k.lower() not in ("content-type", "content-length", "transfer-encoding"):
            har_headers.append({"name": k, "value": v})

    return {
        "status": status,
        "statusText": "OK" if status == 200 else "",
        "httpVersion": "HTTP/1.1",
        "headers": har_headers,
        "content": {
            "size": len(response_text.encode("utf-8")),
            "mimeType": "application/json",
            "text": response_text,
        },
        "redirectURL": "",
        "headersSize": -1,
        "bodySize": len(response_text.encode("utf-8")),
    }


# [LAW:dataflow-not-control-flow] State container for event reconstruction
class _ReconstructionState:
    """Shared state for event reconstructors."""

    def __init__(self, message: dict, content_blocks: list, current_text_block: dict | None):
        self.message = message
        self.content_blocks = content_blocks
        self.current_text_block = current_text_block


def _handle_message_start(event: dict, state: _ReconstructionState) -> None:
    """Handle message_start event."""
    msg = event.get("message", {})
    state.message["id"] = msg.get("id", "")
    state.message["model"] = msg.get("model", "")
    state.message["role"] = msg.get("role", "assistant")
    state.message["usage"] = dict(msg.get("usage", {}))


def _handle_content_block_start(event: dict, state: _ReconstructionState) -> None:
    """Handle content_block_start event."""
    block = event.get("content_block", {})
    block_type = block.get("type", "")
    if block_type == "text":
        state.current_text_block = {"type": "text", "text": ""}
        state.content_blocks.append(state.current_text_block)
    elif block_type == "tool_use":
        tool_block = {
            "type": "tool_use",
            "id": block.get("id", ""),
            "name": block.get("name", ""),
            "input": {},
        }
        state.content_blocks.append(tool_block)
        state.current_text_block = None


def _handle_content_block_delta(event: dict, state: _ReconstructionState) -> None:
    """Handle content_block_delta event."""
    delta = event.get("delta", {})
    delta_type = delta.get("type", "")

    if delta_type == "text_delta" and state.current_text_block:
        state.current_text_block["text"] += delta.get("text", "")

    elif delta_type == "input_json_delta":
        # For tool use blocks, accumulate JSON input
        if state.content_blocks and state.content_blocks[-1].get("type") == "tool_use":
            # Accumulate JSON string (will need parsing at end)
            if "_input_json_str" not in state.content_blocks[-1]:
                state.content_blocks[-1]["_input_json_str"] = ""
            state.content_blocks[-1]["_input_json_str"] += delta.get("partial_json", "")


def _handle_content_block_stop(event: dict, state: _ReconstructionState) -> None:
    """Handle content_block_stop event."""
    # Finalize current block
    if state.content_blocks and state.content_blocks[-1].get("type") == "tool_use":
        # Parse accumulated JSON
        json_str = state.content_blocks[-1].pop("_input_json_str", "{}")
        try:
            state.content_blocks[-1]["input"] = json.loads(json_str)
        except json.JSONDecodeError:
            state.content_blocks[-1]["input"] = {}
    state.current_text_block = None


def _handle_message_delta(event: dict, state: _ReconstructionState) -> None:
    """Handle message_delta event."""
    delta = event.get("delta", {})
    if "stop_reason" in delta:
        state.message["stop_reason"] = delta["stop_reason"]
    if "stop_sequence" in delta:
        state.message["stop_sequence"] = delta["stop_sequence"]
    # Update usage with output tokens
    usage_delta = event.get("usage", {})
    if usage_delta:
        state.message["usage"].update(usage_delta)


# [LAW:dataflow-not-control-flow] Event reconstruction dispatch table
_EVENT_RECONSTRUCTORS = {
    "message_start": _handle_message_start,
    "content_block_start": _handle_content_block_start,
    "content_block_delta": _handle_content_block_delta,
    "content_block_stop": _handle_content_block_stop,
    "message_delta": _handle_message_delta,
}


def reconstruct_message_from_events(events: list[dict]) -> dict:
    """Reconstruct complete Claude message from SSE event sequence.

    This is the KEY function: accumulates deltas into final message in the
    same format as if stream=false was used in the API request.

    Args:
        events: List of SSE event dicts (message_start, content_block_delta, etc.)

    Returns:
        Complete message dict: {"id": "...", "type": "message", "content": [...], "usage": {...}}
    """
    message = {
        "id": "",
        "type": "message",
        "role": "assistant",
        "content": [],
        "model": "",
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {},
    }

    # Initialize reconstruction state
    state = _ReconstructionState(
        message=message,
        content_blocks=[],
        current_text_block=None,
    )

    # [LAW:dataflow-not-control-flow] Dispatch via table lookup
    for event in events:
        event_type = event.get("type", "")
        handler = _EVENT_RECONSTRUCTORS.get(event_type)
        if handler:
            handler(event, state)

    state.message["content"] = state.content_blocks
    return state.message


class HARRecordingSubscriber:
    """Subscriber that accumulates events and writes HAR entries incrementally.

    This is a DirectSubscriber-style component that runs inline in the router
    thread. It writes each complete HAR entry immediately to disk, so the file
    is always valid HAR JSON and close() is instant.
    """

    def __init__(self, path: str, session_id: str):
        """Initialize HAR recorder and open file with valid empty HAR.

        Args:
            path: Output file path for HAR file
            session_id: Session ID for metadata
        """
        self.path = path
        self.session_id = session_id

        # State machine for current request/response
        self.pending_request = None
        self.pending_request_headers = None
        self.response_status = None
        self.response_headers = None
        self.response_events = []
        self.request_start_time = None

        # Open file and write valid empty HAR structure
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

        # Build HAR header through the opening bracket of entries array
        har_header = {
            "log": {
                "version": "1.2",
                "creator": {"name": "cc-dump", "version": "0.2.0"},
                "entries": [],
            }
        }
        header_json = json.dumps(har_header, ensure_ascii=False)
        # Strip trailing ]}} to get preamble through opening [
        preamble = header_json[:-3]  # Remove ]}}

        self._file = open(self.path, "w", encoding="utf-8")
        self._file.write(preamble)
        self._entries_end_pos = self._file.tell()
        self._file.write("\n]}}")
        self._file.flush()

        self._first_entry = True
        self._entry_count = 0

    def on_event(self, event: tuple) -> None:
        """Handle an event from the router.

        State machine:
        - "request_headers" + "request" -> store pending request
        - "response_headers" -> store response metadata
        - "response_event" -> accumulate in response_events list
        - "response_done" -> reconstruct complete message, build HAR entry

        Errors are logged but never crash the router.
        """
        try:
            self._handle(event)
        except Exception as e:
            import traceback

            sys.stderr.write(f"[har] error: {e}\n")
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()

    def _handle(self, event: tuple) -> None:
        """Internal event handler - may raise exceptions."""
        kind = event[0]

        if kind == "request_headers":
            # Store request headers
            self.pending_request_headers = event[1]
            self.request_start_time = datetime.now(timezone.utc)

        elif kind == "request":
            # Store request body
            self.pending_request = event[1]

        elif kind == "response_headers":
            # Store response status and headers
            self.response_status = event[1]
            self.response_headers = event[2]

        elif kind == "response_event":
            # Accumulate SSE event
            _event_type, event_data = event[1], event[2]
            self.response_events.append(event_data)

        elif kind == "response_done":
            # Complete - reconstruct message and write HAR entry
            self._commit_entry()

    def _commit_entry(self) -> None:
        """Reconstruct complete message and write HAR entry to disk immediately."""
        if not self.pending_request or not self.response_events:
            return

        try:
            # Reconstruct complete message from events
            complete_message = reconstruct_message_from_events(self.response_events)

            # Calculate timing
            end_time = datetime.now(timezone.utc)
            time_ms = (
                (end_time - self.request_start_time).total_seconds() * 1000
                if self.request_start_time
                else 0.0
            )

            # Build HAR request/response
            har_request = build_har_request(
                method="POST",
                url="https://api.anthropic.com/v1/messages",
                headers=self.pending_request_headers or {},
                body=self.pending_request,
            )

            har_response = build_har_response(
                status=self.response_status or 200,
                headers=self.response_headers or {},
                complete_message=complete_message,
                time_ms=time_ms,
            )

            # Create HAR entry
            entry = {
                "startedDateTime": self.request_start_time.isoformat()
                if self.request_start_time
                else datetime.now(timezone.utc).isoformat(),
                "time": time_ms,
                "request": har_request,
                "response": har_response,
                "cache": {},
                "timings": {
                    "send": 0,
                    "wait": time_ms,
                    "receive": 0,
                },
            }

            # Serialize entry (compact JSON, no indent)
            entry_json = json.dumps(entry, ensure_ascii=False)

            # Seek to entries end position and overwrite footer
            self._file.seek(self._entries_end_pos)

            # Write entry with comma separator (if not first)
            if self._first_entry:
                self._file.write(f"\n{entry_json}")
                self._first_entry = False
            else:
                self._file.write(f",\n{entry_json}")

            # Update entries end position
            self._entries_end_pos = self._file.tell()

            # Write footer to maintain valid HAR
            self._file.write("\n]}}")
            self._file.flush()

            self._entry_count += 1

        except Exception as e:
            # Skip bad entries without corrupting file
            sys.stderr.write(f"[har] error serializing entry: {e}\n")
            sys.stderr.flush()

        # Clear state for next request
        self.pending_request = None
        self.pending_request_headers = None
        self.response_status = None
        self.response_headers = None
        self.response_events = []
        self.request_start_time = None

    def close(self) -> None:
        """Close file handle - file is already valid HAR."""
        try:
            self._file.close()
        except Exception as e:
            sys.stderr.write(f"[har] error closing file: {e}\n")
            sys.stderr.flush()
