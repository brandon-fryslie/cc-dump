# Sprint 6: database - New Schema, Store, Queries
Generated: 2026-02-06
Confidence: HIGH: 2, MEDIUM: 1, LOW: 0
Status: PARTIALLY READY

## Sprint Goal
Rewrite database layer for generic HTTP request/response storage. Preserve blob infrastructure.

## Scope
**Deliverables:**
- New schema with requests table (not turns)
- Store rewritten for new event schema
- Query layer rewritten for generic HTTP data
- Blob storage preserved for large request/response bodies

## Work Items

### P0: New schema
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] `requests` table: id, session_id, sequence_num, timestamp, method, url, status_code, content_type, request_size, response_size, duration_ms, is_streaming, request_headers (JSON), response_headers (JSON), request_body, response_body, sse_event_count
- [ ] `blobs` table preserved as-is (content-addressed storage)
- [ ] `request_blobs` table (replaces turn_blobs): links requests to blobs
- [ ] `requests_fts` FTS table on request_body + response_body
- [ ] `turns` table DROPPED
- [ ] `tool_invocations` table DROPPED
- [ ] Migration: fresh DB creation (no migration from old schema needed — clean break)

**Technical Notes:**
- SCHEMA_VERSION bumped to 4
- Large request/response bodies blobified using existing _blobify infrastructure

### P1: Rewrite SQLiteWriter
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] on_event() handles new event types: request, response_start, response_body, sse_event, response_done
- [ ] Accumulates request/response data across event stream
- [ ] Commits complete request/response pair on response_done
- [ ] Blobifies large request/response bodies (preserve _blobify logic)
- [ ] No references to token_counter, correlate_tools, or Claude-specific fields

### P2: Rewrite db_queries.py
**Confidence: MEDIUM**
**Acceptance Criteria:**
- [ ] get_session_stats() returns: request_count, total_request_bytes, total_response_bytes, avg_duration_ms, status_code_counts
- [ ] No references to tokens, models, cache, tool invocations
- [ ] Read-only connection pattern preserved

#### Unknowns to Resolve
- What queries does the stats panel need? **Depends on Sprint 5 stats panel design**
- Need any queries for potential future search feature? **Decision: keep FTS infrastructure but don't build search UI yet**

#### Exit Criteria
- Stats panel can query generic HTTP metrics from database

## Dependencies
- Sprint 3 (event schema — store consumes events)
- Sprint 5 can run in parallel if event schema is locked

## Risks
- **Data directory**: Change from `~/.local/share/cc-dump/` to `~/.local/share/surview/`
- **Old databases**: Incompatible schema. Users must start fresh. This is fine for a retool.
