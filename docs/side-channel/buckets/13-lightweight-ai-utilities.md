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

## Ready to start?

Yes incrementally.

Definition of ready:
- each utility declares: purpose, budget cap, fallback behavior, success metric

