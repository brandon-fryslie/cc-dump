# FINAL PLAN: cc-dump-d6u — Migrate Non-UI Subscribers to Complete-Response Events

**Ticket:** cc-dump-d6u (P1)
**Dependency:** cc-dump-yj3 must be closed (done at `ff55efb`)
**Dependency:** cc-dump-yj3 (closed, ff55efb) — proxy-side SSE ResponseAssembler
**Downstream:** cc-dump-0xo (unify TUI response handlers), cc-dump-9z0 (parity contracts)

---

## 1. Architecture Constraints

### Laws Applied

- **[LAW:one-source-of-truth]** `ResponseAssembler` reconstructs once at the proxy boundary. Subscribers must not duplicate reconstruction. After this migration, only the proxy calls `reconstruct_message_from_events`.
- **[LAW:single-enforcer]** Each subscriber's event-handling method is the single point where its domain logic reacts to response data. The migration changes the input type (SSE fragments → complete dict) without adding a second enforcement point.
- **[LAW:dataflow-not-control-flow]** Tmux zoom decisions stay as a table lookup. Analytics and HAR recorder switch from progressive accumulation to single-event extraction — same data, fewer operations. No new conditional branches.
- **[LAW:behavior-not-structure]** Tests assert output behavior (TurnRecord fields, HAR JSON content, zoom/unzoom calls) not internal accumulator structure.

### Current State → Target State

| Subscriber | Current: consumes | Target: consumes | Eliminated code |
|---|---|---|---|
| **AnalyticsStore** (`analytics_store.py`) | `RESPONSE_EVENT` (SSE fragments) + `RESPONSE_DONE` (commit trigger) | `RESPONSE_COMPLETE` (commit immediately) | `_current_response_events`, `_current_text`, SSE-type dispatch (lines 102-123) |
| **HARRecordingSubscriber** (`har_recorder.py`) | `RESPONSE_EVENT` (SSE→dict accumulation) + `RESPONSE_DONE` (reconstruct+commit) | `RESPONSE_COMPLETE` (direct commit) | `response_events` list, `sse_event_to_dict` calls, `reconstruct_message_from_events` call (lines 202-222) |
| **TmuxController** (`tmux_controller.py`) | `RESPONSE_EVENT` (unwrap MessageDeltaEvent for stop_reason) | `RESPONSE_COMPLETE` (read `body["stop_reason"]`) | `ResponseSSEEvent`/`MessageDeltaEvent` isinstance checks (lines 94-97) |

### What Does NOT Change

- **TUI event path**: `event_handlers.py` still consumes `ResponseSSEEvent` for real-time streaming display. The TUI migration is a separate ticket (cc-dump-0xo).
- **`ResponseNonStreamingEvent`**: Still emitted by har_replayer for TUI consumption. Removed in cc-dump-0xo.
- **`ResponseAssembler`**: Unchanged. Still a `StreamSink` in `_fan_out_sse`.
- **`sse_event_to_dict`/`_SSEEventRecord`**: Remain in `response_assembler.py`. Used by `ResponseAssembler` internally and tested in `test_response_assembler.py`. Not dead code.

---

## 2. Critical Fix: Event Ordering in proxy.py

### The Bug

`_stream_response()` (line 456-468) emits events in wrong order:

```
_fan_out_sse(resp, [ClientSink, EventQueueSink, assembler])
  → EventQueueSink.on_done() emits ResponseDoneEvent    ← FIRST
  → assembler.on_done() reconstructs message
→ proxy emits ResponseCompleteEvent                      ← SECOND (too late)
```

But `_send_synthetic_response()` (line 442-454) does it correctly:

```
assembler.on_done()
→ emit ResponseCompleteEvent                             ← FIRST
→ emit ResponseDoneEvent                                 ← SECOND
```

### The Fix

Remove `ResponseDoneEvent` emission from `EventQueueSink.on_done()`. Have proxy.py emit it explicitly in both paths, always after `ResponseCompleteEvent`.

**Exact changes to proxy.py:**

