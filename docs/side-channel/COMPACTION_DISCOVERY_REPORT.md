# Compaction Discovery Report

Status: draft-for-implementation
Date: 2026-02-22
Tickets: `cc-dump-v7t.1`, `cc-dump-v7t.2`, `cc-dump-v7t.3`

`// [LAW:one-source-of-truth] This report is the canonical compaction rubric + feasibility + decision record.`
`// [LAW:verifiable-goals] Every go/no-go gate below has deterministic pass/fail criteria.`
`// [LAW:single-enforcer] Compaction replacement must be accepted/rejected at one explicit boundary.`

## 1) Quality Rubric (Gate Before Context Replacement)

Compaction artifacts are **viewable immediately** but are **never allowed to replace active context**
until all gates pass.

### Gate A: Structure validity

- Requirement: artifact parses into the canonical compaction schema.
- Pass criteria: `parse_success_rate == 100%` over the evaluation set.
- Failure action: artifact marked non-replaceable; fallback to source-linked checkpoint/handoff output.

### Gate B: Source traceability

- Requirement: every top-level claim item includes at least one source link.
- Pass criteria: `traceable_item_ratio >= 0.98`.
- Failure action: artifact remains advisory only (cannot be used for replacement).

### Gate C: Decision/open-work retention

- Requirement: compaction must preserve accepted decisions and open work captured from source range.
- Pass criteria:
- `decision_recall >= 0.95`
- `open_work_recall >= 0.95`
- Failure action: artifact rejected and tagged `insufficient_fidelity`.

### Gate D: Contradiction safety

- Requirement: no contradictions against source-linked facts in scope.
- Pass criteria: `contradiction_count == 0`.
- Failure action: artifact rejected and tagged `contradiction_detected`.

### Gate E: Cost/latency guardrail compliance

- Requirement: generation stays within configured purpose limits.
- Pass criteria:
- `input_tokens + cache_read_tokens + cache_creation_tokens + output_tokens <= purpose_cap`
- `elapsed_ms_p95 <= timeout_ms_purpose`
- Failure action: degrade to fallback artifact with explicit warning.

## 2) Rollback Requirements

### Replacement model

- Replacement is **explicit and reversible**.
- A compaction artifact may become active only through one acceptance action:
- `accept_compaction(artifact_id, source_session_id, source_start, source_end)`.

### Rollback contract

- Rollback is one operation:
- `rollback_compaction(artifact_id)` restores original scope selection and invalidates replacement pointer.
- Rollback prerequisites:
- accepted artifact must store source session id + source range.
- previous active pointer must be persisted before swap.

### Data retained for rollback

- `artifact_id`
- `source_session_id`
- `source_start`, `source_end`
- `prompt_version`, `policy_version`
- acceptance timestamp + actor
- previous pointer id

### Rollback SLO

- UI rollback action visible in history within one interaction cycle.
- Pass criteria: rollback pointer swap observable in state snapshot immediately after mutation transaction.

## 3) Feasibility Spike: Rolling vs Intentional vs Multi-Session

Assumptions for deterministic sizing:

- Compaction purpose cap currently `40,000` tokens (`REDACTION_POLICY` / side-channel boundary).
- Compression target for accepted artifacts: `20% - 35%` of scoped source tokens.
- Rolling mode cadence candidate: every 20 turns.

### Token-cost comparison (estimated planning envelope)

| Mode | Invocation pattern | Typical per-run input | Aggregate cost trend | Fidelity risk |
|---|---|---:|---|---|
| Rolling | recurring every N turns | 2k-10k | medium ongoing; grows with session length | highest drift risk (lossy-over-lossy) |
| Intentional | user-triggered one-shot for explicit range | 8k-40k | medium one-time | medium risk (single-pass loss) |
| Multi-session seed | staged intentional compaction + seed package | 12k-40k per stage | high total; bounded by staged windows | medium-high (cross-session context loss) |

### Quality findings from spike analysis

- Rolling compaction has the worst drift profile because each pass summarizes prior summaries.
- Intentional compaction has the cleanest auditability since source range is explicit and user-scoped.
- Multi-session compaction is feasible only as staged windows when source scope approaches cap.

### Recommendation

- Phase 1 default: **Intentional compaction only**.
- Phase 2 optional: rolling compaction behind explicit opt-in after retention metrics prove stable.
- Multi-session deep compaction: staged-only, never one-shot across unbounded history.

## 4) Decision and Implementation Plan

Decision:

- Proceed with implementation planning for **intentional compaction first**.
- Keep rolling and multi-session deep compaction in guarded follow-up tracks.

Initial implementation sequence:

1. Define canonical compaction artifact schema with source links and acceptance metadata.
2. Add explicit acceptance/rollback API and state pointer history.
3. Add evaluator checks for Gate A-E to CI and local quality gate commands.
4. Wire UI flow: draft -> inspect sources -> accept -> rollback.

Dependency impact:

- Requires existing purpose guardrails (`compaction` cap/timeout) to remain active.
- Depends on source-link extraction quality from existing side-channel artifact patterns.
- Does not require changes to non-compaction purpose contracts.

Exit criteria for discovery epic:

- quality rubric approved
- rollback semantics defined
- phased implementation decision recorded with explicit next steps
