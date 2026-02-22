# 08 Summary Checkpoints Over Time

Goal:
- Create range-based summary checkpoints so users can inspect evolution of work.

`// [LAW:one-source-of-truth] Each checkpoint must reference exact source range boundaries.`

## Implemented now

- Canonical checkpoint artifact type with serialization/deserialization.
- Dispatcher API for selected-range checkpoint creation:
  - `DataDispatcher.create_checkpoint(...)`
  - stores `source_start/source_end`, `source_session_id`, `request_id`
  - uses `checkpoint_summary` purpose, with fallback artifact when side-channel is disabled/blocked
- Deterministic checkpoint diff rendering:
  - `DataDispatcher.checkpoint_diff(...)`
  - output includes compared checkpoint IDs and both source ranges

## Value

- Easier long-session comprehension.
- Supports audits and decision evolution review.
- Useful base for handoff and changelog generation.

## Rough token cost

- Sparse/manual checkpoints: Low.
- Frequent automatic checkpoints: Medium.

## Deferred follow-ups

- UI for checkpoint creation over explicit user-selected ranges.
- Automatic checkpoint cadence policy (optional).
