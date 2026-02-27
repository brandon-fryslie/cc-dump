# Side-Channel Common Framework

Purpose:
- Keep all bucket implementations aligned on taxonomy, cost accounting, and readiness gates.

`// [LAW:one-source-of-truth] This file defines shared contracts used by every bucket.`

## 1) Canonical `purpose` taxonomy

Required for all side-channel requests:
- `core_debug_lane`
- `block_summary`
- `decision_ledger`
- `action_extraction`
- `handoff_note`
- `conversation_qa`
- `checkpoint_summary`
- `compaction`
- `utility_<name>` (explicitly registered)

Rule:
- No request without a purpose.
- No free-form purpose strings in runtime calls.

## 2) Required per-run metadata

Minimum fields:
- `run_id`
- `purpose`
- `prompt_version`
- `lane_key`
- `source_session_id`
- `flags_used`
- `input_tokens`
- `cache_read_input_tokens`
- `cache_creation_input_tokens`
- `output_tokens`
- `latency_ms`
- `status`

## 3) Token cost band definitions

- `Very Low`: <= 1k input tokens typical, one-shot
- `Low`: 1k-5k input tokens typical
- `Medium`: 5k-25k input tokens or periodic automation
- `High`: >25k input tokens, large-context or frequent automation

Note:
- Banding is coarse; analytics should report actual counts.

## 4) Readiness rubric

- `R0 Discovery`: unknowns block design decisions
- `R1 Scoped`: clear MVP shape + known integration points
- `R2 Ready`: implementation can start with current info
- `R3 Productizable`: policy/guardrails/telemetry understood

## 5) Mandatory gates before enabling by default

1. Segregation gate:
- side-channel never contaminates primary lane/views
2. Budget gate:
- purpose-level budgets and fallback behavior are enforced
3. Analytics gate:
- per-purpose token accounting visible and correct
4. Quality gate:
- feature-specific acceptance checks defined and passing

## 6) Testing expectations

- Unit tests for classification/routing/purpose attribution.
- Integration tests for lane segregation and fallback behavior.
- Snapshot/contract tests for structured outputs where applicable.

`// [LAW:behavior-not-structure] Tests validate user-visible contracts and invariants, not internal implementation details.`

## 7) Operational controls (required)

- Global side-channel kill switch.
- Per-purpose enable/disable toggles.
- Max concurrent side-channel runs.
- Per-purpose timeout defaults.

Reason:
- fast rollback during incidents
- quota protection during unexpected load
- controlled rollout for new purposes
