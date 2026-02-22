# Bucket Implementation Matrix

This is the technical implementation plan across all buckets, including placeholder strategy.

`// [LAW:one-way-deps] Core lane/analytics contracts first; feature buckets build on those seams.`

## Foundation dependencies

- F1 ingress classification + lane routing (`00`)
- F2 per-purpose usage accounting (`01`)
- F3 prompt registry + prompt versioning (`06`)
- F4 budget guardrails (`07`)

Most other buckets depend on F1-F4.

## 00 Core debug lane

Implementation:
- classify side-channel at ingress (request marker)
- bind request_id to side-channel lane key
- show traffic in existing multi-session tabs/lanes
- keep primary lane free of side-channel

Placeholder now:
- marker-based classification and separate lane routing

## 01 Purpose cost analytics

Implementation:
- purpose required per side-channel request
- aggregate input/cache_read/cache_creation/output by purpose
- expose analytics snapshots in existing analytics surfaces

Placeholder now:
- purpose-level aggregation in analytics store + dispatcher analytics snapshot

## 02 Block summaries + cache

Implementation:
- summary key = content hash + prompt version
- local summary cache store
- on-demand summarize with cache fill

Placeholder path:
- summary generation with prompt registry integration; cache store deferred

## 03 Compaction strategies (deferred for discovery)

Implementation direction:
- explicit compaction artifacts with source range links
- user acceptance + rollback path

Status:
- discovery/deferred until quality rubric finalized

## 04 Proxy interception

Implementation:
- marker-strip transform before upstream
- streaming capture for side-channel lane
- preserve existing sink isolation

Placeholder now:
- marker stripping in request pipeline transform

## 05 Decision ledger

Implementation:
- structured decision schema + source links
- extraction prompt + merge/supersede flow

Placeholder:
- prompt/contract ready; extraction persistence pending

## 06 Prompt registry

Implementation:
- central purpose->prompt/version registry
- dispatcher uses registry only

Placeholder now:
- registry module in place for core purposes

## 07 Budget guardrails

Implementation:
- global kill, per-purpose enable, concurrency, timeout, token caps
- fallback behavior on guardrail hit

Placeholder now:
- global kill + max concurrency controls wired through settings

## 08 Summary checkpoints

Implementation:
- checkpoint artifacts with source ranges
- diff support between checkpoints

Placeholder:
- prompt/purpose contract only

## 09 Action/deferred extraction

Implementation:
- extraction schema and approval workflow
- optional beads creation bridge

Placeholder:
- prompt/purpose contract only

## 10 Handoff notes

Implementation:
- fixed template output sections + source links

Placeholder:
- prompt/purpose contract only

## 11 Release notes/changelog

Implementation:
- scoped generation over selected ranges/checkpoints
- output templates

Placeholder:
- prompt/purpose contract only

## 12 Incident/debug timeline

Implementation:
- chronological extractor using selected ranges/events
- source-linked timeline entries

Placeholder:
- prompt/purpose contract only

## 13 Lightweight utilities

Implementation:
- registered utility catalog (`utility_<name>`)
- per-utility budget and purpose attribution

Placeholder:
- taxonomy ready; utility execution hooks deferred

## 14 Conversation Q&A textbox

Implementation:
- textbox + explicit scope selection
- response with source references

Placeholder:
- purpose contract ready; UI/input flow deferred

## 15 Evaluation and quality gates

Implementation:
- benchmark harness per purpose
- promotion gates tracked in CI

Placeholder:
- gate definitions documented

## 16 Redaction and data boundaries

Implementation:
- centralized context minimizer/redaction pipeline before dispatch
- redaction policy version tagging in run metadata

Placeholder:
- policy defined, enforcement hook deferred

