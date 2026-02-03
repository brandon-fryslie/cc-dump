# Sprint: event-replay - Event Stream Replay and Session Restore
Generated: 2026-02-03T13:00:00
Confidence: HIGH: 3, MEDIUM: 1, LOW: 0
Status: PARTIALLY READY
Source: EVALUATION-20260203-120000.md

## Sprint Goal
Implement HAR replay that loads complete request/response pairs and restores application state directly, with NO streaming simulation.

## Scope
**Deliverables:**
- `har_replayer.py` module: reads HAR file and processes complete messages
- CLI `--replay <path>` flag that starts the TUI in replay mode (no proxy server)
- Batch event processing: load all messages, process immediately, display final state
- Verification that replayed sessions produce identical final state to live sessions

## Work Items

### P0 - HAR Loader and Message Parser

**Dependencies**: Sprint 1 (HAR recording) - HAR format structure
**Spec Reference**: HAR 1.2 Spec, ARCHITECTURE.md "Event Flow"
**Status Reference**: EVALUATION-20260203-120000.md "Architectural Gap" section

#### Description
Create `har_replayer.py` that loads HAR files and extracts complete request/response pairs. The key difference from Sprint 1 planning: **NO streaming simulation**. We load complete messages and process them as batch data.

The loader must:
- Parse HAR JSON structure (`log.entries[]`)
- Extract request body (JSON) and response content (complete Claude message)
- Validate that responses are in non-streaming format (not SSE streams)
- Return list of (request, response) tuples for processing

**Critical design constraint**: This is NOT an event source that feeds the queue. It loads complete data and hands it off for batch processing.

#### Acceptance Criteria
- [ ] `load_har(path) -> list[tuple[dict, dict]]` loads HAR and returns request/response pairs
- [ ] Validates HAR structure (has log.entries, each has request/response)
- [ ] Parses request postData JSON and response content JSON
- [ ] Raises clear errors for invalid HAR format or SSE responses (we expect synthetic non-streaming)
- [ ] Handles large HAR files (multiple conversations, dozens of entries)

#### Technical Notes
- Use `json.load()` to parse HAR file
- Response content should be complete Claude messages (`{"id": "...", "content": [...], "usage": {...}}`)
- If HAR contains actual SSE streams (from old recordings), need migration path or error message

---

### P0 - CLI Replay Mode with Batch Processing

**Dependencies**: HAR Loader
**Spec Reference**: PROJECT_SPEC.md "Zero Configuration", CLAUDE.md CLI section
**Status Reference**: EVALUATION-20260203-120000.md "CLI Bootstrap" section

#### Description
Add `--replay <path>` flag to cli.py. When specified:
1. Do NOT start the HTTP proxy server
2. Load HAR file and extract all request/response pairs
3. Convert complete messages to event tuples (synthetic events that match live format)
4. Push ALL events to event_q in batch (no delays, no streaming simulation)
5. Start router and TUI as normal
6. Router processes all events immediately, builds final state, displays

**Key architectural decision**: Replay still uses the event pipeline (router → subscribers → formatting) for code reuse, but pushes all events at once instead of streaming them. The TUI processes them in a tight loop until complete, THEN displays.

#### Acceptance Criteria
- [ ] `--replay <path>` flag accepted by argparse
- [ ] When --replay is set, no HTTP server is started
- [ ] HAR entries are converted to synthetic event tuples (request, response_event, response_done)
- [ ] All events pushed to queue immediately (no delays)
- [ ] Final TUI state matches what live session would produce
- [ ] SQLite database populated from replayed data (if desired)
- [ ] TUI stays open after replay completes (for browsing)

#### Technical Notes
In cli.py, the change is structural:

```python
if args.replay:
    # Replay mode: load HAR, convert to events, push all to queue
    from cc_dump.har_replayer import load_har, convert_to_events
    request_response_pairs = load_har(args.replay)

    # Convert each pair to event tuples
    for req, resp in request_response_pairs:
        events = convert_to_events(req, resp)  # Returns list of event tuples
        for event in events:
            event_q.put(event)

    # No proxy server - events already in queue
else:
    # Live mode: proxy feeds event_q
    server = http.server.HTTPServer(...)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
```

