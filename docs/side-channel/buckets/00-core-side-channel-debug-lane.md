# 00 Core Side-Channel Debug Lane

Goal:
- See side-channel traffic in `cc-dump` for debugging, while keeping main session clean.

`// [LAW:single-enforcer] One ingress classifier decides primary vs side_channel.`
`// [LAW:one-source-of-truth] HAR + existing session/lane views remain the canonical debug surfaces.`

## How it could work

- Ingress classification tags each request as `primary` or `side_channel`.
- Router maps `side_channel` requests to separate multi-session lane keys (for example `live:side-channel:<source-session>`).
- HAR entries include side-channel category metadata.
- Primary views default to primary-only data.
- Operator switches lanes/tabs to inspect side-channel events and payloads.

## Value

- Removes opacity while preserving trust in the main session view.
- Makes low-level debugging first-class without adding new tooling.
- Unblocks all higher-level side-channel features safely.

## Rough token cost

- Incremental token cost: none (classification/routing only).
- Side-channel requests themselves still consume tokens as usual.

## Ready to start?

Yes.

Known inputs already present:
- request/response envelope events
- HAR recording pipeline
- stream/session attribution machinery
- multi-session architecture direction

Open questions before coding:
- exact metadata field names for HAR category tagging
- default filtering behavior in each existing view

Definition of ready:
- side-channel entries visible in side-channel lane
- zero side-channel entries in primary lane
- automated tests for routing/filtering invariants

