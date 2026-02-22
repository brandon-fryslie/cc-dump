# 07 Budget Guardrails

Goal:
- Prevent side-channel features from unexpectedly consuming user quota.

`// [LAW:single-enforcer] Guardrail policy is enforced in one dispatcher boundary.`
`// [LAW:no-mode-explosion] Keep a small set of guardrail modes with clear defaults.`

## How side-channel helps beyond existing cc-dump

Existing cc-dump is observational; side-channel introduces active token spend. Guardrails add control over this new spend source.

## How it could work

- Per-purpose daily/session token budgets.
- Hard/soft caps with fallback behavior.
- Concurrency/rate limits for background features.
- "Only on explicit user action" mode for expensive purposes.

## Value

- Strong user trust.
- Prevents accidental quota spikes.
- Enables safe defaults for opt-in features.

## Rough token cost

- Guardrail logic itself: negligible.
- Savings potential: high (by preventing low-value calls).

## Ready to start?

Yes.

Definition of ready:
- at least one hard cap and one soft warning policy implemented
- fallback path always available when guardrail blocks AI calls

