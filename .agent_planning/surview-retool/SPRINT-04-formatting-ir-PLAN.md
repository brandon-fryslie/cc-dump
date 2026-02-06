# Sprint 4: formatting-ir - New Generic HTTP Block Types
Generated: 2026-02-06
Confidence: HIGH: 3, MEDIUM: 1, LOW: 0
Status: PARTIALLY READY

## Sprint Goal
Replace the Claude-specific FormattedBlock hierarchy with generic HTTP block types. This is the IR layer between proxy events and rendering.

## Scope
**Deliverables:**
- New block types for generic HTTP request/response display
- New format functions that consume the Sprint 3 event schema
- Delete all Claude-specific block types and format functions
- Content-type detection for body display

## Work Items

### P0: Define new block types
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] FormattedBlock base class preserved
- [ ] Generic blocks preserved: SeparatorBlock, HeaderBlock, HttpHeadersBlock, NewlineBlock, ErrorBlock, ProxyErrorBlock, LogBlock, TextContentBlock
- [ ] New: RequestHeaderBlock(method, url, request_num, timestamp) — request line display
- [ ] New: ResponseStatusBlock(status_code, content_type, size, duration_ms) — response summary
- [ ] New: JsonBodyBlock(body, truncated, full_size, body_type) — pretty-printed JSON
- [ ] New: TextBodyBlock(text, content_type, truncated) — raw text body
- [ ] New: BinaryBodyBlock(content_type, size) — binary placeholder
- [ ] New: SSEEventBlock(event_type, data_preview, full_size) — single SSE event
- [ ] New: SSEStreamSummaryBlock(event_count, total_size, duration_ms) — collapsed SSE summary
- [ ] Claude-specific blocks DELETED: MetadataBlock, SystemLabelBlock, TrackedContentBlock, ToolUseBlock, ToolResultBlock, StreamToolUseBlock, TurnBudgetBlock, StopReasonBlock, StreamInfoBlock, RoleBlock, DiffBlock, ImageBlock, UnknownTypeBlock

**Technical Notes:**
- Keep HeaderBlock but repurpose: label="REQUEST #1 GET /api/users", header_type stays "request"/"response"
- RoleBlock deleted — no concept of "user"/"assistant" in generic HTTP
- DiffBlock deleted — content tracking is LLM-specific (can be re-added later)
- TrackedContentBlock deleted — SHA256 content dedup was for system prompt tracking

### P1: New format functions
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] `format_request(method, url, headers, body_bytes, state)` → list[FormattedBlock]
- [ ] `format_response_start(status_code, headers, content_type)` → list[FormattedBlock]
- [ ] `format_response_body(body_bytes, content_type)` → list[FormattedBlock]
- [ ] `format_sse_event(event_type, data_str)` → list[FormattedBlock]
- [ ] Content-type detection: JSON → JsonBodyBlock, text/* → TextBodyBlock, else → BinaryBodyBlock
- [ ] JSON body truncation at ~4KB for display (full_size stored for reference)

**Technical Notes:**
- format_request replaces the Claude-specific format_request that parsed messages/tools/system
- format_response_start is new (old code went directly to streaming events)
- format_response_body is new (old code never captured non-streaming response bodies)
- format_sse_event replaces format_response_event (which switched on Claude event types)
- State dict simplified: only needs request_counter (remove positions, known_hashes, etc.)

### P2: Delete Claude-specific code from formatting.py
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] track_content(), _make_tracked_block() deleted
- [ ] make_diff_lines() deleted (DiffBlock removed)
- [ ] format_response_event() deleted
- [ ] format_complete_response() deleted
- [ ] _merge_tool_only_assistant_runs() deleted
- [ ] _tool_detail() deleted
- [ ] MSG_COLOR_CYCLE deleted
- [ ] All deleted block class definitions removed

### P3: Content-type detection and body formatting
**Confidence: MEDIUM**
**Acceptance Criteria:**
- [ ] `application/json` → attempt JSON parse, pretty-print, create JsonBodyBlock
- [ ] `text/*` (text/plain, text/html, text/xml) → TextBodyBlock
- [ ] `text/event-stream` → handled by SSE path (not body path)
- [ ] Everything else → BinaryBodyBlock with size and content-type
- [ ] Graceful fallback: if JSON parse fails, fall back to TextBodyBlock

#### Unknowns to Resolve
- What truncation limit for JSON bodies? **Decision: 4KB display, store full_size for "X bytes total" indicator**
- Should HTML bodies get any special treatment? **Decision: no, just text for MVP**

#### Exit Criteria
- JSON body detected and pretty-printed correctly
- Non-JSON text displayed raw
- Binary content shows placeholder with size

## Dependencies
- Sprint 3 (event schema defined — format functions must match event data)

## Risks
- **Charset detection**: body_bytes need decoding. Use content-type charset or fall back to UTF-8 with errors="replace".
