"""HAR recording subscriber for HTTP Archive format output.

Accumulates streaming SSE events and reconstructs complete HTTP request/response
pairs in HAR 1.2 format for replay and analysis in standard tools.
"""

import json
import os
import sys
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
import traceback

from cc_dump.event_types import (
    PipelineEvent,
    PipelineEventKind,
    ResponseCompleteEvent,
    RequestHeadersEvent,
    RequestBodyEvent,
    ResponseHeadersEvent,
)
from cc_dump.side_channel_marker import extract_marker


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


@dataclass
class _PendingExchange:
    """Per-request pending state used by HARRecordingSubscriber."""

    request_body: dict | None = None
    request_headers: dict | None = None
    response_status: int | None = None
    response_headers: dict | None = None
    complete_message: dict | None = None
    request_start_time: datetime | None = None



class HARRecordingSubscriber:
    """Subscriber that accumulates events and writes HAR entries incrementally.

    This is a DirectSubscriber-style component that runs inline in the router
    thread. It writes each complete HAR entry immediately to disk, so the file
    is always valid HAR JSON and close() is instant.

    File creation is deferred until the first entry is committed, so sessions
    with no API traffic produce no file at all.
    """

    def __init__(self, path: str):
        """Initialize HAR recorder. File is NOT created until first entry.

        Args:
            path: Output file path for HAR file
        """
        self.path = path

        # [LAW:one-source-of-truth] Request-scoped pending exchange state.
        self._pending_by_request: OrderedDict[str, _PendingExchange] = OrderedDict()
        self._max_pending_requests = self._read_max_pending_requests()

        # Diagnostic counters for investigation if something goes wrong
        self._events_received: dict[str, int] = {}

        # Lazy file init — _file is None until first entry
        self._file = None
        self._entries_end_pos = 0
        self._first_entry = True
        self._entry_count = 0

    def _read_max_pending_requests(self) -> int:
        """Read bounded pending-request cap from env with safe fallback."""
        raw = str(os.environ.get("CC_DUMP_HAR_MAX_PENDING", "256") or "").strip()
        try:
            parsed = int(raw)
        except ValueError:
            parsed = 256
        return max(1, parsed)

    def _prune_pending_requests(self) -> None:
        """Bound pending exchange map to prevent unbounded growth."""
        # // [LAW:single-enforcer] Pending request cap is enforced only here.
        while len(self._pending_by_request) > self._max_pending_requests:
            evicted_request_id, _ = self._pending_by_request.popitem(last=False)
            sys.stderr.write(
                f"[har] WARN: evicted incomplete pending request {evicted_request_id} "
                f"(max_pending={self._max_pending_requests})\n"
            )
            sys.stderr.flush()

    def _open_file(self) -> None:
        """Create the HAR file and write the header. Called on first entry only."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

        har_header = {
            "log": {
                "version": "1.2",
                "creator": {"name": "cc-dump", "version": "0.2.0"},
                "entries": [],
            }
        }
        header_json = json.dumps(har_header, ensure_ascii=False)
        preamble = header_json[:-3]  # Strip ]}} to get preamble through opening [

        self._file = open(self.path, "w", encoding="utf-8")
        self._file.write(preamble)
        self._entries_end_pos = self._file.tell()
        self._file.write("\n]}}")
        self._file.flush()

    def on_event(self, event: PipelineEvent) -> None:
        """Handle an event from the router.

        State machine:
        - request_headers + request -> store pending request
        - response_headers -> store response metadata
        - response_complete -> build HAR entry from complete message

        Errors are logged but never crash the router.
        """
        try:
            kind_name = event.kind.name
            self._events_received[kind_name] = self._events_received.get(kind_name, 0) + 1
            self._handle(event)
        except Exception as e:

            sys.stderr.write(f"[har] error: {e}\n")
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()

    def _handle(self, event: PipelineEvent) -> None:
        """Internal event handler - may raise exceptions."""
        kind = event.kind
        request_key = event.request_id or "__legacy__"
        pending = self._pending_by_request.get(request_key)
        if pending is None:
            pending = _PendingExchange()
            self._pending_by_request[request_key] = pending
            self._prune_pending_requests()
        else:
            self._pending_by_request.move_to_end(request_key)

        if kind == PipelineEventKind.REQUEST_HEADERS:
            assert isinstance(event, RequestHeadersEvent)
            pending.request_headers = event.headers
            pending.request_start_time = datetime.now(timezone.utc)

        elif kind == PipelineEventKind.REQUEST:
            assert isinstance(event, RequestBodyEvent)
            pending.request_body = event.body

        elif kind == PipelineEventKind.RESPONSE_HEADERS:
            assert isinstance(event, ResponseHeadersEvent)
            pending.response_status = event.status_code
            pending.response_headers = event.headers

        elif kind == PipelineEventKind.RESPONSE_COMPLETE:
            # [LAW:one-source-of-truth] Complete message from ResponseAssembler
            assert isinstance(event, ResponseCompleteEvent)
            pending.complete_message = event.body
            self._commit_entry(request_key)

    def _commit_entry(self, request_key: str) -> None:
        """Reconstruct complete message and write HAR entry to disk immediately."""
        pending = self._pending_by_request.get(request_key)
        if pending is None:
            return
        if not pending.request_body or not pending.complete_message:
            return

        # Lazy file creation — only when we have a real entry to write
        if self._file is None:
            self._open_file()

        try:
            complete_message = pending.complete_message

            # Calculate timing
            end_time = datetime.now(timezone.utc)
            time_ms = (
                (end_time - pending.request_start_time).total_seconds() * 1000
                if pending.request_start_time
                else 0.0
            )

            # Build HAR request/response
            har_request = build_har_request(
                method="POST",
                url="https://api.anthropic.com/v1/messages",
                headers=pending.request_headers or {},
                body=pending.request_body,
            )

            har_response = build_har_response(
                status=pending.response_status or 200,
                headers=pending.response_headers or {},
                complete_message=complete_message,
                time_ms=time_ms,
            )

            # Create HAR entry
            entry = {
                "startedDateTime": pending.request_start_time.isoformat()
                if pending.request_start_time
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
            marker = extract_marker(pending.request_body or {})
            if marker is not None:
                entry["comment"] = (
                    f"cc-dump side-channel run={marker.run_id} purpose={marker.purpose} "
                    f"prompt_version={marker.prompt_version} policy_version={marker.policy_version}"
                )
                # HAR allows custom fields using underscore prefix.
                entry["_cc_dump"] = {
                    "category": "side_channel",
                    "run_id": marker.run_id,
                    "purpose": marker.purpose,
                    "prompt_version": marker.prompt_version,
                    "policy_version": marker.policy_version,
                    "source_session_id": marker.source_session_id,
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

        # Clear state for this request.
        self._pending_by_request.pop(request_key, None)

    def close(self) -> None:
        """Close file handle and enforce non-empty invariant.

        If no entries were written, the file is deleted (if it exists) and a
        diagnostic message is emitted to stderr for investigation.
        """
        if self._file is None:
            # File was never opened — no entries, no file. Expected path for
            # sessions with no API traffic. Log quietly for diagnostics.
            if self._events_received:
                sys.stderr.write(
                    f"[har] WARN: {os.path.basename(self.path)} received events "
                    f"but wrote 0 HAR entries. Events: {self._events_received}. "
                    f"No file created at {self.path}\n"
                )
                sys.stderr.flush()
            return

        try:
            self._file.close()
        except Exception as e:
            sys.stderr.write(f"[har] error closing file: {e}\n")
            sys.stderr.flush()

        # Belt-and-suspenders: if file was opened but has 0 entries, something
        # is broken — the lazy init should prevent this. Delete and scream.
        if self._entry_count == 0:
            sys.stderr.write(
                f"\n{'='*72}\n"
                f"[har] FATAL: empty HAR file detected — deleting garbage\n"
                f"  path:    {self.path}\n"
                f"  entries: {self._entry_count}\n"
                f"  events:  {self._events_received}\n"
                f"  This should never happen with lazy file init.\n"
                f"  If you see this, the bug is in _commit_entry or _open_file.\n"
                f"{'='*72}\n\n"
            )
            sys.stderr.flush()
            try:
                os.unlink(self.path)
                sys.stderr.write(f"[har] deleted empty file: {self.path}\n")
                sys.stderr.flush()
            except OSError as e:
                sys.stderr.write(f"[har] failed to delete {self.path}: {e}\n")
                sys.stderr.flush()
