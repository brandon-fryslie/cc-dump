# Sprint: event-recording - Event Stream Recording
Generated: 2026-02-03T12:00:00
Confidence: HIGH: 4, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION
Source: EVALUATION-20260203-120000.md

## Sprint Goal
Implement a recording subscriber that captures every event tuple as JSONL, preserving exact ordering, timing, and data fidelity for later replay.

## Scope
**Deliverables:**
- `recorder.py` module: a `Subscriber` that serializes event tuples to JSONL
- JSONL format specification with timestamp, sequence number, and event data
- Integration into `cli.py` as a third router subscriber
- CLI flag `--record <path>` to enable recording (on by default to a session file)
- Tests for serialization round-trip fidelity

## Work Items

### P0 - Event Serializer/Deserializer

**Dependencies**: None
**Spec Reference**: ARCHITECTURE.md "Event Flow" section, proxy.py event tuple definitions
**Status Reference**: EVALUATION-20260203-120000.md "Event Pipeline" section

#### Description
Create a pair of functions that serialize and deserialize event tuples to/from JSON. The event tuples are currently plain Python tuples like `("request", body_dict)`, `("response_event", "message_start", data_dict)`, etc. These must round-trip perfectly -- the deserialized output must be identical to the original input when fed to any subscriber.

Key design decisions:
- Use JSON lines format (one JSON object per line, newline-delimited)
- Each line contains: `{"ts": <float_epoch>, "seq": <int>, "event": [<event_tuple_elements>]}`
- Event tuple elements are already JSON-serializable (strings, dicts, ints) since they come from JSON parsing in proxy.py
- The `event` field is a JSON array matching the tuple positionally

#### Acceptance Criteria
- [ ] `serialize_event(event_tuple) -> str` produces valid JSON line with timestamp and sequence
- [ ] `deserialize_event(json_line) -> (timestamp, seq, event_tuple)` reconstructs exact event tuple
- [ ] Round-trip test: `deserialize(serialize(event)) == event` for all 8 event types
- [ ] Binary data (if any) is base64-encoded; all other data passes through as-is
- [ ] Malformed input raises clear ValueError with context

#### Technical Notes
- Event tuples from proxy.py contain only JSON-native types (str, dict, int, list, bool, None) because they originate from `json.loads()` calls. No special serialization needed for the payloads.
- Timestamps should use `time.monotonic()` for relative replay timing and `time.time()` for absolute wall clock.

---

### P0 - Recording Subscriber

**Dependencies**: Event Serializer
**Spec Reference**: ARCHITECTURE.md "Event Flow", router.py Subscriber protocol
**Status Reference**: EVALUATION-20260203-120000.md "What Does NOT Exist" section

#### Description
Create `RecordingSubscriber` that implements the `Subscriber` protocol (has `on_event(event)` method) and writes each event to a JSONL file. This is a `DirectSubscriber`-style component (inline in the router thread, no queue).

The recorder must:
- Open a file handle on construction
- Write one JSON line per event (using the serializer from above)
- Flush after each write (events must survive crash)
- Include a header line with session metadata (start time, cc-dump version, session_id)
- Close cleanly on shutdown

#### Acceptance Criteria
- [ ] Implements `Subscriber` protocol (has `on_event` method)
- [ ] Writes valid JSONL to the specified file path
- [ ] Each line is flushed immediately (fsync not required, but flush is)
- [ ] First line is a metadata header with `{"type": "session_meta", "version": 1, ...}`
- [ ] File is created in `~/.local/share/cc-dump/recordings/` by default

#### Technical Notes
- Follow the pattern of `DirectSubscriber` wrapping `SQLiteWriter.on_event` -- the recorder wraps a file write.
- Error handling: log and continue on write errors (never crash the router).
- File naming: `recording-<session_id>.jsonl`

---

### P1 - CLI Integration for Recording

**Dependencies**: Recording Subscriber
**Spec Reference**: PROJECT_SPEC.md "Zero Configuration"
**Status Reference**: EVALUATION-20260203-120000.md "CLI Bootstrap" section

#### Description
Add recording to `cli.py`. Recording should be on by default (every session is recorded) with an opt-out `--no-record` flag. Add `--record <path>` for explicit output path.

The recorder subscriber is added to the router alongside the existing QueueSubscriber and DirectSubscriber(SQLiteWriter).

#### Acceptance Criteria
- [ ] `--record <path>` flag writes recording to specified path
- [ ] Default behavior: records to `~/.local/share/cc-dump/recordings/recording-<session_id>.jsonl`
- [ ] `--no-record` disables recording
- [ ] Recording path is printed to stdout during startup (like db_path is today)
- [ ] Recorder is stopped cleanly in the `finally` block alongside router.stop()

#### Technical Notes
- Mirror the existing pattern for `--db`/`--no-db` flags.
- The recorder is a third subscriber on the router, parallel to display and SQLite.

---

### P1 - Recording Round-Trip Tests

**Dependencies**: Event Serializer, Recording Subscriber
**Spec Reference**: CLAUDE.md test requirements
**Status Reference**: EVALUATION-20260203-120000.md "Test coverage needed"

#### Description
Write tests that verify:
1. All 8 event types serialize and deserialize correctly
2. A recorded JSONL file can be read back and produces identical event tuples
3. Edge cases: empty bodies, large payloads, unicode content, nested JSON

#### Acceptance Criteria
- [ ] Test file `tests/test_recorder.py` with at least 8 test cases (one per event type)
- [ ] Round-trip test that writes events, reads them back, compares
- [ ] Edge case test with unicode, empty strings, deeply nested dicts
- [ ] Test that recorder handles write errors gracefully (does not crash)

#### Technical Notes
- Use `tmp_path` pytest fixture for file I/O tests.
- Generate representative event tuples by examining proxy.py's emit points.

## Dependencies
- No external dependencies on other sprints
- This sprint is a prerequisite for Sprint 2 (replay)

## Risks
- **Low risk**: Event tuples may contain types we haven't accounted for (e.g., if proxy.py is modified to emit non-JSON types). Mitigation: the serializer tests cover all current event types.
- **Low risk**: Recording overhead could slow the event pipeline. Mitigation: JSONL append + flush is fast; benchmarks show <1ms per event for typical payloads.
