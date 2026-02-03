# Sprint: event-replay - Event Stream Replay and Session Restore
Generated: 2026-02-03T13:00:00
Confidence: HIGH: 3, MEDIUM: 1, LOW: 0
Status: PARTIALLY READY
Source: EVALUATION-20260203-120000.md

## Sprint Goal
Implement replay of recorded JSONL event streams through the existing pipeline, achieving zero divergence between live and restored sessions.

## Scope
**Deliverables:**
- `replayer.py` module: reads JSONL recording and injects events into the router's source queue
- CLI `--replay <path>` flag that starts the TUI in replay mode (no proxy server)
- Replay speed control (instant, 1x realtime, configurable multiplier)
- Verification that replayed sessions produce identical TUI output to live sessions

## Work Items

### P0 - Event Replayer Module

**Dependencies**: Sprint 1 (event-recording) - Event Serializer/Deserializer
**Spec Reference**: ARCHITECTURE.md "Event Flow" - router drains source queue
**Status Reference**: EVALUATION-20260203-120000.md "Architectural Gap" section

#### Description
Create `replayer.py` that reads a JSONL recording file and pushes event tuples into a `queue.Queue` -- the same queue that `proxy.py` normally feeds. The replayer is an alternative event source, not a new pipeline.

The key insight: `EventRouter.__init__` takes a `source: queue.Queue`. In live mode, proxy.py puts events into this queue. In replay mode, the replayer puts events into this same queue. Everything downstream (router fan-out, subscribers, TUI) is identical.

The replayer must:
- Read the session_meta header line and validate format version
- Read event lines sequentially
- Push event tuples into the provided queue
- Support speed modes: instant (no delay), realtime (original timing), multiplied (Nx)
- Run in a dedicated thread (like proxy's server_thread)
- Signal completion when all events are replayed

#### Acceptance Criteria
- [ ] `EventReplayer(path, queue, speed)` constructor validates file and reads header
- [ ] `start()` method begins replay in background thread
- [ ] Events are pushed to the queue in original order
- [ ] Speed modes work: instant (speed=0), realtime (speed=1.0), fast (speed=0.5 = 2x)
- [ ] Completion callback or event signals end of replay

#### Technical Notes
- The replayer is structurally parallel to proxy.py's server_thread. Both produce event tuples into the same queue type.
- For "instant" mode, push all events with no delay. For timed modes, use `time.sleep(delta)` between events based on timestamp differences.
- Thread must be daemon=True so it doesn't block app shutdown.

---

### P0 - CLI Replay Mode

**Dependencies**: Event Replayer
**Spec Reference**: PROJECT_SPEC.md "Zero Configuration", CLAUDE.md CLI section
**Status Reference**: EVALUATION-20260203-120000.md "CLI Bootstrap" section

#### Description
Add `--replay <path>` flag to cli.py. When specified:
1. Do NOT start the HTTP proxy server
2. Create event_q as normal
3. Create EventReplayer targeting event_q instead of proxy
4. Create router, subscribers as normal (including SQLite writer for a new session)
5. Start the TUI as normal
6. The replayer feeds events; everything else is identical

This is the architectural keystone: the TUI and all downstream processing code is UNAWARE of whether events come from a live proxy or a replay. One code path.

#### Acceptance Criteria
- [ ] `--replay <path>` flag accepted by argparse
- [ ] When --replay is set, no HTTP server is started
- [ ] Events from the recording file appear in the TUI identically to live capture
- [ ] SQLite database is populated from replayed events (same as live)
- [ ] `--replay` + `--record` together works (re-records a replay -- useful for format migration)
- [ ] Exit cleanly when replay completes (or keep TUI open for browsing)

#### Technical Notes
In cli.py, the change is structural:

```python
if args.replay:
    # Replay mode: replayer feeds event_q
    from cc_dump.replayer import EventReplayer
    replayer = EventReplayer(args.replay, event_q, speed=args.replay_speed)
    replayer.start()
else:
    # Live mode: proxy feeds event_q
    server = http.server.HTTPServer(...)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
```

Everything after this point (router setup, subscriber setup, TUI launch) stays identical.

---

### P0 - Content Tracking State Restoration

**Dependencies**: Event Replayer, CLI Replay Mode
**Spec Reference**: ARCHITECTURE.md "Content Tracking" section
**Status Reference**: EVALUATION-20260203-120000.md "Content tracking state" note

#### Description
Content tracking state (system prompt hashing, position tracking in `formatting.py`) is accumulated across events. When replaying, this state must build up naturally as events are processed -- which it will, since the same `format_request()` calls happen in the same order.

This work item verifies that no special handling is needed: the state dict initialized in cli.py (lines 52-58) accumulates correctly during replay just as it does during live capture.

If any state depends on wall-clock time or external factors (not event data), those must be identified and handled.

#### Acceptance Criteria
- [ ] Replayed session produces identical system prompt tags ([sp-1], [sp-2], etc.) as live session
- [ ] Diffs between system prompt versions are identical in replay vs. live
- [ ] Content tracking state dict at end of replay matches what it would be after live session
- [ ] No state depends on wall-clock time (only on event ordering and content)

#### Technical Notes
The state dict in cli.py lines 52-58 is:
```python
state = {"positions": {}, "known_hashes": {}, "next_id": 0, "next_color": 0, "request_counter": 0}
```
This is purely derived from event content processed through `track_content()` in formatting.py. Since replay feeds identical events, the state should be identical. This is a verification task, not an implementation task.

---

### P1 - Replay Speed Control (MEDIUM confidence)

**Dependencies**: Event Replayer
**Spec Reference**: None (UX enhancement)
**Status Reference**: N/A

#### Description
Add `--replay-speed <float>` flag. Values: 0 = instant, 1.0 = realtime, 0.5 = 2x speed, 2.0 = half speed. Default: 0 (instant).

Additionally, consider TUI keybindings for speed control during replay (pause/resume, speed up/slow down). This is MEDIUM confidence because the UX design for interactive speed control needs consideration.

#### Acceptance Criteria
- [ ] `--replay-speed` CLI flag works with float values
- [ ] Speed=0 replays all events instantly
- [ ] Speed=1.0 replays at original timing
- [ ] Speed values between 0 and 1 speed up; above 1 slow down

#### Unknowns to Resolve
1. Should the TUI show a "replay mode" indicator? Research: examine footer implementation in custom_footer.py
2. Should there be interactive speed controls (keybindings)? Research: check if Textual binding system can handle dynamic additions
3. What happens at end of replay -- keep TUI open or exit? Research: check how other TUI tools handle this

#### Exit Criteria (to reach HIGH confidence)
- [ ] UX decision made: replay indicator yes/no
- [ ] UX decision made: interactive controls yes/no
- [ ] UX decision made: end-of-replay behavior

## Dependencies
- Sprint 1 (event-recording) must be complete: serializer/deserializer, recording format
- No dependency on Sprint 3 (unification)

## Risks
- **Low risk**: Content tracking state may have hidden dependencies on factors outside event data. Mitigation: verification test in "Content Tracking State Restoration" work item.
- **Medium risk**: Replay of streaming events at "instant" speed may overwhelm the TUI's rendering pipeline (events arrive faster than rendering). Mitigation: the QueueSubscriber already handles backpressure via queue depth; _drain_events processes one at a time.
- **Low risk**: SQLite write during replay may conflict with live reads by panels. Mitigation: WAL mode already handles this for live sessions.
