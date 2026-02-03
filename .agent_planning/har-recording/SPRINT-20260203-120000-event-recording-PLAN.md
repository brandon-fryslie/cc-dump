# Sprint: event-recording - Event Stream Recording
Generated: 2026-02-03T12:00:00
Confidence: HIGH: 4, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION
Source: EVALUATION-20260203-120000.md

## Sprint Goal
Implement a HAR recording subscriber that accumulates streaming SSE events and writes complete HTTP request/response pairs in standard HAR format, while preserving live streaming UX.

## Scope
**Deliverables:**
- `har_recorder.py` module: a `Subscriber` that accumulates events and writes HAR format
- HAR 1.2 compliant format with synthetic non-streaming responses
- Integration into `cli.py` as a third router subscriber (parallel to TUI and SQLite)
- CLI flag `--record <path>` to enable recording (on by default to a session file)
- Tests for HAR generation and request/response reconstruction

## Work Items

### P0 - HAR Request/Response Builder

**Dependencies**: None
**Spec Reference**: HAR 1.2 Spec (https://w3c.github.io/web-performance/specs/HAR/Overview.html)
**Status Reference**: EVALUATION-20260203-120000.md "Format Analysis" section

#### Description
Create functions to build HAR-compliant request/response entries from streaming SSE events. The key insight: as events arrive, accumulate them in memory, then when the stream completes, reconstruct a **synthetic non-streaming response** that contains the complete message.

**Transformation:**
- Input: Streaming SSE events (`message_start`, `content_block_delta`, `message_delta`, `message_stop`)
- Output: Single complete JSON message (as if `stream: false` was used)

Key design decisions:
- Store actual request with `"stream": false` (synthetic, for HAR viewer clarity)
- Reconstruct response as `Content-Type: application/json` with complete message body
- HAR entry includes headers, timing (startedDateTime, time in ms), HTTP version
- Response body is the final reconstructed message, not the SSE event stream

#### Acceptance Criteria
- [ ] `build_har_request(headers, body) -> dict` produces HAR request entry
- [ ] `build_har_response(status, headers, reconstructed_body, timings) -> dict` produces HAR response entry
- [ ] Reconstructed message matches Claude API non-streaming format (content array, usage object, etc.)
- [ ] HAR structure validates against HAR 1.2 schema
- [ ] Headers are properly formatted (name/value pairs)

#### Technical Notes
- The response body must be reconstructed from accumulated deltas (text_delta events → final text)
- Message structure: `{"id": "...", "type": "message", "role": "assistant", "content": [...], "usage": {...}}`
- Timing information comes from event timestamps (first event → last event = total time)

---

### P0 - HAR Recording Subscriber

**Dependencies**: HAR Request/Response Builder
**Spec Reference**: ARCHITECTURE.md "Event Flow", router.py Subscriber protocol
**Status Reference**: EVALUATION-20260203-120000.md "What Does NOT Exist" section

#### Description
Create `HARRecordingSubscriber` that implements the `Subscriber` protocol and **accumulates streaming events in memory**, then writes complete HAR entries when each request/response completes. This is a `DirectSubscriber`-style component (inline in the router thread, no queue).

**Critical UX constraint**: This subscriber runs in parallel with TUI subscriber. It must NOT block or slow down the live streaming display.

The recorder must:
- Accumulate events in memory per request (track state: pending request, accumulating response)
- On `request` event: store request headers and body
- On `response_event`: accumulate SSE events (message_start, content_block_delta, etc.)
- On `response_done`: reconstruct complete message, build HAR entry, write to file
- Maintain HAR 1.2 structure: `{"log": {"version": "1.2", "creator": {...}, "entries": [...]}}`
- Write complete HAR file on shutdown (or incrementally append entries)

#### Acceptance Criteria
- [ ] Implements `Subscriber` protocol (has `on_event` method)
- [ ] Accumulates events in memory without blocking TUI
- [ ] Writes valid HAR 1.2 JSON structure
- [ ] Synthetic responses contain complete messages (not SSE streams)
- [ ] File is created in `~/.local/share/cc-dump/recordings/` by default
- [ ] HAR file can be opened in Chrome DevTools Network panel

#### Technical Notes
- Follow the pattern of `DirectSubscriber` wrapping `SQLiteWriter.on_event`.
- Error handling: log and continue on write errors (never crash the router).
- File naming: `recording-<session_id>.har`
- Memory management: for long sessions, periodically flush completed entries to disk

---

### P1 - CLI Integration for HAR Recording

**Dependencies**: HAR Recording Subscriber
**Spec Reference**: PROJECT_SPEC.md "Zero Configuration"
**Status Reference**: EVALUATION-20260203-120000.md "CLI Bootstrap" section

#### Description
Add HAR recording to `cli.py`. Recording should be on by default (every session is recorded) with an opt-out `--no-record` flag. Add `--record <path>` for explicit output path.

The HAR recorder subscriber is added to the router alongside the existing QueueSubscriber and DirectSubscriber(SQLiteWriter). It runs in parallel and does NOT affect live streaming performance.

#### Acceptance Criteria
- [ ] `--record <path>` flag writes HAR file to specified path
- [ ] Default behavior: records to `~/.local/share/cc-dump/recordings/recording-<session_id>.har`
- [ ] `--no-record` disables recording
- [ ] Recording path is printed to stdout during startup (like db_path is today)
- [ ] Recorder is stopped cleanly in the `finally` block (flushes HAR file)
- [ ] Live streaming UX is completely unchanged (no latency or blocking)

#### Technical Notes
- Mirror the existing pattern for `--db`/`--no-db` flags.
- The recorder is a third subscriber on the router, parallel to display and SQLite.
- On shutdown, recorder must flush final HAR structure to disk

---

### P1 - HAR Generation Tests

**Dependencies**: HAR Request/Response Builder, HAR Recording Subscriber
**Spec Reference**: CLAUDE.md test requirements
**Status Reference**: EVALUATION-20260203-120000.md "Test coverage needed"

#### Description
Write tests that verify:
1. Streaming SSE events correctly reconstruct into complete messages
2. HAR structure is valid (validates against HAR 1.2 schema)
3. Generated HAR files can be loaded by standard tools (Chrome DevTools compatible)
4. Edge cases: empty messages, large responses, unicode content, tool use blocks

#### Acceptance Criteria
- [ ] Test file `tests/test_har_recorder.py` with at least 5 test cases
- [ ] Reconstruction test: SSE event sequence → complete message (compare with expected non-streaming format)
- [ ] HAR validation: generated structure has all required fields (log, entries, request, response)
- [ ] Edge case test with unicode, tool use, large content blocks
- [ ] Test that recorder handles incomplete streams gracefully (missing message_stop)

#### Technical Notes
- Use `tmp_path` pytest fixture for file I/O tests.
- Generate representative SSE event sequences matching real Claude API responses.
- Test HAR can be parsed by json.load() and has expected structure

## Dependencies
- No external dependencies on other sprints
- This sprint is a prerequisite for Sprint 2 (replay)

## Risks
- **Low risk**: Message reconstruction logic may not handle all SSE event patterns. Mitigation: tests cover standard message types, tool use, and edge cases. Can add more patterns as discovered.
- **Low risk**: HAR accumulation in memory could use significant RAM for very long responses. Mitigation: typical Claude responses are <100KB complete messages; even 50 turns = ~5MB peak memory usage.
- **Low risk**: Recording overhead could slow the event pipeline. Mitigation: Accumulation in memory is fast (no I/O per event); only final HAR write at stream completion has I/O cost.
