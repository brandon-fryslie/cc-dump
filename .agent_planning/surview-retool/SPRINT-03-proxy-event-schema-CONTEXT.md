# Implementation Context: Sprint 3 - Proxy + Event Schema

## proxy.py Rewrite Plan

### Current structure (keep)
- BaseHTTPRequestHandler subclass
- target_host class variable for reverse proxy
- event_queue class variable for event emission
- _proxy() method that forwards requests and responses
- SSL context creation
- Forward proxy mode (absolute URI detection) and reverse proxy mode

### Changes needed

#### 1. Remove path filter (line 59)
```python
# BEFORE:
if body_bytes and request_path.startswith("/v1/messages"):
    ...emit events...

# AFTER:
# Always emit events, regardless of path
self.event_queue.put(("request", self.command, url, safe_headers, body_bytes))
```

#### 2. Add all HTTP method handlers
```python
def do_PUT(self): self._proxy()
def do_DELETE(self): self._proxy()
def do_PATCH(self): self._proxy()
def do_HEAD(self): self._proxy()
```

#### 3. Capture non-streaming response bodies
```python
# BEFORE (lines 110-112):
data = resp.read()
self.wfile.write(data)
# (no events emitted!)

# AFTER:
data = resp.read()
self.wfile.write(data)
content_type = resp.headers.get("content-type", "")
self.event_queue.put(("response_start", resp.status, safe_resp_headers))
self.event_queue.put(("response_body", data, content_type))
self.event_queue.put(("response_done", duration_ms))
```

#### 4. Add timing
```python
import time

def _proxy(self):
    start_time = time.monotonic()
    # ... existing forwarding logic ...
    duration_ms = (time.monotonic() - start_time) * 1000
```

#### 5. Rewrite SSE parsing (_stream_response)
```python
def _stream_response(self, resp):
    """Parse W3C-standard SSE stream."""
    current_event_type = ""
    current_data_lines = []

    for raw_line in resp:
        self.wfile.write(raw_line)
        self.wfile.flush()

        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

        if not line:
            # Empty line = event boundary (W3C spec)
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
                break  # OpenAI/Claude convention
            current_data_lines.append(data_value)
        # Ignore id: and retry: fields

    # Flush any remaining buffered event
    if current_data_lines:
        data = "\n".join(current_data_lines)
        self.event_queue.put(("sse_event", current_event_type, data))
```

#### 6. Merge request_headers into request event
Current: two events `("request_headers", headers)` + `("request", body_dict)`
New: single event `("request", method, url, headers, body_bytes)`

This eliminates the "pending_request_headers" state management in event_handlers.py.

## Downstream Impact
- event_handlers.py: all handlers need signature updates (Sprint 5)
- store.py: on_event() switches on new event types (Sprint 6)
- har_recorder.py: on_event() switches on new event types (Sprint 7)
- formatting.py: format functions receive new data shapes (Sprint 4)
