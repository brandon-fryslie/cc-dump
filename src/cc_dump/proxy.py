"""HTTP proxy handler — pure data source, no display logic."""

import http.server
import json
import ssl
import sys
import uuid
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse

from cc_dump.event_types import (
    ErrorEvent,
    LogEvent,
    ProxyErrorEvent,
    RequestBodyEvent,
    RequestHeadersEvent,
    ResponseDoneEvent,
    ResponseHeadersEvent,
    ResponseSSEEvent,
    parse_sse_event,
)

# Headers to exclude from emitted events (security + noise reduction)
_EXCLUDED_HEADERS = frozenset(
    {
        "authorization",
        "x-api-key",
        "cookie",
        "set-cookie",
        "host",
        "content-length",
        "transfer-encoding",
    }
)


def _safe_headers(headers):
    """Filter out sensitive and noisy headers."""
    return {k: v for k, v in headers.items() if k.lower() not in _EXCLUDED_HEADERS}


# ─── Request Pipeline ────────────────────────────────────────────────────────
# // [LAW:dataflow-not-control-flow] Transforms compose by chaining; interceptors compose by first-match.


@dataclass
class RequestPipeline:
    """Composable request processing: transforms modify, interceptors short-circuit.

    Phase 1 — transforms run unconditionally, each sees the output of the previous.
    Phase 2 — interceptors run after transforms. First non-None return wins.
    """

    transforms: list[Callable[[dict, str], tuple[dict, str]]] = field(default_factory=list)
    interceptors: list[Callable[[dict], str | None]] = field(default_factory=list)

    def process(self, body: dict, url: str) -> tuple[dict, str, str | None]:
        """Run pipeline. Returns (body, url, intercept_response_or_none)."""
        for transform in self.transforms:
            body, url = transform(body, url)
        for interceptor in self.interceptors:
            response = interceptor(body)
            if response is not None:
                return body, url, response
        return body, url, None


def _build_synthetic_sse_bytes(response_text: str, model: str = "synthetic") -> bytes:
    """Build complete SSE byte stream for a synthetic response.

    // [LAW:dataflow-not-control-flow] Pure function — data in, bytes out.
    """
    msg_id = "msg_synthetic_" + uuid.uuid4().hex[:12]
    chunks = []

    # message_start
    chunks.append(
        _sse_line(
            {
                "type": "message_start",
                "message": {
                    "id": msg_id,
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            }
        )
    )

    # content_block_start
    chunks.append(
        _sse_line(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            }
        )
    )

    # content_block_delta (full text in one delta)
    chunks.append(
        _sse_line(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": response_text},
            }
        )
    )

    # content_block_stop
    chunks.append(_sse_line({"type": "content_block_stop", "index": 0}))

    # message_delta
    chunks.append(
        _sse_line(
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 1},
            }
        )
    )

    # message_stop
    chunks.append(_sse_line({"type": "message_stop"}))

    # [DONE]
    chunks.append(b"data: [DONE]\n\n")

    return b"".join(chunks)


def _sse_line(event: dict) -> bytes:
    """Format a single SSE data line."""
    return b"data: " + json.dumps(event).encode() + b"\n\n"


class StreamSink:
    """Consumer of an SSE stream. Each method is called in its own error boundary."""

    def on_raw(self, data: bytes) -> None:
        pass

    def on_event(self, event_type: str, event: dict) -> None:
        pass

    def on_done(self) -> None:
        pass


class ClientSink(StreamSink):
    """Writes raw SSE bytes back to the HTTP client."""

    def __init__(self, wfile):
        self._wfile = wfile

    def on_raw(self, data):
        self._wfile.write(data)
        self._wfile.flush()


class EventQueueSink(StreamSink):
    """Emits parsed events to the TUI event queue."""

    def __init__(self, queue):
        self._queue = queue

    def on_event(self, event_type, event):
        try:
            sse = parse_sse_event(event_type, event)
        except ValueError:
            return
        self._queue.put(ResponseSSEEvent(sse_event=sse))

    def on_done(self):
        self._queue.put(ResponseDoneEvent())


