"""Smoke tests for generic HTTP proxy event emission.

Verifies the proxy event schema contract defined in proxy.py docstring.
Uses a local test HTTP server to avoid network dependencies.
"""

import http.server
import json
import queue
import threading
import time

import pytest

from surview.proxy import ProxyHandler


# ── Local test HTTP server ──────────────────────────────────────────────────


class TestHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Simple handler that echoes request info back in JSON."""

    def log_message(self, fmt, *args):
        pass  # suppress logs

    def do_GET(self):
        body = json.dumps({
            "method": "GET",
            "path": self.path,
            "headers": dict(self.headers),
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        request_body = self.rfile.read(content_len) if content_len else b""
        body = json.dumps({
            "method": "POST",
            "path": self.path,
            "body": request_body.decode("utf-8", errors="replace"),
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self):
        self.do_POST()  # same echo behavior

    def do_DELETE(self):
        self.send_response(204)
        self.end_headers()

    def do_PATCH(self):
        self.do_POST()

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()


class SSEHandler(http.server.BaseHTTPRequestHandler):
    """Handler that responds with SSE stream."""

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        events = [
            b"event: message_start\ndata: {\"type\": \"start\"}\n\n",
            b"data: {\"type\": \"delta\", \"text\": \"hello\"}\n\n",
            b"event: message_stop\ndata: {\"type\": \"stop\"}\n\n",
            b"data: [DONE]\n\n",
        ]
        for event in events:
            self.wfile.write(event)
            self.wfile.flush()


class W3CSSEHandler(http.server.BaseHTTPRequestHandler):
    """Handler that responds with W3C-standard SSE including comments and multi-line data."""

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        lines = [
            b": this is a comment\n",
            b"event: update\n",
            b"data: line1\n",
            b"data: line2\n",
            b"\n",  # event boundary
            b"data: simple\n",
            b"\n",  # event boundary
        ]
        for line in lines:
            self.wfile.write(line)
            self.wfile.flush()


class ErrorHandler(http.server.BaseHTTPRequestHandler):
    """Handler that returns 500 errors."""

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        self.send_response(500)
        self.send_header("Content-Type", "text/plain")
        body = b"Internal Server Error"
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ── Fixtures ────────────────────────────────────────────────────────────────


def _start_server(handler_class):
    """Start a local HTTP server on a random port, return (server, port)."""
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_class)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def _make_proxy(target_port):
    """Create a proxy server pointing at a local target, return (server, port, event_queue)."""
    eq = queue.Queue()

    class TestProxy(ProxyHandler):
        target_host = f"http://127.0.0.1:{target_port}"
        event_queue = eq

    server = http.server.HTTPServer(("127.0.0.1", 0), TestProxy)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, eq


def _drain_events(eq, timeout=2.0):
    """Drain all events from queue, return as list."""
    events = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            events.append(eq.get(timeout=0.1))
        except queue.Empty:
            if events:
                break
    return events


def _send_request(proxy_port, method="GET", path="/test", body=None, headers=None):
    """Send an HTTP request through the proxy."""
    import urllib.request
    url = f"http://127.0.0.1:{proxy_port}{path}"
    data = body.encode() if isinstance(body, str) else body
    req = urllib.request.Request(url, data=data, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        resp.read()
        return resp
    except urllib.error.HTTPError as e:
        e.read()
        return e


# ── Tests ───────────────────────────────────────────────────────────────────


class TestProxyEventEmission:
    """Verify proxy emits events per the documented contract."""

    def test_get_request_emits_events(self):
        """GET request produces request, response_start, response_body, response_done."""
        target, target_port = _start_server(TestHTTPHandler)
        proxy, proxy_port, eq = _make_proxy(target_port)
        try:
            _send_request(proxy_port, "GET", "/test")
            events = _drain_events(eq)

            types = [e[0] for e in events]
            assert "request" in types
            assert "response_start" in types
            assert "response_body" in types
            assert "response_done" in types

            # Verify request event shape
            req_event = next(e for e in events if e[0] == "request")
            assert req_event[1] == "GET"  # method
            assert "/test" in req_event[2]  # url
            assert isinstance(req_event[3], dict)  # headers
            assert isinstance(req_event[4], bytes)  # body

            # Verify response_start
            resp_start = next(e for e in events if e[0] == "response_start")
            assert resp_start[1] == 200  # status_code
            assert isinstance(resp_start[2], dict)  # headers

            # Verify response_body
            resp_body = next(e for e in events if e[0] == "response_body")
            assert isinstance(resp_body[1], bytes)  # body
            assert "application/json" in resp_body[2]  # content_type

            # Verify response_done with timing
            resp_done = next(e for e in events if e[0] == "response_done")
            assert resp_done[1] > 0  # duration_ms > 0

        finally:
            proxy.shutdown()
            target.shutdown()

    def test_post_with_body(self):
        """POST body is captured as raw bytes in request event."""
        target, target_port = _start_server(TestHTTPHandler)
        proxy, proxy_port, eq = _make_proxy(target_port)
        try:
            body = '{"key": "value"}'
            _send_request(proxy_port, "POST", "/api", body=body,
                         headers={"Content-Type": "application/json"})
            events = _drain_events(eq)

            req_event = next(e for e in events if e[0] == "request")
            assert req_event[1] == "POST"
            assert req_event[4] == body.encode()  # raw bytes

        finally:
            proxy.shutdown()
            target.shutdown()

    def test_all_http_methods(self):
        """PUT, DELETE, PATCH, HEAD all emit request events."""
        target, target_port = _start_server(TestHTTPHandler)
        proxy, proxy_port, eq = _make_proxy(target_port)
        try:
            for method in ("PUT", "DELETE", "PATCH", "HEAD"):
                # Drain any leftover events
                _drain_events(eq, timeout=0.2)

                body = '{"data": 1}' if method in ("PUT", "PATCH") else None
                headers = {"Content-Type": "application/json"} if body else None
                _send_request(proxy_port, method, f"/{method.lower()}", body=body, headers=headers)
                events = _drain_events(eq)

                types = [e[0] for e in events]
                assert "request" in types, f"No request event for {method}"
                req_event = next(e for e in events if e[0] == "request")
                assert req_event[1] == method

        finally:
            proxy.shutdown()
            target.shutdown()

    def test_no_path_filter(self):
        """Events emitted for ANY path, not just /v1/messages."""
        target, target_port = _start_server(TestHTTPHandler)
        proxy, proxy_port, eq = _make_proxy(target_port)
        try:
            for path in ("/api/users", "/health", "/v2/chat", "/anything"):
                _drain_events(eq, timeout=0.2)
                _send_request(proxy_port, "GET", path)
                events = _drain_events(eq)
                types = [e[0] for e in events]
                assert "request" in types, f"No request event for path {path}"

        finally:
            proxy.shutdown()
            target.shutdown()


class TestSSEParsing:
    """Verify SSE stream parsing per W3C spec."""

    def test_sse_stream_emits_events(self):
        """SSE stream produces sse_event events (not response_body)."""
        target, target_port = _start_server(SSEHandler)
        proxy, proxy_port, eq = _make_proxy(target_port)
        try:
            _send_request(proxy_port, "GET", "/stream")
            events = _drain_events(eq)

            types = [e[0] for e in events]
            assert "sse_event" in types
            assert "response_body" not in types  # SSE streams don't emit response_body

            sse_events = [e for e in events if e[0] == "sse_event"]
            assert len(sse_events) >= 2  # at least the non-[DONE] events

        finally:
            proxy.shutdown()
            target.shutdown()

    def test_sse_event_type_parsed(self):
        """SSE `event:` field is captured as event_type."""
        target, target_port = _start_server(SSEHandler)
        proxy, proxy_port, eq = _make_proxy(target_port)
        try:
            _send_request(proxy_port, "GET", "/stream")
            events = _drain_events(eq)
            sse_events = [e for e in events if e[0] == "sse_event"]

            # First event has event: message_start
            assert sse_events[0][1] == "message_start"
            assert '"type": "start"' in sse_events[0][2]

            # Second event has no event: field (empty string)
            assert sse_events[1][1] == ""
            assert '"type": "delta"' in sse_events[1][2]

        finally:
            proxy.shutdown()
            target.shutdown()

    def test_w3c_sse_multiline_data(self):
        """Multi-line data: fields are joined with newlines per W3C spec."""
        target, target_port = _start_server(W3CSSEHandler)
        proxy, proxy_port, eq = _make_proxy(target_port)
        try:
            _send_request(proxy_port, "GET", "/stream")
            events = _drain_events(eq)
            sse_events = [e for e in events if e[0] == "sse_event"]

            # First event: event: update, data: line1\nline2
            assert sse_events[0][1] == "update"
            assert sse_events[0][2] == "line1\nline2"

            # Second event: no event type, data: simple
            assert sse_events[1][1] == ""
            assert sse_events[1][2] == "simple"

        finally:
            proxy.shutdown()
            target.shutdown()

    def test_sse_comments_ignored(self):
        """SSE comment lines (starting with :) are ignored."""
        target, target_port = _start_server(W3CSSEHandler)
        proxy, proxy_port, eq = _make_proxy(target_port)
        try:
            _send_request(proxy_port, "GET", "/stream")
            events = _drain_events(eq)
            sse_events = [e for e in events if e[0] == "sse_event"]

            # No event should contain "this is a comment"
            for evt in sse_events:
                assert "comment" not in evt[2]

        finally:
            proxy.shutdown()
            target.shutdown()


class TestTiming:
    """Verify request timing is captured."""

    def test_response_done_has_timing(self):
        """response_done event includes duration in milliseconds."""
        target, target_port = _start_server(TestHTTPHandler)
        proxy, proxy_port, eq = _make_proxy(target_port)
        try:
            _send_request(proxy_port, "GET", "/test")
            events = _drain_events(eq)

            done_event = next(e for e in events if e[0] == "response_done")
            assert isinstance(done_event[1], float)
            assert done_event[1] > 0

        finally:
            proxy.shutdown()
            target.shutdown()
