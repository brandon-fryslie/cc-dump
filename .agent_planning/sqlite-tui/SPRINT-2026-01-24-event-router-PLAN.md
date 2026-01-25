# Sprint: event-router - Event Router Fan-Out
Generated: 2026-01-24
Confidence: HIGH: 3, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Create an EventRouter that drains the proxy queue in its own thread and fans out events to registered subscribers, replacing direct queue consumption in cli.py.

## Scope
**Deliverables:**
- `router.py` — EventRouter class with subscriber protocol
- Updated `cli.py` — uses router instead of direct queue consumption
- `--no-tui` flag (selects legacy display loop via QueueSubscriber)

## Work Items

### P0: Create router.py with EventRouter
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] `Subscriber` protocol with `on_event(event)` method
- [ ] `QueueSubscriber` wraps a `queue.Queue`, puts events for async consumption
- [ ] `DirectSubscriber` wraps a callable, invokes inline (for SQLiteWriter later)
- [ ] `EventRouter` spawns a daemon thread, drains source queue, copies to all subscribers
- [ ] Router stops cleanly when source queue gets a sentinel or on thread join

**Technical Notes:**
- EventRouter.__init__(source_queue) — takes the proxy's event queue
- EventRouter.add_subscriber(subscriber) — register before start
- EventRouter.start() — spawn drain thread
- EventRouter.stop() — signal and join thread
- Drain loop: get(timeout=0.5), on event call each subscriber.on_event(event)
- DirectSubscriber: on_event calls fn(event) inline in router thread
- QueueSubscriber: on_event calls self.queue.put(event)

### P1: Integrate router into cli.py
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] cli.py creates EventRouter(event_q) instead of consuming event_q directly
- [ ] Legacy display loop reads from a QueueSubscriber's queue
- [ ] `--no-tui` flag added (currently always uses legacy mode since TUI doesn't exist yet)
- [ ] Hot-reload still works in the legacy event loop
- [ ] Ctrl+C gracefully stops router and server

**Technical Notes:**
- Create router, add QueueSubscriber for display, start router
- Main loop reads from subscriber's queue (same pattern as before)
- Add `--no-tui` argument (default: False, but behavior is same either way until Sprint 4)

### P2: Verify transparent operation
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] Proxy works identically through router indirection — no visible output change
- [ ] No events are lost (router drains queue reliably)
- [ ] Clean shutdown on Ctrl+C (no hanging threads)

## Dependencies
- Sprint 1 (formatting-ir) must be complete first

## Risks
- Thread safety: Queue is already thread-safe. Router thread is the only reader of source queue.
