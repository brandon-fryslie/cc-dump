# 12 Incident / Debug Timeline

Goal:
- Build concise, ordered incident timelines from noisy interactions and tool output.

`// [LAW:one-way-deps] Timeline generation consumes event/history data; it should not alter core pipeline behavior.`

## How it could work

- Ingest selected message/event ranges.
- Extract timeline entries with timestamps, actor, action, outcome, source links.
- Support facts-only default and optional hypothesis mode.

## Value

- Faster postmortems.
- Better communication during active incident response.

## Rough token cost

- Medium (needs broader context + temporal reasoning).
- Can be reduced by scoping to selected ranges.

## Implemented now

- Canonical incident timeline artifact schema:
  - `TimelineEntry` (`timestamp`, `actor`, `action`, `outcome`, `source_links`)
  - `IncidentTimelineArtifact` with separate `facts` and `hypotheses`
- Dispatcher generation flow:
  - `DataDispatcher.generate_incident_timeline(...)`
  - selected-scope extraction, chronological ordering, fallback-safe behavior
- Mode support:
  - facts-only default excludes hypothesis section
  - optional hypothesis mode includes `hypotheses` section

## Deferred follow-ups

- UI for timeline generation and navigation.
- Timeline grouping controls beyond strict chronological ordering.
