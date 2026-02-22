# 08 Summary Checkpoints Over Time

Goal:
- Create time/range-based summary snapshots so users can inspect evolution of work.

`// [LAW:one-source-of-truth] Each checkpoint must reference exact source range boundaries.`

## How it could work

- Create checkpoints at events (N turns, explicit command, milestone markers).
- Store summary + source range + prompt version.
- Allow diffing checkpoint A vs B for "what changed".

## Value

- Easier long-session comprehension.
- Supports audits and decision evolution review.
- Useful base for handoff and changelog generation.

## Rough token cost

- Sparse/manual checkpoints: Low.
- Frequent automatic checkpoints: Medium.

## Ready to start?

Yes for sparse/manual MVP.

Unknowns:
- default checkpoint cadence that balances value vs spend

Definition of ready:
- checkpoints are navigable by time/range
- at least one diff view is useful in real sessions

