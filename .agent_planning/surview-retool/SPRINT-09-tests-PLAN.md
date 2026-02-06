# Sprint 9: tests - Test Suite for Generic HTTP Proxy
Generated: 2026-02-06
Confidence: HIGH: 2, MEDIUM: 2, LOW: 0
Status: PARTIALLY READY

## Sprint Goal
Build test suite for the new generic HTTP proxy. Combine kept generic tests (updated imports) with new tests for rewritten modules.

## Scope
**Deliverables:**
- Generic tests updated (imports only)
- New tests for proxy, formatting, rendering, store, HAR
- End-to-end test: proxy → HAR record → replay → display

## Work Items

### P0: Update kept generic tests
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] test_router.py: imports updated, passes as-is
- [ ] test_sessions.py: path constants updated, passes
- [ ] test_hot_reload.py: module names updated, passes
- [ ] test_scroll_nav.py: block types in test data updated to new generic types
- [ ] test_widget_arch.py: block type references updated
- [ ] conftest.py: path references updated

### P1: New test_formatting.py
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] Tests for format_request() with various HTTP methods
- [ ] Tests for _detect_body_blocks() with JSON, text, binary content
- [ ] Tests for format_sse_event()
- [ ] Tests for JSON truncation behavior
- [ ] Tests for content-type detection edge cases (no content-type, charset params)

### P2: New test_proxy_generic.py
**Confidence: MEDIUM**
**Acceptance Criteria:**
- [ ] Test: proxy emits events for GET request
- [ ] Test: proxy emits events for POST with body
- [ ] Test: proxy captures non-streaming response body
- [ ] Test: proxy parses SSE stream and emits sse_event events
- [ ] Test: all HTTP methods (PUT, DELETE, PATCH, HEAD) emit events
- [ ] Test: proxy error handling (upstream 500, connection refused)

#### Unknowns to Resolve
- How to test proxy without hitting real URLs? **Decision: use a local test HTTP server (http.server or pytest-httpserver)**

#### Exit Criteria
- Proxy tests pass without network access (local test server)

### P3: New test_har.py and test_store.py
**Confidence: MEDIUM**
**Acceptance Criteria:**
- [ ] test_store.py: SQLiteWriter accumulates and commits generic requests
- [ ] test_store.py: blobification of large request/response bodies
- [ ] test_store.py: FTS search across request/response content
- [ ] test_har.py: HAR recording of generic request/response
- [ ] test_har.py: HAR replay emits correct generic events
- [ ] test_har.py: end-to-end record → replay roundtrip

#### Unknowns to Resolve
- Reuse existing test patterns or start fresh? **Decision: adapt existing test_har_recorder.py/test_har_replayer.py patterns with generic data**

#### Exit Criteria
- Full record → replay → display pipeline tested

## Dependencies
- Sprints 3-7 (all core modules rewritten)
- Tests can be written incrementally alongside each sprint

## Risks
- **Test infrastructure**: Some tests may need a local HTTP server for proxy testing. pytest-httpserver or a simple http.server fixture.
