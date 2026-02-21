# Analytics Panel Migration Decision

**Date**: 2026-02-21  
**Status**: Accepted  
**Scope**: Analytics dashboard rollout (`cc-dump-8bn`)

## Decision

Use incremental migration (Option C), not immediate replacement.

## Rollout Plan

1. Ship new Analytics panel alongside current Stats/Economics/Timeline panels.
2. Validate that Analytics covers core real-token use cases and UX expectations.
3. Remove or merge legacy panels only after coverage parity is demonstrated.

## Why

- Avoids big-bang UI replacement risk.
- Keeps a rollback path if the new dashboard misses a workflow.
- Preserves operator continuity during transition.

## Constraints

- New Analytics panel must use real API token data only.
- Legacy panels are transitional; no long-term dual-analytics strategy.
