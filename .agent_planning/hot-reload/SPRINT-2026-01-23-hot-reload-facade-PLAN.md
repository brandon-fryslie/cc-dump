# Sprint: hot-reload-queue - Event Queue Hot Reload
Generated: 2026-01-23
Confidence: HIGH
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Proxy becomes a pure data source pushing events onto a queue. Main-thread consumer pulls events and calls into reloadable display code. State lives in the consumer, not the proxy.

## Architecture

```
┌─────────────────────────┐         ┌──────────────────────────────┐
│ proxy.py (never reloaded)│         │ main thread (cli.py)         │
│                          │  Queue  │                              │
│ HTTP handler threads ────┼────────>│ consumer loop:               │
│                          │         │   _check_reload()            │
│ Pushes plain tuples:     │         │   cc_dump.display.handle()   │
│  ("request", body)       │         │                              │
│  ("response_start",)     │         │ Owns: state dict             │
│  ("event", type, data)   │         │                              │
│  ("response_done",)      │         └──────────────────────────────┘
│  ("error", code, reason) │                    │
│                          │                    ▼
└──────────────────────────┘         ┌──────────────────────────────┐
                                     │ display.py (reloaded)        │
                                     │  → formatting.py (reloaded)  │
                                     │  → colors.py (reloaded)      │
                                     └──────────────────────────────┘
```

## Event Types

```python
# All events are plain tuples — no imports needed in proxy
("request", body_dict)           # parsed JSON request body
("response_start",)             # response headers received, stream beginning
("response_event", event_type, event_dict)  # one SSE event
("response_done",)              # stream finished
("error", code, reason)         # HTTP error from upstream
("proxy_error", str(exception)) # connection/proxy failure
("log", command, path, status)  # access log line
```

## State (owned by consumer, passed to display)

```python
state = {
    "positions": {},     # position_key → {hash, content, id, color_idx}
    "known_hashes": {},  # hash → id (for "ref" detection)
    "next_id": 0,
    "next_color": 0,
    "request_counter": 0,
}
```

Bounded: one content string per position (for diffs). `known_hashes` stores only 8-char hash → tag-id.

## Work Items

### P0: Refactor proxy.py to push events onto queue

- Remove all display/formatting/color imports
- Accept a `queue.Queue` (passed in from cli.py)
- In `_proxy()`: push `("request", body)` after parsing
- In `_stream_response()`: push `("response_start",)`, then `("response_event", type, data)` per SSE event, then `("response_done",)`
- On HTTP error: push `("error", code, reason)`
- On proxy error: push `("proxy_error", str(e))`
- In `log_message`: push `("log", command, path, status)`
- Remove lock (no stdout writes in proxy anymore)

**Acceptance Criteria:**
- [ ] proxy.py imports nothing from cc_dump (except maybe __init__ if needed)
- [ ] proxy.py does not write to stdout or stderr
- [ ] proxy.py has no threading.Lock (display serialization is consumer's job)
- [ ] All data pushed is plain tuples of str/int/dict

### P1: Create consumer loop in cli.py

- Create queue, pass to ProxyHandler
- Run HTTP server in a daemon thread
- Main thread runs consumer loop: `while True: event = queue.get()`
- On each event: `_check_reload()` then `cc_dump.display.handle(event, state)`
- Consumer owns the `state` dict

**Acceptance Criteria:**
- [ ] Server runs in background thread, consumer on main thread
- [ ] Ctrl-C still shuts down cleanly
- [ ] `_check_reload()` called on each event (file change detection)

### P2: Create display.py facade

- `handle(event, state) → None` — dispatches by event[0], writes to stdout/stderr
- Delegates to formatting.py for complex rendering
- Pure functions, no module-level mutable state

**Acceptance Criteria:**
- [ ] Single `handle()` entry point
- [ ] All stdout/stderr writes happen here
- [ ] No module-level mutable state

### P3: Move tracking logic into formatting.py, delete tracker.py

- `track_content(content, position_key, state) → tuple` as a pure function
- Operates on state dict directly (mutates it)
- Delete tracker.py

**Acceptance Criteria:**
- [ ] No ContentTracker class
- [ ] tracker.py deleted
- [ ] track_content works with plain dict state
- [ ] Bounded memory (one content per position)

### P4: Verify

**Acceptance Criteria:**
- [ ] `just run` starts cleanly
- [ ] Editing formatting.py mid-session picks up changes on next request
- [ ] System prompt tracking (new/ref/changed) works
- [ ] Streaming text appears in terminal with minimal latency
- [ ] No import errors on reload

## Dependencies
None — single sprint.

## Risks
- **Latency**: Terminal output is decoupled from byte forwarding. Queue latency is sub-millisecond for in-process queue.get(), so imperceptible.
- **Ordering**: Single queue preserves event order. Multiple concurrent requests interleave events — same as current behavior with lock-based stdout writes.
