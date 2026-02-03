# Implementation Context: event-replay
Generated: 2026-02-03T13:00:00
Confidence: HIGH (3 items), MEDIUM (1 item)
Source: EVALUATION-20260203-120000.md
Plan: SPRINT-20260203-130000-event-replay-PLAN.md

## New File: src/cc_dump/replayer.py

### EventReplayer class

```python
import json
import queue
import threading
import time

from cc_dump.recorder import deserialize_event  # From Sprint 1


class EventReplayer:
    """Replays recorded event streams into a queue.

    Drop-in replacement for proxy.py as event source.
    """

    def __init__(self, path: str, target_queue: queue.Queue, speed: float = 0.0):
        self._path = path
        self._queue = target_queue
        self._speed = speed  # 0=instant, 1.0=realtime, 0.5=2x fast
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._meta = self._read_header()

    def _read_header(self) -> dict:
        """Read and validate session_meta header."""
        with open(self._path) as f:
            first_line = f.readline()
        meta = json.loads(first_line)
        if meta.get("type") != "session_meta":
            raise ValueError(f"Invalid recording: missing session_meta header")
        if meta.get("version", 0) > 1:
            raise ValueError(f"Unsupported recording version: {meta['version']}")
        return meta

    @property
    def session_id(self) -> str:
        return self._meta.get("session_id", "unknown")

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        prev_ts = None
        with open(self._path) as f:
            # Skip header
            f.readline()
            for line in f:
                if self._stop.is_set():
                    break
                line = line.strip()
                if not line:
                    continue
                ts, seq, event = deserialize_event(line)
                # Timing
                if self._speed > 0 and prev_ts is not None:
                    delay = (ts - prev_ts) * self._speed
                    if delay > 0:
                        time.sleep(delay)
                prev_ts = ts
                self._queue.put(event)
        # Signal end of replay
        self._queue.put(("replay_done",))
```

### Module Classification
`replayer.py` is a **stable boundary module** (like proxy.py -- it's an event source, not display logic). Use `import cc_dump.replayer` pattern.

## Modified File: src/cc_dump/cli.py

### Changes needed:

**Add argparse flags** (near line 25):
```python
parser.add_argument("--replay", type=str, default=None,
                    help="Replay a recorded session (path to .jsonl file)")
parser.add_argument("--replay-speed", type=float, default=0.0,
                    help="Replay speed: 0=instant, 1.0=realtime, 0.5=2x (default: 0)")
```

**Conditional proxy/replay startup** (replace lines 32-49):
```python
event_q = queue.Queue()

if args.replay:
    # Replay mode: replayer feeds event_q
    from cc_dump.replayer import EventReplayer
    replayer = EventReplayer(args.replay, event_q, speed=args.replay_speed)
    session_id = replayer.session_id  # Use original session ID or generate new
    print(f"   Replaying: {args.replay}")
    print(f"   Speed: {'instant' if args.replay_speed == 0 else f'{args.replay_speed}x'}")
    replayer.start()
    server = None
else:
    # Live mode: proxy feeds event_q
    ProxyHandler.target_host = args.target.rstrip("/") if args.target else None
    ProxyHandler.event_queue = event_q
    server = http.server.HTTPServer((args.host, args.port), ProxyHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    # ... existing print statements ...
```

**Cleanup** (modify finally block around line 101-104):
```python
finally:
    router.stop()
    if args.replay:
        replayer.stop()
    else:
        server.shutdown()
```

### Key Architectural Point

The section from `router = EventRouter(event_q)` through `app.run()` (cli.py lines 61-101) remains IDENTICAL in both modes. This is the "one code path" requirement: router setup, subscriber setup, state initialization, and TUI launch do not branch on replay vs. live.

## Content Tracking Verification

The state dict at cli.py lines 52-58:
```python
state = {
    "positions": {},     # pos_key -> {hash, content, id, color_idx}
    "known_hashes": {},  # hash -> tag_id
    "next_id": 0,
    "next_color": 0,
    "request_counter": 0,
}
```

This state is modified only by `formatting.py:track_content()` (lines 193-242) and `formatting.py:format_request()` which increments `request_counter`. All modifications are deterministic functions of event content, not wall clock or random state. Replay produces identical state.

## Handling "replay_done" Event

The `("replay_done",)` event is a new event type not produced by proxy.py. Options:
1. Handle in `app.py:_handle_event_inner()` to show a "Replay complete" status
2. Ignore it (unknown event types are silently dropped by the current handler)

Recommendation: Add minimal handling in app.py to log it and optionally show in footer. The router and all existing subscribers will ignore unknown event types safely (they match on `kind` with if/elif chains that have no catch-all crash).

## Test File: tests/test_replayer.py

```python
def test_replay_instant(tmp_path):
    """Record events, replay instantly, verify all events received."""
    # 1. Write a recording file manually
    # 2. Create a queue
    # 3. Create EventReplayer with speed=0
    # 4. Start and wait for completion
    # 5. Drain queue, compare events

def test_replay_order_preserved(tmp_path):
    """Events arrive in original sequence order."""

def test_replay_timed(tmp_path):
    """Realtime replay respects timing gaps."""
    # Use short delays (10ms) to keep test fast

def test_content_tracking_fidelity(tmp_path):
    """Replay produces identical content tracking state."""
    # Process events through formatting, compare state dicts
```
