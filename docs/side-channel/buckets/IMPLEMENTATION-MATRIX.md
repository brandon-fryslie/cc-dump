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

Implemented now:
- canonical artifact schema + serializer/deserializer
- dispatcher checkpoint creation over selected ranges
- deterministic checkpoint diff output linked by checkpoint IDs/ranges

## 09 Action/deferred extraction

Implementation:
- extraction schema and approval workflow
- optional beads creation bridge

Implemented now:
- normalized action/deferred schema + parser
- staged review workflow (no auto-persist)
- explicit acceptance persistence with `create_beads` confirmation gate
- default beads bridge adapter (`bd create`) for accepted-item issue links

## 10 Handoff notes

Implementation:
- fixed template output sections + source links

Implemented now:
- fixed section contract with required headings/source refs
- dispatcher handoff generation + fallback behavior
- latest artifact snapshot API for resume workflows

## 11 Release notes/changelog

Implementation:
- scoped generation over selected ranges/checkpoints
- output templates

Implemented now:
- deterministic section templates with variant renderers
- dispatcher scoped generation with source-linked entries
- draft retrieval/render APIs for review/edit/export handoff

## 12 Incident/debug timeline

Implementation:
- chronological extractor using selected ranges/events
- source-linked timeline entries

Implemented now:
- normalized timeline entry schema with source links
- dispatcher extraction flow with fallback safety
- facts-only default + optional hypothesis mode toggle

## 13 Lightweight utilities

Implementation:
- registered utility catalog (`utility_<name>`)
- per-utility budget and purpose attribution

Implemented now:
- canonical bounded utility registry with lifecycle metadata
- first batch of 5 low-cost utilities
- dispatcher utility execution path with deterministic fallbacks

## 14 Conversation Q&A textbox

Implementation:
- textbox + explicit scope selection
- response with source references

Implemented now:
- scoped request contract with explicit whole-session confirmation
- dispatcher Q&A execution with source-linked responses + fallback
- pre-send budget estimate object integrated into send flow API

## 15 Evaluation and quality gates

Implementation:
- benchmark harness per purpose
- promotion gates tracked in CI

Implemented now:
- canonical per-purpose acceptance thresholds in code
- deterministic fixed-corpus evaluation harness with JSON artifact output
- CI gate step that fails on threshold regressions

## 16 Redaction and data boundaries

Implementation:
- centralized context minimizer/redaction pipeline before dispatch
- redaction policy version tagging in run metadata

Placeholder:
- policy defined, enforcement hook deferred