Everything after this point (router setup, subscriber setup, TUI launch) stays identical. The router drains the queue, which is already full of events from the HAR file.

---

### P0 - Message-to-Event Conversion

**Dependencies**: HAR Loader, CLI Replay Mode
**Spec Reference**: ARCHITECTURE.md "Event Flow", formatting.py event handling
**Status Reference**: EVALUATION-20260203-120000.md "Event Pipeline" section

#### Description
Create `convert_to_events(request, response)` function that takes a complete request/response pair and generates synthetic event tuples that match the live pipeline format.

**Synthetic events to generate:**
1. `("request_headers", {...})` - extracted from HAR request headers
2. `("request", {...})` - request postData parsed as JSON
3. `("response_headers", status, {...})` - extracted from HAR response
4. `("response_event", "message_start", {...})` - synthetic message_start with message metadata
5. `("response_event", "content_block_start", {...})` - for each content block
6. `("response_event", "content_block_delta", {...})` - for each text segment (no actual deltas, just complete text)
7. `("response_event", "content_block_stop", {...})` - for each content block
8. `("response_event", "message_delta", {...})` - usage information
9. `("response_event", "message_stop", {...})` - end marker
10. `("response_done",)` - completion

**Critical**: These events must match what formatting.py expects. The complete message is "exploded" back into the SSE event sequence format, but all at once (no streaming).

#### Acceptance Criteria
- [ ] `convert_to_events(req, resp) -> list[tuple]` generates all required event types
- [ ] Generated events match the format that formatting.py expects
- [ ] Content blocks are properly sequenced (start → deltas → stop)
- [ ] Tool use blocks are handled correctly
- [ ] Usage information is included in message_delta event
- [ ] Final state after processing matches live session state

#### Technical Notes
- Look at formatting.py to understand exact event structure expected
- Complete message content is split into "fake deltas" that contain full text (not actual character-by-character deltas)
- This is the inverse of Sprint 1's reconstruction: live SSE → complete message (Sprint 1), complete message → synthetic SSE (Sprint 2)

---

### P1 - State Restoration Verification

**Dependencies**: Message-to-Event Conversion, CLI Replay Mode
**Spec Reference**: ARCHITECTURE.md "Content Tracking" section
**Status Reference**: EVALUATION-20260203-120000.md "Content tracking state" note

#### Description
Verify that content tracking state (system prompt hashing, position tracking in `formatting.py`) accumulates correctly during batch replay. Since replay pushes all events at once, the state dict builds up in a tight loop, but the final result should be identical to live.

#### Acceptance Criteria
- [ ] Replayed session produces identical system prompt tags ([sp-1], [sp-2], etc.) as live session
- [ ] Diffs between system prompt versions are identical in replay vs. live
- [ ] Content tracking state dict at end of replay matches what it would be after live session
- [ ] Batch processing (all events at once) produces same final state as incremental streaming

#### Technical Notes
The state dict in cli.py is purely derived from event content processed through `track_content()` in formatting.py. Since replay feeds identical events (just in batch instead of streaming), the state should be identical. This is a verification task, not an implementation task.

## Dependencies
- Sprint 1 (HAR recording) must be complete: HAR format structure, message reconstruction
- No dependency on Sprint 3 (unification)

## Risks
- **Low risk**: Message-to-event conversion may not handle all content block types. Mitigation: tests cover text, tool_use, and other block types. Can extend as needed.
- **Medium risk**: Batch processing (all events at once) may cause TUI freeze during load. Mitigation: acceptable for replay mode - users expect brief loading time. For very large HAR files (hundreds of entries), could show loading indicator.
- **Low risk**: Content tracking state may accumulate differently in batch vs. streaming. Mitigation: verification test in "State Restoration Verification" work item.
- **Low risk**: Synthetic events may not perfectly match live event structure. Mitigation: copy exact event structure from formatting.py expectations, validate with tests.
