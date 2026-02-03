# Implementation Context: event-recording
Generated: 2026-02-03T12:00:00
Confidence: HIGH
Source: EVALUATION-20260203-120000.md
Plan: SPRINT-20260203-120000-event-recording-PLAN.md

## New File: src/cc_dump/recorder.py

### Event Serializer

```python
# Functions to create:
def serialize_event(event: tuple, seq: int) -> str:
    """Serialize event tuple to JSON line."""
    # Returns: '{"ts": 1706900000.123, "seq": 1, "event": ["request", {...}]}\n'

def deserialize_event(line: str) -> tuple[float, int, tuple]:
    """Deserialize JSON line to (timestamp, seq, event_tuple)."""
    # Returns: (1706900000.123, 1, ("request", {...}))

def write_session_header(f, session_id: str, metadata: dict) -> None:
    """Write metadata header as first line."""
    # Line: '{"type": "session_meta", "version": 1, "session_id": "...", ...}\n'
```

### Event types to handle (from proxy.py):

```python
# Line 64: self.event_queue.put(("request_headers", safe_req_headers))
# Line 65: self.event_queue.put(("request", body))
# Line 81: self.event_queue.put(("error", e.code, e.reason))
# Line 90: self.event_queue.put(("proxy_error", str(e)))
# Line 108: self.event_queue.put(("response_headers", resp.status, safe_resp_headers))
# Line 137: self.event_queue.put(("response_event", event_type, event))
# Line 139: self.event_queue.put(("response_done",))
# Line 33: self.event_queue.put(("log", self.command, self.path, args[0] if args else ""))
```

All payloads are JSON-native types (str, dict, int, list). The `body` in "request" events comes from `json.loads(body_bytes)` at proxy.py line 62. The `event` in "response_event" comes from `json.loads(json_str)` at proxy.py line 130. Headers are filtered dicts of strings.

### Recording Subscriber

```python
class RecordingSubscriber:
    """Subscriber that records events to JSONL file."""

    def __init__(self, path: str, session_id: str):
        # Open file, write header, init seq counter

    def on_event(self, event: tuple) -> None:
        # Serialize and write, increment seq

    def close(self) -> None:
        # Flush and close file handle
```

Follow pattern from `router.py` lines 21-28 (`QueueSubscriber`) and lines 31-37 (`DirectSubscriber`).

### CLI Integration: src/cc_dump/cli.py

Modify around lines 68-78 (where SQLiteWriter is created):

```python
# After line 78, add:
# Recording subscriber
record_path = None
if not args.no_record:
    from cc_dump.recorder import RecordingSubscriber
    record_dir = os.path.expanduser("~/.local/share/cc-dump/recordings")
    os.makedirs(record_dir, exist_ok=True)
    record_path = args.record or os.path.join(record_dir, f"recording-{session_id}.jsonl")
    recorder = RecordingSubscriber(record_path, session_id)
    router.add_subscriber(DirectSubscriber(recorder.on_event))
    print(f"   Recording: {record_path}")
```

Add argparse flags near lines 22-25:

```python
parser.add_argument("--record", type=str, default=None, help="Recording output path")
parser.add_argument("--no-record", action="store_true", help="Disable event recording")
```

Add cleanup in finally block near line 103:

```python
finally:
    router.stop()
    if record_path:
        recorder.close()
    server.shutdown()
```

### Module Classification

`recorder.py` is a **stable boundary module** (it does file I/O, should not be hot-reloaded). Use `import cc_dump.recorder` pattern if referenced from stable modules.

### JSONL Line Format

```json
{"type": "session_meta", "version": 1, "session_id": "abc123", "start_time": 1706900000.0, "cc_dump_version": "0.2.0"}
{"ts": 1706900000.123, "seq": 1, "event": ["request_headers", {"content-type": "application/json"}]}
{"ts": 1706900000.456, "seq": 2, "event": ["request", {"model": "claude-3-opus", "messages": [...]}]}
{"ts": 1706900001.789, "seq": 3, "event": ["response_headers", 200, {"content-type": "text/event-stream"}]}
{"ts": 1706900001.800, "seq": 4, "event": ["response_event", "message_start", {"type": "message_start", ...}]}
{"ts": 1706900002.100, "seq": 5, "event": ["response_done"]}
```

### Test File: tests/test_recorder.py

Test patterns to follow from existing tests (e.g., `tests/test_analysis.py`):
- Use `tmp_path` fixture for file output
- Create representative event tuples matching proxy.py's actual output
- Assert round-trip equality with `==` comparison on tuples
