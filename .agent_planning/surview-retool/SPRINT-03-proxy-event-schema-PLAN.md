# Sprint 3: proxy-event-schema - Rewrite Proxy + Define Event Schema
Generated: 2026-02-06
Confidence: HIGH: 2, MEDIUM: 2, LOW: 0
Status: PARTIALLY READY

## Sprint Goal
Rewrite proxy.py to capture ALL HTTP traffic (not just /v1/messages) and define the canonical event schema that the entire downstream pipeline will consume. This sprint defines THE CONTRACT.

## Scope
**Deliverables:**
- proxy.py rewritten for generic HTTP
- Event schema documented and locked
- All HTTP methods supported
- Non-streaming response bodies captured
- SSE streams parsed per W3C spec
- Smoke test validating events are emitted

## Work Items

### P0: Define event schema (THE CONTRACT)
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] Event schema documented in code comments at top of proxy.py
- [ ] All downstream consumers can be written against this contract
- [ ] Schema covers: request capture, non-streaming response, streaming SSE, errors

**Technical Notes:**
Event schema (informed by evaluation):
```python
# Event tuples emitted by proxy → consumed by router → fan-out to subscribers
("request", method, url, headers_dict, body_bytes)       # Every request
("response_start", status_code, headers_dict)              # Response metadata
("response_body", body_bytes, content_type)                # Non-streaming response body
("sse_event", event_type_str, data_str)                    # Individual SSE event (W3C)
("response_done", duration_ms)                             # Request complete (with timing)
("error", status_code, reason)                             # HTTP error from upstream
("proxy_error", error_str)                                 # Internal proxy error
("log", method, path, status_str)                          # Access log
```

Key changes from current:
- `("request", body_dict)` → `("request", method, url, headers, body_bytes)` — raw bytes, not parsed JSON
- `("request_headers", headers_dict)` — MERGED into ("request", ...) — single event, not two
- `("response_headers", status, headers)` → `("response_start", status, headers)` — clearer name
- `("response_event", event_type, data_dict)` → `("sse_event", type_str, data_str)` — raw strings, not parsed JSON
- NEW: `("response_body", body_bytes, content_type)` — for non-streaming responses
- `("response_done",)` → `("response_done", duration_ms)` — add timing

### P1: Remove /v1/messages path filter and capture all traffic
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] Line 59 path filter removed — ALL requests emit events
- [ ] Events emitted for non-streaming responses (currently zero events for non-SSE)
- [ ] Events emitted for all HTTP methods (GET, POST, PUT, DELETE, PATCH, HEAD)
- [ ] Request body captured as raw bytes (not parsed as JSON)
- [ ] Response body captured for non-streaming responses

**Technical Notes:**
- Current proxy.py line 59: `if body_bytes and request_path.startswith("/v1/messages")` — REMOVE this guard
- Current lines 110-112: non-streaming responses forwarded with ZERO event emission — ADD response_body event
- Add do_PUT, do_DELETE, do_PATCH, do_HEAD methods that all delegate to _proxy()

### P2: Rewrite SSE parsing for W3C standard
**Confidence: MEDIUM**
**Acceptance Criteria:**
- [ ] Parse `event:` lines (W3C SSE field) in addition to `data:` lines
- [ ] Handle multi-line `data:` fields (concatenate with newlines per spec)
- [ ] Support both `[DONE]` sentinel (OpenAI/Claude convention) AND clean stream termination
- [ ] Emit `("sse_event", event_type, data)` with raw string data (not parsed JSON)

#### Unknowns to Resolve
- Should we parse SSE data as JSON or pass raw strings? **Decision: raw strings** — let formatting layer decide.
- Should we support `id:` and `retry:` SSE fields? **Decision: no** — display-only proxy, not a reconnecting client.

#### Exit Criteria
- Can parse Claude/OpenAI-style SSE (data: only, [DONE] sentinel)
- Can parse W3C-standard SSE (event: + data: fields)
- SSE events emitted with correct event_type (from `event:` line, or empty string if absent)

### P3: Request timing
**Confidence: MEDIUM**
**Acceptance Criteria:**
- [ ] Duration measured from request start to response complete
- [ ] Duration included in ("response_done", duration_ms) event
- [ ] Timing works for both streaming and non-streaming responses

#### Unknowns to Resolve
- Should timing include proxy overhead or just upstream time? **Decision: total time** — simple, useful for user.

#### Exit Criteria
- Duration is a float in milliseconds, included in response_done event

## Dependencies
- Sprint 1 (package renamed)
- Sprint 2 (dead imports removed so proxy.py can be modified without import errors)

## Risks
- **SSE parsing complexity**: W3C spec has edge cases (BOM handling, empty lines, comment lines). Keep implementation pragmatic — handle common patterns, not every edge case.
- **No downstream consumers yet**: The new events won't be consumed until Sprint 4. Validation via smoke test only.
