"""HTTP proxy handler — pure data source, no display logic.

Event Schema (THE CONTRACT)
===========================
All events are tuples emitted via event_queue.put(). Downstream consumers
(TUI event_handlers, SQLiteWriter, HAR recorder) subscribe via router.py.

    ("request", method, url, headers_dict, body_bytes)
        Every proxied request. headers_dict has sensitive headers stripped.
        body_bytes is raw bytes (may be empty for GET/HEAD/DELETE).

    ("response_start", status_code, headers_dict)
        Response metadata — emitted once per request, before body/SSE events.

    ("response_body", body_bytes, content_type)
        Complete non-streaming response body. Not emitted for SSE streams.

    ("sse_event", event_type_str, data_str)
        Individual SSE event from a text/event-stream response.
        event_type is from the `event:` field (empty string if absent).
        data is the raw data string (not parsed as JSON).

    ("response_done", duration_ms)
        Request/response cycle complete. duration_ms is wall-clock time.

    ("error", status_code, reason)
        HTTP error from upstream server.

    ("proxy_error", error_str)
        Internal proxy error (connection refused, timeout, etc.).

    ("log", method, path, status_str)
        Access log line (from BaseHTTPRequestHandler.log_message).
"""

import http.server
import ssl
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

# Headers to exclude from emitted events (security + noise reduction)
_EXCLUDED_HEADERS = frozenset({
    "authorization",
    "x-api-key",
    "cookie",
    "set-cookie",
    "host",
    "content-length",
    "transfer-encoding",
})


def _safe_headers(headers):
    """Filter out sensitive and noisy headers."""
    return {k: v for k, v in headers.items() if k.lower() not in _EXCLUDED_HEADERS}


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    target_host = "https://api.anthropic.com"
    event_queue = None  # set by cli.py before server starts

    def log_message(self, fmt, *args):
        self.event_queue.put(("log", self.command, self.path, args[0] if args else ""))

    def _proxy(self):
        start_time = time.monotonic()

        content_len = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_len) if content_len else b""

        # Detect proxy mode and determine target URL
        if self.path.startswith("http://") or self.path.startswith("https://"):
            # Forward proxy mode - absolute URI
            parsed = urlparse(self.path)
            # Upgrade to HTTPS for security
            url = self.path
            if url.startswith("http://"):
                url = "https://" + url[7:]
        else:
            # Reverse proxy mode - relative URI
            if not self.target_host:
                self.event_queue.put(("error", 500, "No target_host configured for reverse proxy mode"))
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"No target configured. Use --target or send absolute URIs.")
                return
            url = self.target_host + self.path

        # Emit request event for ALL requests
        safe_req_headers = _safe_headers(self.headers)
        self.event_queue.put(("request", self.command, url, safe_req_headers, body_bytes))

        # Forward request to upstream
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("host", "content-length")}
        headers["Content-Length"] = str(len(body_bytes))

        req = urllib.request.Request(url, data=body_bytes or None,
                                     headers=headers, method=self.command)
        try:
            ctx = ssl.create_default_context()
            resp = urllib.request.urlopen(req, context=ctx, timeout=300)
        except urllib.error.HTTPError as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            self.event_queue.put(("error", e.code, e.reason))
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() != "transfer-encoding":
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(e.read())
            self.event_queue.put(("response_done", duration_ms))
            return
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            self.event_queue.put(("proxy_error", str(e)))
            self.send_response(502)
            self.end_headers()
            self.event_queue.put(("response_done", duration_ms))
            return

        # Forward response headers to client
        self.send_response(resp.status)
        is_stream = False
        content_type = ""
        for k, v in resp.headers.items():
            if k.lower() == "transfer-encoding":
                continue
            if k.lower() == "content-type":
                content_type = v
                if "text/event-stream" in v:
                    is_stream = True
            self.send_header(k, v)
        self.end_headers()

        # Emit response_start for all responses
        safe_resp_headers = _safe_headers(resp.headers)
        self.event_queue.put(("response_start", resp.status, safe_resp_headers))

        if is_stream:
            self._stream_response(resp)
        else:
            data = resp.read()
            self.wfile.write(data)
            self.event_queue.put(("response_body", data, content_type))

        duration_ms = (time.monotonic() - start_time) * 1000
        self.event_queue.put(("response_done", duration_ms))

    def _stream_response(self, resp):
        """Parse W3C-standard SSE stream and emit events."""
        current_event_type = ""
        current_data_lines = []

        for raw_line in resp:
            self.wfile.write(raw_line)
            self.wfile.flush()

            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

            if not line:
                # Empty line = event boundary (W3C SSE spec)
                if current_data_lines:
                    data = "\n".join(current_data_lines)
                    self.event_queue.put(("sse_event", current_event_type, data))
                    current_data_lines = []
                    current_event_type = ""
                continue

            if line.startswith(":"):
                continue  # SSE comment line, ignore

            if line.startswith("event:"):
                current_event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_value = line[5:].lstrip(" ")  # "data: value" or "data:value"
                if data_value == "[DONE]":
                    break  # OpenAI/Claude convention for stream end
                current_data_lines.append(data_value)
            # Ignore id: and retry: fields (display-only proxy)

        # Flush any remaining buffered event
        if current_data_lines:
            data = "\n".join(current_data_lines)
            self.event_queue.put(("sse_event", current_event_type, data))

    def do_POST(self):
        self._proxy()

    def do_GET(self):
        self._proxy()

    def do_PUT(self):
        self._proxy()

    def do_DELETE(self):
        self._proxy()

    def do_PATCH(self):
        self._proxy()

    def do_HEAD(self):
        self._proxy()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()