def _fan_out_sse(resp, sinks):
    """Drive an SSE response to multiple sinks with per-sink error isolation."""
    # [LAW:dataflow-not-control-flow] All sinks called unconditionally
    try:
        for raw_line in resp:
            for sink in sinks:
                try:
                    sink.on_raw(raw_line)
                except Exception:
                    pass

            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line.startswith("data: "):
                continue
            json_str = line[6:]
            if json_str == "[DONE]":
                break

            try:
                event = json.loads(json_str)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")
            for sink in sinks:
                try:
                    sink.on_event(event_type, event)
                except Exception:
                    pass
    finally:
        for sink in sinks:
            try:
                sink.on_done()
            except Exception:
                pass


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    target_host = None  # set by cli.py from --target arg before server starts
    event_queue = None  # set by cli.py before server starts
    request_pipeline = None  # set by cli.py before server starts

    def log_message(self, fmt, *args):
        self.event_queue.put(LogEvent(method=self.command, path=self.path, status=args[0] if args else ""))

    def _proxy(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_len) if content_len else b""

        # Detect proxy mode and determine target URL
        if self.path.startswith("http://") or self.path.startswith("https://"):
            # Forward proxy mode - absolute URI
            parsed = urlparse(self.path)
            request_path = parsed.path
            # Upgrade to HTTPS for security
            url = self.path
            if url.startswith("http://"):
                url = "https://" + url[7:]
        else:
            # Reverse proxy mode - relative URI
            request_path = self.path
            if not self.target_host:
                self.event_queue.put(
                    ErrorEvent(code=500, reason="No target_host configured for reverse proxy mode")
                )
                self.send_response(500)
                self.end_headers()
                self.wfile.write(
                    b"No target configured. Use --target or send absolute URIs."
                )
                return
            url = self.target_host + self.path

        body = None
        if body_bytes and request_path.startswith("/v1/messages"):
            try:
                body = json.loads(body_bytes)
                # Emit request headers before request body (TUI sees original request)
                safe_req_headers = _safe_headers(self.headers)
                self.event_queue.put(RequestHeadersEvent(headers=safe_req_headers))
                self.event_queue.put(RequestBodyEvent(body=body))
            except json.JSONDecodeError as e:
                sys.stderr.write(f"[proxy] malformed request JSON: {e}\n")
                sys.stderr.flush()

        # Pipeline processing — transforms modify body/url, interceptors short-circuit
        if body is not None and self.request_pipeline is not None:
            body, url, intercept_response = self.request_pipeline.process(body, url)
            if intercept_response is not None:
                self._send_synthetic_response(intercept_response, body)
                return
            body_bytes = json.dumps(body).encode()  # re-serialize for upstream

        # Forward
        headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower() not in ("host", "content-length")
        }
        headers["Content-Length"] = str(len(body_bytes))

        req = urllib.request.Request(
            url, data=body_bytes or None, headers=headers, method=self.command
        )
        try:
            ctx = ssl.create_default_context()
            resp = urllib.request.urlopen(req, context=ctx, timeout=300)
        except urllib.error.HTTPError as e:
            self.event_queue.put(ErrorEvent(code=e.code, reason=e.reason))
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() != "transfer-encoding":
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(e.read())
            return
        except Exception as e:
            self.event_queue.put(ProxyErrorEvent(error=str(e)))
            self.send_response(502)
            self.end_headers()
            return

        self.send_response(resp.status)
        is_stream = False
        for k, v in resp.headers.items():
            if k.lower() == "transfer-encoding":
                continue
            if k.lower() == "content-type" and "text/event-stream" in v:
                is_stream = True
            self.send_header(k, v)
        self.end_headers()

        if is_stream:
            # Emit response headers before streaming
            safe_resp_headers = _safe_headers(resp.headers)
            self.event_queue.put(ResponseHeadersEvent(status_code=resp.status, headers=safe_resp_headers))
            self._stream_response(resp)
        else:
            data = resp.read()
            self.wfile.write(data)

    def _send_synthetic_response(self, response_text: str, body: dict) -> None:
        """Send a synthetic SSE response and emit pipeline events.

        Used when an interceptor short-circuits the request.
        """
        model = body.get("model", "synthetic")
        if not isinstance(model, str):
            model = "synthetic"

        sse_bytes = _build_synthetic_sse_bytes(response_text, model)

        # Send HTTP response to client
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(sse_bytes)
        self.wfile.flush()

        # Emit events to TUI pipeline (same path as real responses)
        self.event_queue.put(
            ResponseHeadersEvent(
                status_code=200,
                headers={"content-type": "text/event-stream"},
            )
        )
        # Parse our own SSE bytes through the event queue sink
        for line in sse_bytes.split(b"\n"):
            line_str = line.decode("utf-8", errors="replace").rstrip("\r")
            if not line_str.startswith("data: "):
                continue
            json_str = line_str[6:]
            if json_str == "[DONE]":
                break
            try:
                event = json.loads(json_str)
            except json.JSONDecodeError:
                continue
            event_type = event.get("type", "")
            try:
                sse = parse_sse_event(event_type, event)
                self.event_queue.put(ResponseSSEEvent(sse_event=sse))
            except ValueError:
                pass
        self.event_queue.put(ResponseDoneEvent())

    def _stream_response(self, resp):
        _fan_out_sse(resp, [ClientSink(self.wfile), EventQueueSink(self.event_queue)])

    def do_POST(self):
        self._proxy()

    def do_GET(self):
        self._proxy()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()
