# 16 Redaction And Data Boundaries

Goal:
- Ensure side-channel requests do not leak sensitive or irrelevant data unnecessarily.

`// [LAW:capabilities-over-context] Send only the minimum context required for a purpose.`
`// [LAW:single-enforcer] Redaction boundary should be centralized before side-channel dispatch.`

## Why this matters

- Side-channel features increase request volume.
- Without discipline, unnecessary data gets resent repeatedly.
- Better scoping lowers spend and risk simultaneously.

## How it could work

- Pre-dispatch context minimizer:
- include only selected range/scope
- strip known sensitive headers/fields
- apply optional content redaction rules
- Annotate run metadata with scope level and redaction policy version.

## Value

- Better trust and safer defaults.
- Lower token usage by reducing irrelevant context.

## Rough token cost

- Redaction logic itself: negligible.
- Often reduces model token usage significantly.

## Ready to start?

Yes.

Definition of ready:
- centralized redaction/minimization policy exists
- tests prove policy is applied to every side-channel request

