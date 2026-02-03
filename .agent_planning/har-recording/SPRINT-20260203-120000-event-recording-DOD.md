# Definition of Done: event-recording
Generated: 2026-02-03T12:00:00
Status: READY FOR IMPLEMENTATION
Plan: SPRINT-20260203-120000-event-recording-PLAN.md

## Acceptance Criteria

### Event Serializer/Deserializer
- [ ] `serialize_event(event_tuple) -> str` produces valid JSON line
- [ ] `deserialize_event(json_line) -> (timestamp, seq, event_tuple)` round-trips
- [ ] All 8 event types round-trip identically
- [ ] Malformed input raises ValueError with context

### Recording Subscriber
- [ ] Implements `Subscriber` protocol
- [ ] Writes valid JSONL, one line per event
- [ ] Lines flushed immediately after write
- [ ] First line is session metadata header
- [ ] Default output directory: `~/.local/share/cc-dump/recordings/`

### CLI Integration
- [ ] `--record <path>` flag works
- [ ] Default records to standard location
- [ ] `--no-record` disables recording
- [ ] Recording path printed at startup
- [ ] Clean shutdown in finally block

### Tests
- [ ] `tests/test_recorder.py` exists with 8+ test cases
- [ ] Round-trip fidelity verified for all event types
- [ ] Edge cases: unicode, empty, nested, large payloads
- [ ] Graceful error handling verified
