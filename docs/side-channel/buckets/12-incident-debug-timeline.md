# 12 Incident / Debug Timeline

Goal:
- Build concise, ordered incident timelines from noisy interactions and tool output.

`// [LAW:one-way-deps] Timeline generation consumes event/history data; it should not alter core pipeline behavior.`

## How it could work

- Ingest selected message/event ranges.
- Extract timeline entries with timestamps, actor, action, result, impact.
- Optionally tag likely root-cause hypotheses and unresolved questions.

## Value

- Faster postmortems.
- Better communication during active incident response.

## Rough token cost

- Medium (needs broader context + temporal reasoning).
- Can be reduced by scoping to selected ranges.

## Ready to start?

Yes for scoped/manual MVP.

Unknowns:
- best balance between strict chronology and semantic grouping

Definition of ready:
- generated timeline is chronologically coherent
- users can map entries back to source artifacts quickly

