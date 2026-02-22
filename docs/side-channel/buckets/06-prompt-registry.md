# 06 Prompt Registry

Goal:
- Centralize and version prompt templates for all side-channel purposes.

`// [LAW:one-source-of-truth] Prompt text and version live in one registry, not scattered literals.`
`// [LAW:single-enforcer] Prompt selection happens in one boundary based on purpose/profile.`

## How it could work

- Registry maps `purpose -> prompt template + version + constraints`.
- Templates support scoped variables (`messages`, `selection`, `target_format`).
- Side-channel request records prompt version for analytics/comparisons.

## Value

- Safer prompt changes.
- Easy A/B tests and rollback.
- Better consistency across features.

## Rough token cost

- Near zero direct overhead.
- Can reduce waste by keeping prompts short and purpose-specific.

## Ready to start?

Yes.

Definition of ready:
- no feature calls side-channel with inline freeform prompts
- all requests carry prompt version metadata

