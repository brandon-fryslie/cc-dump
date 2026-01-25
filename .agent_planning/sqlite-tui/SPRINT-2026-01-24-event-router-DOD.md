# Definition of Done: event-router
Generated: 2026-01-24

## Acceptance Criteria

1. **router.py exists** with `EventRouter`, `QueueSubscriber`, `DirectSubscriber`
2. **Subscriber protocol**: any object with `on_event(event)` method works
3. **EventRouter** drains source queue in daemon thread, fans out to all subscribers
4. **QueueSubscriber** puts events into its own queue for async consumption
5. **DirectSubscriber** calls a function inline in the router thread
6. **cli.py** uses router instead of direct queue consumption
7. **--no-tui flag** exists (selects legacy display loop)
8. **Output identical** to Sprint 1 completion (transparent indirection)
9. **Clean shutdown**: Ctrl+C stops router thread, server, no hangs
10. **No events lost**: all proxy events reach display subscriber

## Verification Method
- Run `cc-dump --no-tui` and make API requests — output identical to before
- Ctrl+C cleanly exits without thread warnings
- Add a second DirectSubscriber that counts events, verify count matches
