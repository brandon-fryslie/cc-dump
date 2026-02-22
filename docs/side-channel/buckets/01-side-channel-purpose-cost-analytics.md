# 01 Side-Channel Purpose Cost Analytics

Goal:
- Attribute side-channel token usage by purpose (summary, ledger, action-extraction, etc.).

`// [LAW:one-source-of-truth] Purpose attribution is one canonical field on side-channel requests.`
`// [LAW:single-enforcer] Cost aggregation happens in one analytics boundary, not per feature widget.`

## How it could work

- Every side-channel request includes `purpose` metadata.
- Capture usage fields from responses:
- `input_tokens`
- `cache_read_input_tokens`
- `cache_creation_input_tokens`
- `output_tokens`
- Aggregate by purpose over session, day, and run.
- Show a purpose breakdown in existing analytics surfaces.

## Value

- Prevents accidental quota drain from nice-to-have features.
- Enables per-feature ROI decisions.
- Supports sane default settings and opt-outs.

## Rough token cost

- Feature overhead: effectively zero (analytics on already-returned usage).
- Cost to user: unchanged, but now measurable per purpose.

## Ready to start?

Yes.

Open questions:
- canonical purpose taxonomy (small fixed set vs extensible)
- whether to show purpose rollups per lane or globally by default

Definition of ready:
- each side-channel run has exactly one purpose value
- purpose-level totals visible and test-verified

