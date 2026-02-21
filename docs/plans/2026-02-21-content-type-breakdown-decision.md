# Content-Type Token Breakdown Decision

**Date**: 2026-02-21  
**Status**: Accepted  
**Scope**: Analytics dashboard v1 (`cc-dump-8bn` and related tickets)

## Decision

Skip content-type token breakdown in v1.

## Why

- Anthropic usage fields are authoritative for total input/output/cache tokens, but do not provide content-type attribution.
- Request-structure-derived estimates are not acceptable for this product direction.
- Mixing real and estimated token metrics in the same dashboard creates trust and UX problems.

## Consequences

- Analytics dashboard v1 includes only real-token dimensions:
  - cache/fresh efficiency
  - input/output split
  - timeline by turn
  - model/tool/subagent dimensions where attribution can be grounded in real data
- "Content type" (system/tool/conversation/code) is explicitly out of scope for v1.

## Revisit Conditions

Re-open this decision only if one of the following becomes true:

1. Anthropic API adds authoritative content-type token fields.
2. Product direction changes to allow non-authoritative estimates in analytics.