1. **`EventQueueSink.on_done()` (line 202-208)**: Change to no-op (remove the `ResponseDoneEvent` put).

2. **`_stream_response()` (line 456-468)**: After `_fan_out_sse` returns and `assembler.result` is checked, emit `ResponseDoneEvent` explicitly:

```python
def _stream_response(self, resp, request_id: str = ""):
    assembler = ResponseAssembler()
    _fan_out_sse(resp, [
        ClientSink(self.wfile),
        EventQueueSink(self.event_queue, request_id=request_id),
        assembler,
    ])
    if assembler.result is not None:
        self.event_queue.put(ResponseCompleteEvent(
            body=assembler.result,
            request_id=request_id,
            recv_ns=time.monotonic_ns(),
        ))
    self.event_queue.put(ResponseDoneEvent(  # NEW: explicit, after COMPLETE
        request_id=request_id,
        recv_ns=time.monotonic_ns(),
    ))
```

3. **`_send_synthetic_response()` (line 442-454)**: Already correct order — no change needed, just verify `ResponseDoneEvent` emission stays after `ResponseCompleteEvent`.

**Result:** Both paths now emit: `...SSE... → ResponseCompleteEvent → ResponseDoneEvent`.

---

## 3. File-by-File Implementation Steps

### Step A: Fix event ordering in proxy.py

**File:** `src/cc_dump/proxy.py`

| Line(s) | Action | Detail |
|---|---|---|
| 202-208 | **Modify** | `EventQueueSink.on_done()` → remove `ResponseDoneEvent` emission, make it a no-op (or keep empty) |
| 456-468 | **Modify** | `_stream_response()` → add explicit `ResponseDoneEvent` emission after the `ResponseCompleteEvent` block |
| 442-454 | **Verify** | `_send_synthetic_response()` already has correct order — no change |

### Step B: Add ResponseCompleteEvent to har_replayer.py

**File:** `src/cc_dump/har_replayer.py`

| Line(s) | Action | Detail |
|---|---|---|
| 12-17 | **Modify imports** | Add `ResponseCompleteEvent` to imports from `cc_dump.event_types` |
| 149-161 | **Modify** | Add `ResponseCompleteEvent(body=complete_message, request_id=request_id, seq=1, recv_ns=time.monotonic_ns())` after the `ResponseNonStreamingEvent` in the returned list |

The returned event list becomes: `[RequestHeadersEvent, RequestBodyEvent, ResponseNonStreamingEvent, ResponseCompleteEvent]`

Keep `ResponseNonStreamingEvent` — TUI's `handle_response_non_streaming` still uses it. Removed in cc-dump-0xo.

### Step C: Migrate analytics_store.py

**File:** `src/cc_dump/analytics_store.py`

| Line(s) | Action | Detail |
|---|---|---|
| 16-24 | **Modify imports** | Remove: `ResponseSSEEvent`, `MessageStartEvent`, `MessageDeltaEvent`, `TextDeltaEvent`. Add: `ResponseCompleteEvent` |
| 73-74 | **Remove fields** | Delete `_current_response_events = []` and `_current_text = []` from `__init__` |
| 75-77 | **Simplify fields** | Keep `_current_usage`, `_current_stop`, `_current_model` but they become write-once-on-complete instead of progressive accumulators |
| 92-100 | **Keep** | `REQUEST` handler stays unchanged — stores `_current_request` for tool correlation |
| 96-97 | **Remove** | Delete the lines that reset `_current_response_events` and `_current_text` |
| 102-123 | **Replace** | Delete entire `RESPONSE_EVENT` handler. Replace with `RESPONSE_COMPLETE` handler: |

```python
elif kind == PipelineEventKind.RESPONSE_COMPLETE:
    assert isinstance(event, ResponseCompleteEvent)
    body = event.body
    usage = body.get("usage", {})
    self._current_usage = {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
    }
    self._current_model = body.get("model", "") or self._current_model
    self._current_stop = body.get("stop_reason", "") or ""
    self._commit_turn()
```

