"""HTTP proxy handler — pure data source, no display logic."""

import http.server
import json
import ssl
import urllib.error
import urllib.request


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    target_host = "https://api.anthropic.com"
    event_queue = None  # set by cli.py before server starts

    def log_message(self, fmt, *args):
        self.event_queue.put(("log", self.command, self.path, args[0] if args else ""))

    def _proxy(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_len) if content_len else b""

        if body_bytes and self.path.startswith("/v1/messages"):
            try:
                body = json.loads(body_bytes)
                self.event_queue.put(("request", body))
            except json.JSONDecodeError:
                pass

        # Forward
        url = self.target_host + self.path
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("host", "content-length")}
        headers["Content-Length"] = str(len(body_bytes))

        req = urllib.request.Request(url, data=body_bytes or None,
                                     headers=headers, method=self.command)
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
            self._stream_response(resp)
        else:
            data = resp.read()
            self.wfile.write(data)

    def _stream_response(self, resp):
        self.event_queue.put(("response_start",))

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
            except json.JSONDecodeError:
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
