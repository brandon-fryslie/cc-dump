# Definition of Done: http-headers
Generated: 2026-01-30-120000
Status: RESEARCH REQUIRED
Plan: SPRINT-20260130-120000-http-headers-PLAN.md

## Acceptance Criteria

### Proxy Header Capture
- [ ] Proxy emits `("request_headers", headers_dict)` for /v1/messages requests
- [ ] Proxy emits `("response_headers", status_code, headers_dict)` at response start
- [ ] Authorization and x-api-key headers are excluded from emitted dicts
- [ ] Existing event handling (request, response_event, response_done) unchanged
- [ ] New events are safely ignored if not handled by consumer

### Formatting IR
- [ ] `HttpHeadersBlock` dataclass with `headers: dict` and `header_type: str` fields
- [ ] Formatting functions produce HttpHeadersBlock from header dicts

### Rendering
- [ ] `_render_http_headers()` renders headers as key-value pairs
- [ ] Controlled by "headers" filter (same toggle as section headers)
- [ ] `BLOCK_RENDERERS` includes HttpHeadersBlock entry
- [ ] `BLOCK_FILTER_KEY` maps HttpHeadersBlock -> "headers"

### Integration
- [ ] Request headers displayed after MetadataBlock
- [ ] Response headers displayed at response start
- [ ] Headers filter shows/hides HTTP headers together with section headers

### Tests
- [ ] Unit test: HttpHeadersBlock rendering
- [ ] Unit test: header exclusion (no auth headers in output)
- [ ] All existing tests pass

## Exit Criteria (MEDIUM confidence)
- [ ] Header inclusion/exclusion policy documented
- [ ] Turn grouping approach decided (separate mini-turn vs grouped)
- [ ] Response headers + StreamingRichLog integration approach decided
- [ ] Verified proxy changes don't affect response forwarding