| Line(s) | Action | Detail |
|---|---|---|
| 125-126 | **Remove** | Delete `RESPONSE_DONE` handler — commit now happens in `RESPONSE_COMPLETE` handler |
| 358-392 | **Modify `get_state()`** | Remove: `current_response_events`, `current_text` from serialized state dict |
| 394-428 | **Modify `restore_state()`** | Remove: lines restoring `_current_response_events`, `_current_text` |

### Step D: Migrate har_recorder.py

**File:** `src/cc_dump/har_recorder.py`

| Line(s) | Action | Detail |
|---|---|---|
| 13-26 | **Modify imports** | Remove: `ResponseSSEEvent`. Remove from response_assembler imports: `reconstruct_message_from_events`, `sse_event_to_dict`, `_SSEEventRecord`. Add: `ResponseCompleteEvent` from event_types |
| 131 | **Remove field** | Delete `self.response_events: list[_SSEEventRecord] = []` |
| Add | **Add field** | Add `self._complete_message: dict | None = None` |
| 169-170 | **Update docstring** | Change state machine description: `response_complete -> build HAR entry` (was `response_event -> accumulate, response_done -> reconstruct`) |
| 202-205 | **Replace** | Delete `RESPONSE_EVENT` handler. Add `RESPONSE_COMPLETE` handler: |

```python
elif kind == PipelineEventKind.RESPONSE_COMPLETE:
    assert isinstance(event, ResponseCompleteEvent)
    self._complete_message = event.body
    self._commit_entry()
```

| Line(s) | Action | Detail |
|---|---|---|
| 207-209 | **Remove** | Delete `RESPONSE_DONE` handler — commit now happens in `RESPONSE_COMPLETE` handler |
| 211-214 | **Modify `_commit_entry()`** | Change guard: `if not self.pending_request or not self._complete_message:` (was `self.response_events`) |
| 222 | **Modify** | Replace `complete_message = reconstruct_message_from_events(self.response_events)` with `complete_message = self._complete_message` |
| 290-295 | **Modify cleanup** | Replace `self.response_events = []` with `self._complete_message = None` |

### Step E: Migrate tmux_controller.py

**File:** `src/cc_dump/tmux_controller.py`

| Line(s) | Action | Detail |
|---|---|---|
| 20-26 | **Modify imports** | Remove: `MessageDeltaEvent`, `ResponseSSEEvent`. Add: `ResponseCompleteEvent` |
| 75-82 | **Modify `_ZOOM_DECISIONS`** | Replace `RESPONSE_EVENT` with `RESPONSE_COMPLETE` in all three entries: |

```python
_ZOOM_DECISIONS: dict[tuple[PipelineEventKind, StopReason | None], bool | None] = {
    (PipelineEventKind.REQUEST, None): True,
    (PipelineEventKind.RESPONSE_COMPLETE, StopReason.END_TURN): False,
    (PipelineEventKind.RESPONSE_COMPLETE, StopReason.MAX_TOKENS): False,
    (PipelineEventKind.RESPONSE_COMPLETE, StopReason.TOOL_USE): None,
    (PipelineEventKind.ERROR, None): False,
    (PipelineEventKind.PROXY_ERROR, None): False,
}
```

| Line(s) | Action | Detail |
|---|---|---|
| 85-98 | **Rewrite `_extract_decision_key()`** | Extract stop_reason from `ResponseCompleteEvent.body` instead of unwrapping SSE types: |

```python
def _extract_decision_key(
    event: PipelineEvent,
) -> tuple[PipelineEventKind, StopReason | None]:
    """Extract the lookup key from a pipeline event.

    For ResponseCompleteEvent, extract stop_reason from body dict.
    For all other events, stop_reason is None.
    """
    stop_reason: StopReason | None = None
    if isinstance(event, ResponseCompleteEvent):
        sr_str = event.body.get("stop_reason", "") or ""
        try:
            stop_reason = StopReason(sr_str)
        except ValueError:
            stop_reason = StopReason.NONE
    return (event.kind, stop_reason)
```

