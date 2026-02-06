# Sprint 7: har-rewrite - Generic HAR Recording and Replay
Generated: 2026-02-06
Confidence: HIGH: 3, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Rewrite HAR recording/replay for generic HTTP. The generic version is SIMPLER than the current Claude-specific version (no SSE→message reconstruction).

## Scope
**Deliverables:**
- HAR recorder stores raw request/response pairs
- HAR replayer emits generic events
- Creator name updated to "surview"

## Work Items

### P0: Rewrite har_recorder.py
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] reconstruct_message_from_events() DELETED (Claude SSE reconstruction)
- [ ] build_har_request() accepts raw method/url/headers/body_bytes (no synthetic body manipulation)
- [ ] build_har_response() accepts raw status/headers/body_bytes/content_type (not Claude message dict)
- [ ] HARRecordingSubscriber.on_event() handles new event schema: request, response_start, response_body, sse_event, response_done
- [ ] For SSE streams: accumulate raw SSE data as response body
- [ ] For non-streaming: store response body directly
- [ ] Creator name: "surview"
- [ ] HAR 1.2 format preserved

**Technical Notes:**
- The generic version is simpler: no need to reconstruct messages from SSE deltas
- For SSE responses, concatenate raw SSE lines as the response body (HAR viewers understand text)
- build_har_request now truly generic: method, url, headers, raw body
- build_har_response now truly generic: status, headers, raw body, timing

### P1: Rewrite har_replayer.py
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] convert_to_events() DELETED (Claude SSE synthesis)
- [ ] load_har() generalized: no Claude message type validation (line 72-73)
- [ ] New replay_events() function emits generic events from HAR entries:
  - ("request", method, url, headers, body_bytes)
  - ("response_start", status_code, headers)
  - ("response_body", body_bytes, content_type)
  - ("response_done", duration_ms)
- [ ] No SSE synthesis needed for replay (show complete response)

**Technical Notes:**
- HAR entries already contain complete request/response pairs
- Replay is much simpler: just emit request + response_body events
- No streaming simulation needed — replay shows completed requests
- Duration comes from HAR entry's "time" field

### P2: Update CLI replay path
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] cli.py replay mode calls updated load_har()
- [ ] Replay data passed to app as generic (method, url, headers, body, status, resp_headers, resp_body, content_type, duration) tuples
- [ ] app.py _process_replay_data() uses generic format functions

## Dependencies
- Sprint 3 (event schema — recorder consumes events)
- Sprint 4 (formatting — replay uses format functions)
- Can run in parallel with Sprint 5/6

## Risks
- **Backward compatibility**: Old cc-dump HAR files contain Claude message format. They won't replay correctly in surview. This is acceptable — clean break.
