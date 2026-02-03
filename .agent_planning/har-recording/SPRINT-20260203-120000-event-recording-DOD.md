# Definition of Done: event-recording
Generated: 2026-02-03T12:00:00
Status: READY FOR IMPLEMENTATION
Plan: SPRINT-20260203-120000-event-recording-PLAN.md

## Acceptance Criteria

### HAR Request/Response Builder
- [ ] `build_har_request(headers, body) -> dict` produces valid HAR request entry
- [ ] `build_har_response(status, headers, message, timings) -> dict` produces valid HAR response entry
- [ ] `reconstruct_message_from_events(events) -> dict` correctly assembles complete message from SSE deltas
- [ ] Reconstructed messages match Claude API non-streaming format
- [ ] HAR structure validates against HAR 1.2 schema

### HAR Recording Subscriber
- [ ] Implements `Subscriber` protocol
- [ ] Accumulates events in memory per request/response pair
- [ ] Does NOT block or slow down live TUI streaming
- [ ] Writes valid HAR 1.2 JSON structure on close()
- [ ] Synthetic responses use `Content-Type: application/json` (not text/event-stream)
- [ ] Default output directory: `~/.local/share/cc-dump/recordings/`

### CLI Integration
- [ ] `--record <path>` flag works, writes HAR to specified path
- [ ] Default records to `~/.local/share/cc-dump/recordings/recording-<session_id>.har`
- [ ] `--no-record` disables recording
- [ ] Recording path printed at startup
- [ ] Clean shutdown flushes HAR file (har_recorder.close() in finally block)
- [ ] Live streaming UX completely unchanged

### Tests
- [ ] `tests/test_har_recorder.py` exists with 5+ test cases
- [ ] Message reconstruction verified: SSE events → complete message
- [ ] HAR validation: structure has all required fields
- [ ] Edge cases: unicode, tool use, large content, incomplete streams
- [ ] Generated HAR can be loaded by standard JSON parsers
