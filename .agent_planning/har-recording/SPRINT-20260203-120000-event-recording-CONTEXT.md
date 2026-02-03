# Implementation Context: event-recording (HAR Format)
Generated: 2026-02-03T12:00:00 (UPDATED for HAR approach)
Confidence: HIGH
Source: EVALUATION-20260203-120000.md
Plan: SPRINT-20260203-120000-event-recording-PLAN.md

## New File: src/cc_dump/har_recorder.py

### HAR Request/Response Builder

```python
# Functions to create:
def build_har_request(headers: dict, body: dict) -> dict:
    """Build HAR request entry from HTTP headers and JSON body."""
    # Modifies body to set "stream": false (synthetic for clarity)
    # Returns HAR request structure with method, url, headers, postData

def build_har_response(status: int, headers: dict, complete_message: dict, timings: dict) -> dict:
    """Build HAR response entry from reconstructed complete message."""
    # complete_message is the final Claude API message (not SSE stream)
    # Returns HAR response structure with status, headers, content, timings

def reconstruct_message_from_events(events: list[tuple]) -> dict:
    """Reconstruct complete Claude message from SSE event sequence."""
    # Input: [("response_event", "message_start", {...}), ("response_event", "content_block_delta", {...}), ...]
    # Output: {"id": "...", "type": "message", "content": [...], "usage": {...}}
    # This is the KEY function: accumulates deltas into final message
```

### Event types to handle (from proxy.py):

```python
# Line 64: self.event_queue.put(("request_headers", safe_req_headers))
# Line 65: self.event_queue.put(("request", body))
# Line 108: self.event_queue.put(("response_headers", resp.status, safe_resp_headers))
# Line 137: self.event_queue.put(("response_event", event_type, event))
# Line 139: self.event_queue.put(("response_done",))
# Also: error events, but those aren't recorded as successful HAR entries
```

### HAR Recording Subscriber

```python
class HARRecordingSubscriber:
    """Subscriber that accumulates events and writes HAR entries."""

    def __init__(self, path: str, session_id: str):
        # Initialize HAR structure
        # Track current request/response state
        self.pending_request = None
        self.response_events = []
        self.entries = []

    def on_event(self, event: tuple) -> None:
        # State machine:
        # - "request_headers" + "request" → store pending request
        # - "response_headers" → store response metadata
        # - "response_event" → accumulate in response_events list
        # - "response_done" → reconstruct complete message, build HAR entry, append to entries

    def close(self) -> None:
        # Write final HAR file: {"log": {"version": "1.2", "entries": [...]}}
        # Flush and close file handle
```

Follow pattern from `router.py` lines 31-37 (`DirectSubscriber`).

### CLI Integration: src/cc_dump/cli.py

Modify around lines 68-78 (where SQLiteWriter is created):

```python
# After line 78, add:
# HAR recording subscriber
har_recorder = None
if not args.no_record:
    from cc_dump.har_recorder import HARRecordingSubscriber
    record_dir = os.path.expanduser("~/.local/share/cc-dump/recordings")
    os.makedirs(record_dir, exist_ok=True)
    record_path = args.record or os.path.join(record_dir, f"recording-{session_id}.har")
    har_recorder = HARRecordingSubscriber(record_path, session_id)
    router.add_subscriber(DirectSubscriber(har_recorder.on_event))
    print(f"   Recording: {record_path}")
```

Add argparse flags near lines 22-25:

```python
parser.add_argument("--record", type=str, default=None, help="HAR recording output path")
parser.add_argument("--no-record", action="store_true", help="Disable HAR recording")
```

Add cleanup in finally block near line 103:

```python
finally:
    router.stop()
    if har_recorder:
        har_recorder.close()  # Flushes final HAR structure to disk
    server.shutdown()
```

### Module Classification

`har_recorder.py` is a **stable boundary module** (it does file I/O, should not be hot-reloaded). Use `import cc_dump.har_recorder` pattern if referenced from stable modules.

### HAR File Format (HAR 1.2)

```json
{
  "log": {
    "version": "1.2",
    "creator": {"name": "cc-dump", "version": "0.2.0"},
    "entries": [
      {
        "startedDateTime": "2026-02-03T12:00:00.123Z",
        "time": 1234.5,
        "request": {
          "method": "POST",
          "url": "https://api.anthropic.com/v1/messages",
          "headers": [{"name": "content-type", "value": "application/json"}],
          "postData": {"mimeType": "application/json", "text": "{\"model\":\"claude-3-opus\",\"stream\":false,...}"}
        },
        "response": {
          "status": 200,
          "headers": [{"name": "content-type", "value": "application/json"}],
          "content": {"mimeType": "application/json", "text": "{\"id\":\"msg_123\",\"content\":[...],\"usage\":{...}}"}
        }
      }
    ]
  }
}
```

### Test File: tests/test_har_recorder.py

Test patterns to follow from existing tests (e.g., `tests/test_analysis.py`):
- Use `tmp_path` fixture for file output
- Create representative SSE event sequences matching real Claude API responses
- Verify HAR structure has all required fields (log.version, log.entries, etc.)
- Test message reconstruction: SSE deltas → complete message
