# Definition of Done: Sprint 3 - Proxy + Event Schema

## Exit Criteria
1. proxy.py emits events for ALL HTTP methods (GET, POST, PUT, DELETE, PATCH, HEAD)
2. proxy.py emits events for non-streaming response bodies
3. proxy.py parses SSE streams and emits ("sse_event", ...) events
4. No path filtering — every request through the proxy generates events
5. Event schema documented in proxy.py header comments
6. Smoke test passes: start proxy, send HTTP request, verify events emitted

## Smoke Test
```python
# test_proxy_generic.py
def test_proxy_emits_events_for_any_request():
    """Start proxy, send a GET request, verify request+response events."""
    # Start proxy on random port
    # Send: GET http://httpbin.org/get through proxy
    # Assert: received ("request", "GET", url, headers, body)
    # Assert: received ("response_start", 200, headers)
    # Assert: received ("response_body", body_bytes, "application/json")
    # Assert: received ("response_done", duration_ms) where duration_ms > 0

def test_proxy_captures_post_with_body():
    """Verify POST body is captured as raw bytes."""
    # Send: POST with JSON body
    # Assert: ("request", "POST", url, headers, body_bytes) where body_bytes is raw JSON

def test_proxy_handles_all_methods():
    """Verify PUT, DELETE, PATCH, HEAD all emit events."""
    # Test each method
```

## Verification Commands
```bash
uv run pytest tests/test_proxy_generic.py -v
```
