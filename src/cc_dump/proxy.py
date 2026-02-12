"""HTTP proxy handler — pure data source, no display logic."""

import http.server
import json
import ssl
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

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


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    target_host = None  # set by cli.py from --target arg before server starts
    event_queue = None  # set by cli.py before server starts

    def log_message(self, fmt, *args):
        self.event_queue.put(("log", self.command, self.path, args[0] if args else ""))

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
                    ("error", 500, "No target_host configured for reverse proxy mode")
                )
                self.send_response(500)
                self.end_headers()
                self.wfile.write(
                    b"No target configured. Use --target or send absolute URIs."
                )
                return
            url = self.target_host + self.path

        if body_bytes and request_path.startswith("/v1/messages"):
            try:
                body = json.loads(body_bytes)
                # Emit request headers before request body
                safe_req_headers = _safe_headers(self.headers)
                self.event_queue.put(("request_headers", safe_req_headers))
                self.event_queue.put(("request", body))
            except json.JSONDecodeError as e:
                sys.stderr.write(f"[proxy] malformed request JSON: {e}\n")
                sys.stderr.flush()

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
            self.event_queue.put(("error", e.code, e.reason))
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() != "transfer-encoding":
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(e.read())
            return
        except Exception as e:
            self.event_queue.put(("proxy_error", str(e)))
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
            self.event_queue.put(("response_headers", resp.status, safe_resp_headers))
            self._stream_response(resp)
        else:
            data = resp.read()
            self.wfile.write(data)

    def _stream_response(self, resp):
        # Note: response_start event has been replaced by response_headers above
        # Old code: self.event_queue.put(("response_start",))

        for raw_line in resp:
            self.wfile.write(raw_line)
            self.wfile.flush()

            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line.startswith("data: "):
                continue
            json_str = line[6:]
            if json_str == "[DONE]":
                break

            try:
                event = json.loads(json_str)
            except json.JSONDecodeError as e:
                sys.stderr.write(f"[proxy] malformed SSE JSON: {e}\n")
                sys.stderr.flush()
                continue

            event_type = event.get("type", "")
            self.event_queue.put(("response_event", event_type, event))

        self.event_queue.put(("response_done",))

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
