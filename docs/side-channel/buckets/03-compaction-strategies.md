# 03 Compaction Strategies (Rolling / Intentional / Multi-Session)

Goal:
- Keep long-running work usable by compressing context intentionally.

`// [LAW:locality-or-seam] Compaction artifacts should be explicit objects, not hidden mutations of primary history.`
`// [LAW:verifiable-goals] Must define measurable quality checks before broad rollout.`

## Modes

- Rolling compaction: background updates to a running summary state.
- Intentional compaction: user-triggered compact with instructions.
- Multi-session compaction: produce compact artifact for seeding a new session.

## How it could work

- Maintain compacted artifacts as side outputs tied to source ranges.
- Require explicit user acceptance before replacing active context with compacted form.
- Preserve traceability: every compact artifact links back to source spans.

## Value

- Extends useful session life.
- Improves handoffs and continuity.
- Reduces cognitive load and context drift.

## Rough token cost

- Rolling: Medium ongoing cost.
- Intentional one-shot: Medium.
- Multi-session deep compaction: High.

## Discovery output

Discovery artifact:
- `docs/side-channel/COMPACTION_DISCOVERY_REPORT.md`

Discovery status:
- quality rubric: defined
- rollback requirements: defined
- mode feasibility comparison: documented
- implementation recommendation: intentional compaction first

## Ready to start?

Yes, for intentional-compaction implementation planning and schema work.
