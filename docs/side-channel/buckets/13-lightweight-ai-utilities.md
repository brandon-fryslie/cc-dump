# 13 Lightweight AI Utilities

Goal:
- Add small, high-utility AI helpers that are cheap and optional.

`// [LAW:no-mode-explosion] Utilities should be a bounded list with owner and removal criteria.`

## Candidate utilities

- turn title generation
- acronym/glossary extraction for current session
- short "what changed in last N turns" digest
- classify turn intent/topic tags
- suggest better search query terms from current context
- convert verbose tool output into bullet digest

## Value

- Frequent quality-of-life improvements.
- Low-risk experimentation surface.

## Rough token cost

- Mostly Low per invocation.
- Aggregate can become Medium if called automatically too often.

## Implemented now

- Utility registration contract:
  - canonical registry with bounded utility set (5 max)
  - each utility declares owner, budget cap, success metric, removal criteria, fallback behavior
- First low-cost utility batch:
  - `turn_title`
  - `glossary_extract`
  - `recent_changes_digest`
  - `intent_tags`
  - `search_query_terms`
- Dispatcher execution path:
  - list via `DataDispatcher.list_utilities()`
  - run via `DataDispatcher.run_utility(...)` through `utility_custom` purpose
  - deterministic fallback per utility when disabled/blocked

## Deferred follow-ups

- UI utility launcher.
- Usage-quality telemetry per utility.
