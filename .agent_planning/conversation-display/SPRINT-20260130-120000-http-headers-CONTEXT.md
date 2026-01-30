# Implementation Context: http-headers
Generated: 2026-01-30-120000
Source: EVALUATION-20260130.md

## File: src/cc_dump/proxy.py

### 1. Emit request headers event (line 42-45)

Current:
```python
        if body_bytes and request_path.startswith("/v1/messages"):
            try:
                body = json.loads(body_bytes)
                self.event_queue.put(("request", body))
            except json.JSONDecodeError:
                pass
```

Add header emission before the request event:
```python
        if body_bytes and request_path.startswith("/v1/messages"):
            try:
                body = json.loads(body_bytes)
                # Emit sanitized headers
                safe_headers = {k: v for k, v in self.headers.items()
                                if k.lower() not in _EXCLUDED_HEADERS}
                self.event_queue.put(("request_headers", safe_headers))
                self.event_queue.put(("request", body))
            except json.JSONDecodeError:
                pass
```

### 2. Emit response headers event (line 74-82, around line 91)

Current response start:
```python
        self.send_response(resp.status)
        is_stream = False
        for k, v in resp.headers.items():
            ...
        self.end_headers()

        if is_stream:
            self._stream_response(resp)
```

Add header emission before streaming/reading:
```python
        if is_stream:
            # Emit response headers
            safe_headers = {k: v for k, v in resp.headers.items()
                            if k.lower() not in _EXCLUDED_HEADERS}
            self.event_queue.put(("response_headers", resp.status, safe_headers))
            self._stream_response(resp)
```

### 3. Define excluded headers constant (top of file)

```python
_EXCLUDED_HEADERS = frozenset({
    "authorization", "x-api-key", "cookie", "set-cookie",
    "host", "content-length", "transfer-encoding",
})
```

## File: src/cc_dump/formatting.py

### 4. Add HttpHeadersBlock (after HeaderBlock, around line 39)

```python
@dataclass
class HttpHeadersBlock(FormattedBlock):
    """HTTP request or response headers."""
    headers: dict = field(default_factory=dict)
    header_type: str = "request"  # "request" or "response"
    status_code: int = 0  # only for response
```

### 5. Add formatting functions (after format_response_event)

```python
def format_request_headers(headers_dict: dict) -> list:
    """Format HTTP request headers as blocks."""
    if not headers_dict:
        return []
    return [HttpHeadersBlock(headers=headers_dict, header_type="request")]


def format_response_headers(status_code: int, headers_dict: dict) -> list:
    """Format HTTP response headers as blocks."""
    if not headers_dict:
        return []
    return [HttpHeadersBlock(headers=headers_dict, header_type="response", status_code=status_code)]
```

## File: src/cc_dump/tui/rendering.py

### 6. Add HttpHeadersBlock to imports (line 10-17)

Add `HttpHeadersBlock` to the import list from `cc_dump.formatting`.

### 7. Add renderer function (after _render_header, around line 88)

```python
def _render_http_headers(block: HttpHeadersBlock, filters: dict) -> Text | None:
    """Render HTTP headers as key-value pairs."""
    if not filters.get("headers", False):
        return None
    t = Text()
    label = "Request Headers" if block.header_type == "request" else f"Response Headers ({block.status_code})"
    t.append("  {}:\n".format(label), style="dim bold")
    for key, value in sorted(block.headers.items()):
        t.append("    {}: ".format(key), style="dim cyan")
        t.append("{}\n".format(value), style="dim")
    return _add_filter_indicator(t, "headers")
```

### 8. Add to BLOCK_RENDERERS (line 242-263)

```python
    HttpHeadersBlock: _render_http_headers,
```

### 9. Add to BLOCK_FILTER_KEY (line 269-290)

```python
    HttpHeadersBlock: "headers",
```

## File: src/cc_dump/tui/event_handlers.py

### 10. Add handler functions

```python
def handle_request_headers(event, state, widgets, app_state, log_fn):
    """Handle request_headers event."""
    headers_dict = event[1]
    try:
        blocks = cc_dump.formatting.format_request_headers(headers_dict)
        if blocks:
            conv = widgets["conv"]
            conv.add_turn(blocks)
    except Exception as e:
        log_fn("ERROR", f"Error handling request headers: {e}")
    return app_state


def handle_response_headers(event, state, widgets, app_state, log_fn):
    """Handle response_headers event."""
    status_code, headers_dict = event[1], event[2]
    try:
        blocks = cc_dump.formatting.format_response_headers(status_code, headers_dict)
        if blocks:
            streaming = widgets["streaming"]
            filters = widgets["filters"]
            for block in blocks:
                streaming.append_block(block, filters)
    except Exception as e:
        log_fn("ERROR", f"Error handling response headers: {e}")
    return app_state
```

## File: src/cc_dump/tui/app.py

### 11. Add event dispatch for new events

In `_handle_event_inner()` (the event dispatch method), add cases for new event types. The exact location depends on the dispatch pattern (match/case or if/elif chain). Look for:
```python
if event[0] == "request":
    ...
```
Add before the catch-all:
```python
elif event[0] == "request_headers":
    handle_request_headers(event, state, widgets, app_state, log_fn)
elif event[0] == "response_headers":
    handle_response_headers(event, state, widgets, app_state, log_fn)
```

## Adjacent Patterns
- `("request", body)` event emission at proxy.py:45 -- existing event emission pattern
- `("response_start",)` event at proxy.py:91 -- existing response start event
- `HeaderBlock` rendering at rendering.py:74-87 -- existing header rendering under "headers" filter
- `BLOCK_RENDERERS` dict pattern at rendering.py:242 -- registry for new block types
- `handle_request()` in event_handlers.py:12-44 -- existing event handler pattern

## Gotchas
- `self.headers` in proxy.py is an `http.client.HTTPMessage` instance (from BaseHTTPRequestHandler). Iterating with `.items()` gives all headers. Some headers may appear multiple times -- `.items()` returns all values.
- `resp.headers` from `urllib.request.urlopen` is also `http.client.HTTPMessage`.
- The request headers event is emitted BEFORE the request event. This means the headers turn will appear above the request turn in ConversationView. This is the desired order.
- Response headers are emitted BEFORE `_stream_response()`, so they go into StreamingRichLog before any SSE events. This is correct ordering.
- The app.py dispatch must handle unknown event types gracefully (it currently does -- unknown events are silently ignored via the if/elif chain).