### Step F: Update Tests

#### test_analytics_store.py

| Area | Change |
|---|---|
| Imports (lines 7-12) | Remove `ResponseSSEEvent`, `parse_sse_event`, `ResponseDoneEvent`. Add `ResponseCompleteEvent` |
| Helper `_sse()` (lines 15-17) | Delete entirely |
| `test_store_accumulates_turn` (lines 23-53) | Replace SSE event sequence with single `ResponseCompleteEvent(body={...})` containing model, usage, stop_reason. Remove `ResponseDoneEvent` |
| `test_store_populates_token_counts` (lines 56-113) | Same pattern: replace SSE events + ResponseDoneEvent with ResponseCompleteEvent |
| `test_store_handles_empty_tool_inputs` (lines 116-152) | Same |
| `test_store_handles_multiple_tools` (lines 155-201) | Same |
| `test_get_state_restore_state` (lines 443-467) | Verify `current_response_events` and `current_text` are NOT in serialized state |

Helper for tests:

```python
def _complete(body: dict) -> ResponseCompleteEvent:
    """Build a ResponseCompleteEvent with sensible defaults."""
    return ResponseCompleteEvent(body=body)
```

#### test_har_recorder.py

| Area | Change |
|---|---|
| Imports (lines 5-18) | Remove `ResponseSSEEvent`, `ResponseDoneEvent`, `parse_sse_event`. Add `ResponseCompleteEvent`. Remove `reconstruct_message_from_events` import from har_recorder (no longer exported) |
| Helper `_sse()` (lines 21-23) | Delete entirely |
| `test_har_subscriber_accumulates_events` (lines 357-436) | Replace SSE event sequence with: `RequestHeaders → RequestBody → ResponseHeaders → ResponseCompleteEvent(body=complete_msg)`. Remove `ResponseDoneEvent`. Assert same HAR output |
| `test_har_subscriber_writes_file` (lines 439-508) | Same pattern |
| `test_har_subscriber_multiple_requests` (lines 511-642) | Same pattern for both request cycles |
| `test_har_subscriber_incomplete_stream` (lines 656-689) | Still valid — if ResponseCompleteEvent never arrives, no HAR entry committed. Adjust expected `_events_received` keys |
| `test_har_subscriber_large_content` (lines 692-754) | Replace SSE with ResponseCompleteEvent containing large text in body |
| `test_har_subscriber_progressive_saving` (lines 757-906) | Replace SSE sequences with ResponseCompleteEvent + verify progressive saving behavior |
| Reconstruction tests (lines 119-335) | **Keep as-is** — these test `reconstruct_message_from_events()` which is in `response_assembler.py`, not har_recorder. The import path changes but the tests are still valid (now imported from `cc_dump.response_assembler` directly) |

#### test_tmux_controller.py

| Area | Change |
|---|---|
| Imports (lines 11-20) | Remove `MessageDeltaEvent`, `ResponseSSEEvent`, `TextDeltaEvent`, `ResponseDoneEvent`. Add `ResponseCompleteEvent` |
| `TestZoomDecisions` (lines 74-93) | Update all `RESPONSE_EVENT` references to `RESPONSE_COMPLETE` |
| `TestExtractDecisionKey` (lines 99-127) | Rewrite: `test_response_sse_message_delta_end_turn` → use `ResponseCompleteEvent(body={"stop_reason": "end_turn"})`. Same for `tool_use`, `max_tokens`. Remove `test_response_sse_non_delta` (no longer relevant — all SSE events are irrelevant). Keep request/error/proxy_error tests |
| `TestOnEvent` (lines 172-262) | `test_end_turn_triggers_unzoom`: replace `ResponseSSEEvent(sse_event=MessageDeltaEvent(...))` with `ResponseCompleteEvent(body={"stop_reason": "end_turn"})`. Same for tool_use, max_tokens. Remove `test_unrelated_sse_event_no_decision` (SSE events no longer reach tmux). Keep `test_response_done_no_decision` — still valid, ResponseDoneEvent still has no table entry |

