# Sprint: http-headers - HTTP Headers Display
Generated: 2026-01-30-120000
Confidence: HIGH: 0, MEDIUM: 2, LOW: 0
Status: RESEARCH REQUIRED
Source: EVALUATION-20260130.md

## Sprint Goal
Capture HTTP request and response headers in the proxy layer and display them in the TUI when the headers filter is active.

## Scope
**Deliverables:**
- Proxy emits HTTP headers alongside request/response events
- New `HttpHeadersBlock` in the formatting IR
- Headers rendered under the existing "headers" filter toggle
- Request headers shown after MetadataBlock, response headers after StreamInfoBlock

## Work Items

### P1 [MEDIUM] Capture HTTP headers in proxy event pipeline

**Dependencies**: None
**Spec Reference**: Roadmap Item 3 | **Status Reference**: EVALUATION-20260130.md "Item 3"

#### Description
The proxy (proxy.py) currently emits events with body data only:
- `("request", body)` -- JSON body, no headers
- `("response_event", event_type, data)` -- SSE event, no headers
- `("response_start",)` -- no data at all

To display HTTP headers, the proxy must emit them. Two approaches:

**Option A (recommended)**: Add a new event type `("request_headers", headers_dict)` emitted before `("request", body)`, and `("response_headers", status_code, headers_dict)` emitted at `("response_start",)` time.

**Option B**: Extend existing events: `("request", body, headers_dict)` and `("response_start", status_code, headers_dict)`. This breaks the current event tuple contract.

Option A is preferred because it is additive (no existing event format changes).

#### Acceptance Criteria
- [ ] Proxy emits `("request_headers", headers_dict)` before the `("request", body)` event for /v1/messages requests
- [ ] Proxy emits `("response_headers", status_code, headers_dict)` at response start
- [ ] Headers dict excludes sensitive headers (Authorization, x-api-key) from the event
- [ ] Existing event handling is not broken (new events are ignored if not handled)
- [ ] Unit test: mock proxy handler, verify header events are emitted

#### Technical Notes
- proxy.py:42-45: After the `/v1/messages` check, also emit headers. Access `self.headers` (incoming request headers).
- proxy.py:74-82: After `self.send_response(resp.status)`, before streaming/reading body, emit response headers from `resp.headers`.
- Filter out Authorization and x-api-key for security (proxy.py:50 already filters host/content-length).
- The event queue is thread-safe (queue.Queue). Adding new event types is safe -- the TUI event loop in app.py uses a match/dispatch pattern that will simply ignore unknown events.

#### Unknowns to Resolve
1. **Which headers to include/exclude**: Should we show all headers, or only a curated subset (Content-Type, anthropic-ratelimit-*, x-request-id)?
   Research: Examine actual Anthropic API response headers to determine which are useful.
2. **Header ordering**: Should headers be displayed in received order or sorted alphabetically?
   Research: Check if Python's http.server preserves header order.

#### Exit Criteria (to reach HIGH)
- [ ] Header inclusion/exclusion policy decided
- [ ] Verified that proxy changes don't affect response forwarding
- [ ] Event handler dispatch in app.py handles new events gracefully

---

### P1 [MEDIUM] Format and render HTTP headers

**Dependencies**: "Capture HTTP headers in proxy event pipeline"
**Spec Reference**: Roadmap Item 3 | **Status Reference**: EVALUATION-20260130.md "Item 3"

#### Description
Create a new `HttpHeadersBlock` in the IR and corresponding renderer. The block appears under the "headers" filter.

For requests: Show request headers after the MetadataBlock (model, max_tokens, etc.).
For responses: Show response headers after StreamInfoBlock (or at response_start).

The formatting layer needs new functions:
- `format_request_headers(headers_dict)` -> list of FormattedBlock
- `format_response_headers(status_code, headers_dict)` -> list of FormattedBlock

The event handler needs to route the new events:
- `handle_request_headers(event, ...)` calls `format_request_headers` and adds the blocks
- `handle_response_headers(event, ...)` calls `format_response_headers` and adds the blocks

#### Acceptance Criteria
- [ ] `HttpHeadersBlock` dataclass exists in formatting.py with `headers: dict` and `header_type: str` (request/response)
- [ ] `_render_http_headers()` renders key-value pairs, styled dim, under "headers" filter
- [ ] Request headers appear after MetadataBlock in the turn
- [ ] Response headers appear at response start (before streaming content)
- [ ] Headers filter toggle shows/hides HTTP headers along with existing section headers
- [ ] BLOCK_FILTER_KEY maps HttpHeadersBlock -> "headers"
- [ ] BLOCK_RENDERERS includes HttpHeadersBlock
- [ ] Unit test: create HttpHeadersBlock, verify rendering output

#### Technical Notes
- The new block type must be added to the imports in rendering.py:10-17
- BLOCK_RENDERERS dict at rendering.py:242-263 needs the new entry
- BLOCK_FILTER_KEY dict at rendering.py:269-290 needs the new entry
- For request headers: the event handler processes `("request_headers", headers_dict)` by formatting blocks and calling `conv.add_turn([blocks])` OR prepending to the request turn. Prepending is tricky since the request turn is already added. Simpler: add as a separate mini-turn before the request turn.
- For response headers: append to StreamingRichLog during streaming start, similar to how StreamInfoBlock is handled.

#### Unknowns to Resolve
1. **Turn grouping**: Should HTTP headers be part of the request/response turn or a separate mini-turn? If separate, they appear as their own selectable turn. If grouped, we need to prepend blocks to an already-added turn (which is not currently supported).
   Research: Evaluate whether adding a `prepend_blocks()` method to ConversationView is worth the complexity vs. separate turns.
2. **Response headers timing**: Response headers are available at `response_start` (before any SSE events). But the streaming turn is the StreamingRichLog. Should headers go to the StreamingRichLog or to a separate ConversationView turn?
   Research: Check if StreamingRichLog can display non-streaming blocks (it can -- `append_block` handles any block type).

#### Exit Criteria (to reach HIGH)
- [ ] Turn grouping approach decided
- [ ] Response headers integration with streaming decided
- [ ] Event handler routing for new events designed

## Dependencies
- No external sprint dependencies
- Internal: proxy changes must precede formatting/rendering changes

## Risks
- **Medium**: Proxy changes could introduce timing issues if header events arrive between request and response events in an unexpected order. The event queue is FIFO within a single request handler, so ordering is guaranteed within a request.
- **Medium**: Adding many header key-value pairs could add visual noise. Mitigate by filtering to useful headers only.
- **Low**: Security risk if Authorization/x-api-key headers are accidentally displayed. Mitigate with explicit exclusion list in proxy.
