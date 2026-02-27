# Side-Channel Work Buckets

This folder breaks the brainstorm into concrete work buckets.

Active roadmap (implementation first):
- Make side-channel traffic visible in existing `cc-dump` views without impacting main session behavior.

`// [LAW:one-source-of-truth] This index is the canonical bucket map; per-bucket docs hold details.`

## Buckets

| Bucket | Value | Rough Token Cost | Readiness |
|---|---|---|---|
| `00-core-side-channel-debug-lane.md` | Critical foundation | Low | Ready now |
| `01-side-channel-purpose-cost-analytics.md` | Cost/quota control | Low | Ready now |
| `02-block-summary-generation-and-cache.md` | Better block UX | Medium-High | Ready with scope limits |
| `03-compaction-strategies.md` | Long-session survivability | High | Discovery needed |
| `04-proxy-interception-latency-and-rich-data.md` | Lower latency + richer data | Low-Medium | Ready for spike |
| `05-decision-ledger.md` | Durable decision memory | Low-Medium | Ready for MVP |
| `06-prompt-registry.md` | Consistency + maintainability | Low | Ready now |
| `07-budget-guardrails.md` | Prevent quota burn | Very Low | Ready now |
| `08-summary-checkpoints.md` | Time-sliced recall | Low-Medium | Ready for MVP |
| `09-action-item-and-deferred-work-extraction.md` | Execution follow-through | Low-Medium | Ready for MVP |
| `10-handoff-note-generation.md` | Session continuity | Low-Medium | Ready for MVP |
| `13-lightweight-ai-utilities.md` | Broad quality-of-life wins | Low | Ready incrementally |
| `14-conversation-qa-textbox.md` | Flexible ad-hoc analysis | Variable (Low-High) | Ready for constrained MVP |

## Suggested sequencing

1. `00` core debug lane
2. `01` purpose-level side-channel analytics
3. `COMMON-FRAMEWORK.md` shared contracts
4. `06` prompt registry
5. `07` budget guardrails
6. Then pick user-visible feature buckets (`02`, `05`, `09`, `10`) based on impact.

## Cross-cutting docs

- `COMMON-FRAMEWORK.md`: canonical purpose taxonomy, run metadata contract, cost bands, readiness rubric.
- `15-evaluation-and-quality-gates.md`: acceptance/evaluation expectations per bucket.
- `16-redaction-and-data-boundaries.md`: context minimization and redaction policy guidance.
- `QUESTIONS-FOR-BMF.md`: bucket-scoped decision questions with recommended defaults.
- `IMPLEMENTATION-MATRIX.md`: technical implementation + placeholder status by bucket.
