# 02 Block Summary Generation And Cache

Goal:
- Generate better summaries for blocks and reuse cached summaries when content is unchanged.

`// [LAW:one-source-of-truth] Block summary cache key must derive from canonical block identity/content hash.`
`// [LAW:dataflow-not-control-flow] Summary pipeline runs consistently; cache state determines work/no-work.`

## How it could work

- Compute stable `summary_key` from block content hash + summary prompt version.
- On render needs:
- read local summary cache
- if miss/stale, issue side-channel summary request
- store result with metadata (purpose=`block_summary`)
- Renderers consume summary text through existing summary paths.

## Value

- Dramatically improves scanability of dense technical blocks.
- Reduces repeated summarization costs on unchanged content.

## Rough token cost

- Initial summarization for many blocks: Medium-High.
- Steady state with local cache hits: Low.
- Worst case (no cache discipline): High.

## Ready to start?

Yes, with scope limits.

Start with:
- summarize only selected block types
- cap summaries per turn/session
- require explicit user action or threshold triggers

Unknowns:
- ideal freshness/invalidations when prompt strategy changes

Definition of ready:
- cache hit rate measurable
- summary quality acceptable in at least 2 target block categories

Implementation reference:
- `docs/side-channel/SUMMARY_CACHE_SCHEMA.md`
