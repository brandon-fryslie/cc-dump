# Implementation Context: pipeline-unification
Generated: 2026-02-03T14:00:00
Confidence: HIGH (1), MEDIUM (2), LOW (1)
Source: EVALUATION-20260203-120000.md
Plan: SPRINT-20260203-140000-pipeline-unification-PLAN.md

## Persistence Role Clarification

### Current SQLite contents (schema.py):
- `turns` table: session_id, sequence_num, timestamp, model, stop_reason, token counts, tool_names, request_json, response_json, text_content
- `blobs` table: content-addressed large string storage
- `turn_blobs`: links turns to blobs
- `turns_fts`: full-text search index
- `tool_invocations`: per-tool stats with token counts

### What JSONL captures that SQLite does not:
- Individual SSE events (SQLite only stores aggregated response)
- HTTP request/response headers
- Event ordering and timing
- Log events

### What SQLite provides that JSONL does not (but can derive):
- Token count aggregation (derived from response events)
- Tool invocation correlation (derived from request messages)
- Full-text search index (derived from text deltas)
- Content-addressed blob deduplication (optimization, not data)

### Rebuild verification approach:
1. Live capture session -> produces JSONL + SQLite
2. Delete SQLite
3. Replay JSONL -> produces new SQLite
4. Compare: `SELECT * FROM turns ORDER BY sequence_num` from both
5. Compare: `SELECT * FROM tool_invocations ORDER BY turn_id, tool_name` from both
6. Token counts and text_content should match exactly

### Files to modify for documentation:
- `/Users/bmf/code/cc-dump/ARCHITECTURE.md` lines 76-132 (Event Flow, Database Layer sections)
- `/Users/bmf/code/cc-dump/CLAUDE.md` lines 8-15 (Commands section), lines 32-37 (Architecture section)

## Session Management

### Default recordings directory:
`~/.local/share/cc-dump/recordings/`

### Listing implementation (in cli.py or new sessions.py):
```python
def list_recordings(recordings_dir: str) -> list[dict]:
    """List available recordings with metadata."""
    recordings = []
    for path in sorted(Path(recordings_dir).glob("recording-*.jsonl")):
        with open(path) as f:
            header = json.loads(f.readline())
        # Count events (line count - 1 for header)
        event_count = sum(1 for _ in open(path)) - 1
        recordings.append({
            "path": str(path),
            "session_id": header.get("session_id"),
            "start_time": header.get("start_time"),
            "event_count": event_count,
            "size_bytes": path.stat().st_size,
        })
    return recordings
```

### "--replay latest" implementation:
```python
if args.replay == "latest":
    recordings = list_recordings(recordings_dir)
    if not recordings:
        print("No recordings found")
        sys.exit(1)
    args.replay = recordings[-1]["path"]  # sorted by name = sorted by time
```

## End-to-End Integration Test

### File: tests/test_integration_replay.py

```python
"""Integration test: record -> replay -> verify zero divergence."""

import queue
from cc_dump.recorder import RecordingSubscriber, serialize_event
from cc_dump.replayer import EventReplayer
import cc_dump.formatting as fmt


# Representative event sequence (extracted from proxy.py emit points):
SAMPLE_EVENTS = [
    ("request_headers", {"content-type": "application/json", "anthropic-version": "2023-06-01"}),
    ("request", {
        "model": "claude-3-opus-20240229",
        "max_tokens": 4096,
        "stream": True,
        "system": [{"type": "text", "text": "You are a helpful assistant."}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}],
    }),
    ("response_headers", 200, {"content-type": "text/event-stream"}),
    ("response_event", "message_start", {
        "type": "message_start",
        "message": {"id": "msg_01", "type": "message", "role": "assistant",
                     "model": "claude-3-opus-20240229",
                     "usage": {"input_tokens": 25, "cache_read_input_tokens": 0,
                               "cache_creation_input_tokens": 0}}
    }),
    ("response_event", "content_block_start", {
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "text", "text": ""}
    }),
    ("response_event", "content_block_delta", {
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "text_delta", "text": "Hi there!"}
    }),
    ("response_event", "message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn"},
        "usage": {"output_tokens": 5}
    }),
    ("response_done",),
]


def test_record_replay_roundtrip(tmp_path):
    """Events survive record -> replay cycle perfectly."""
    record_path = tmp_path / "test.jsonl"

    # Record
    recorder = RecordingSubscriber(str(record_path), "test-session")
    for event in SAMPLE_EVENTS:
        recorder.on_event(event)
    recorder.close()

    # Replay
    replay_q = queue.Queue()
    replayer = EventReplayer(str(record_path), replay_q, speed=0)
    replayer.start()
    replayer._thread.join(timeout=5)

    # Collect replayed events
    replayed = []
    while not replay_q.empty():
        event = replay_q.get_nowait()
        if event[0] != "replay_done":
            replayed.append(event)

    assert len(replayed) == len(SAMPLE_EVENTS)
    for original, replayed_event in zip(SAMPLE_EVENTS, replayed):
        assert tuple(replayed_event) == original


def test_formatting_fidelity(tmp_path):
    """Replay produces identical FormattedBlocks."""
    state_live = {"positions": {}, "known_hashes": {}, "next_id": 0, "next_color": 0, "request_counter": 0}
    state_replay = {"positions": {}, "known_hashes": {}, "next_id": 0, "next_color": 0, "request_counter": 0}

    # Process request event through formatting (live)
    request_body = SAMPLE_EVENTS[1][1]  # ("request", body)
    blocks_live = fmt.format_request(request_body, state_live)

    # Record + replay + process through formatting
    record_path = tmp_path / "test.jsonl"
    recorder = RecordingSubscriber(str(record_path), "test-session")
    for event in SAMPLE_EVENTS:
        recorder.on_event(event)
    recorder.close()

    replay_q = queue.Queue()
    replayer = EventReplayer(str(record_path), replay_q, speed=0)
    replayer.start()
    replayer._thread.join(timeout=5)

    # Find the request event in replay
    while not replay_q.empty():
        event = replay_q.get_nowait()
        if event[0] == "request":
            blocks_replay = fmt.format_request(event[1], state_replay)
            break

    # Compare blocks
    assert len(blocks_live) == len(blocks_replay)
    assert state_live == state_replay
```

## Architecture Documentation Updates

### ARCHITECTURE.md additions (after "Database Layer" section):

New section: "## Recording and Replay"

Content to add:
- Data flow diagram showing recorder as third subscriber
- JSONL format specification
- Relationship: JSONL = source of truth, SQLite = derived index
- Replay mode: replayer replaces proxy as event source
- "One code path" principle: everything downstream of event_q is mode-agnostic

### CLAUDE.md additions:

In "Commands" section, add:
```
cc-dump --record <path>        # explicit recording path
cc-dump --no-record            # disable recording
cc-dump --replay <path>        # replay from recording
cc-dump --replay latest        # replay most recent
cc-dump --replay-speed 1.0     # realtime replay speed
cc-dump --list                 # show available recordings
```

In "Architecture" section, add recorder.py and replayer.py to module list as stable modules.