#### test_har_replayer.py

| Area | Change |
|---|---|
| Imports (lines 7-11) | Add `ResponseCompleteEvent` |
| `test_convert_to_events_produces_three_events` (lines 290-316) | Update: now produces **4** events. Assert `events[3]` is `ResponseCompleteEvent` with `body == complete_message` |
| `test_convert_to_events_preserves_body_exactly` (lines 319-337) | Add assertion: `events[3].body is complete_message` |
| `test_roundtrip_har_load_and_convert` (lines 343-396) | Update: `assert len(events) == 4`, add `isinstance(events[3], ResponseCompleteEvent)` |

---

## 4. Machine-Verifiable Acceptance Checks

### Automated (all via `uv run pytest`)

| ID | What | How |
|---|---|---|
| **A1** | Analytics produces correct TurnRecord from ResponseCompleteEvent | `test_store_accumulates_turn`: feed `ResponseCompleteEvent(body={"model": "claude-sonnet-4", "usage": {"input_tokens": 100, "output_tokens": 50}, "stop_reason": "end_turn"})` → assert `turn.input_tokens == 100, turn.output_tokens == 50, turn.stop_reason == "end_turn"` |
| **A2** | Analytics handles cache tokens | Feed body with `cache_read_input_tokens: 200, cache_creation_input_tokens: 50` → assert `turn.cache_read_tokens == 200` |
| **A3** | Analytics ignores ResponseSSEEvent | Feed `ResponseSSEEvent` → assert `len(store._turns) == 0` |
| **A4** | HAR recorder writes correct entry from ResponseCompleteEvent | Feed `RequestHeaders + RequestBody + ResponseHeaders + ResponseCompleteEvent` → read HAR file → assert `response.content.text` contains correct complete message |
| **A5** | HAR recorder progressive saving works | After first `ResponseCompleteEvent`, file exists on disk with 1 entry before `close()` |
| **A6** | HAR recorder handles no-complete gracefully | Feed `RequestHeaders + RequestBody` with no `ResponseCompleteEvent` → `close()` → no file created |
| **A7** | Tmux zoom: request zooms | Feed `RequestBodyEvent` → assert `_is_zoomed is True` |
| **A8** | Tmux zoom: end_turn unzooms | Feed `ResponseCompleteEvent(body={"stop_reason": "end_turn"})` → assert `_is_zoomed is False` |
| **A9** | Tmux zoom: tool_use is noop | Feed `ResponseCompleteEvent(body={"stop_reason": "tool_use"})` → assert zoom state unchanged |
| **A10** | Replay emits ResponseCompleteEvent | `convert_to_events(...)` → assert `isinstance(events[3], ResponseCompleteEvent)` and `events[3].body == complete_message` |
| **A11** | Hot-reload round-trip | `store.get_state()` → new store → `restore_state()` → assert `get_session_stats()` matches |
| **A12** | Full test suite green | `uv run pytest` exits 0 |
| **A13** | Lint clean | `just lint` exits 0 |

### Manual Smoke Tests (by user)

| ID | What | How |
|---|---|---|
| **M1** | Live proxy analytics | Run `cc-dump`, proxy Claude traffic, verify budget panel shows token counts |
| **M2** | Live proxy HAR | After conversation, verify HAR file contains valid entries with correct response content |
| **M3** | Replay parity | `cc-dump --replay latest` → verify analytics panel shows same data as live |
| **M4** | Tmux auto-zoom | In tmux with auto_zoom=True, verify zoom on request, unzoom on end_turn |

---

## 5. Risks and Rollback

### Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **EventQueueSink.on_done() change affects TUI** | Medium | TUI uses `RESPONSE_DONE` only in `handle_response_done()` which triggers final render — identical behavior whether DONE comes from sink or proxy. Verify existing TUI tests still pass. |
| **Replay path emitting extra event** | Low | TUI's `EVENT_HANDLERS` dict has no entry for `RESPONSE_COMPLETE`, so the extra event is silently ignored (router catches errors per-subscriber). When cc-dump-0xo adds the handler, it will work. |
| **StopReason parsing mismatch** | Low | `body["stop_reason"]` is a string from the API ("end_turn", "tool_use", etc.). `StopReason(str)` handles these directly. ValueError fallback to `StopReason.NONE` matches current behavior for unknown values. |
| **Analytics hot-reload state shape change** | Low | `get_state()` and `restore_state()` are updated together. Old state dicts with `current_response_events`/`current_text` keys will be silently ignored by the new `restore_state()` (it uses `.get()` with defaults). |

### Rollback

- **Single git revert**: All changes are in one branch/PR. `git revert <merge-commit>` restores all files.
- **No data migration**: Analytics is runtime-only. HAR format unchanged. No persistent schema changes.
- **No feature flag needed**: Internal plumbing change with identical external behavior.

---

## 6. Parallelizable Beads Subtasks

```
cc-dump-d6u (parent)
│
├── [A] Fix event ordering: COMPLETE before DONE in proxy.py
│   Files: proxy.py
│   Depends on: nothing (yj3 done)
│   Tests: verify event ordering in both proxy paths
│
├── [B] Add ResponseCompleteEvent to har_replayer.py
│   Files: har_replayer.py, test_har_replayer.py
│   Depends on: nothing
│   Tests: A10
│
├── [C] Migrate analytics_store.py to ResponseCompleteEvent
│   Files: analytics_store.py, test_analytics_store.py
│   Depends on: [A]
│   Tests: A1-A3, A11
│
├── [D] Migrate har_recorder.py to ResponseCompleteEvent
│   Files: har_recorder.py, test_har_recorder.py
│   Depends on: [A]
│   Tests: A4-A6
│
├── [E] Migrate tmux_controller.py to ResponseCompleteEvent
│   Files: tmux_controller.py, test_tmux_controller.py
│   Depends on: [A]
│   Tests: A7-A9
│
└── [F] Final verification
    Depends on: [A]-[E]
    Tests: A12, A13
```

**Parallelism:**

```
     ┌── [A] ──┬── [C] ──┐
     │         ├── [D] ──┼── [F]
     │         └── [E] ──┘
     └── [B] ─────────────┘
```

Wave 1: [A], [B] in parallel
Wave 2: [C], [D], [E] in parallel (after [A])
Wave 3: [F] (after all)

---

## 7. Execution Checklist

- [ ] **[A]** `proxy.py`: Remove `ResponseDoneEvent` from `EventQueueSink.on_done()`. Add explicit `ResponseDoneEvent` after `ResponseCompleteEvent` in `_stream_response()`. Verify `_send_synthetic_response()` order is already correct.
- [ ] **[B]** `har_replayer.py`: Add `ResponseCompleteEvent` to `convert_to_events()` output. Update `test_har_replayer.py` assertions for 4 events.
- [ ] **[C]** `analytics_store.py`: Replace SSE fragment handling with `RESPONSE_COMPLETE` handler. Remove `_current_response_events`, `_current_text`. Update `get_state()`/`restore_state()`. Rewrite `test_analytics_store.py` to use `ResponseCompleteEvent`.
- [ ] **[D]** `har_recorder.py`: Replace SSE accumulation with `RESPONSE_COMPLETE` → direct commit. Remove `response_events`, `reconstruct_message_from_events` call, `sse_event_to_dict` import. Add `_complete_message` field. Rewrite `test_har_recorder.py` subscriber tests.
- [ ] **[E]** `tmux_controller.py`: Change `_ZOOM_DECISIONS` keys from `RESPONSE_EVENT` to `RESPONSE_COMPLETE`. Rewrite `_extract_decision_key()` to read `body["stop_reason"]`. Update `test_tmux_controller.py`.
- [ ] **[F]** Run `uv run pytest` — all green. Run `just lint` — clean.
- [ ] User smoke tests M1-M4.

---

**FINAL PLAN**
