# Analytics Dashboard - Findings & Blockers

**Date**: 2026-02-01
**Status**: Blocked - needs architecture decisions

## User Requirements

User wants **one unified analytics dashboard** showing token usage breakdowns across multiple dimensions:

1. **Cache status** - cached vs fresh tokens (CRITICAL - this is missing from current Cost panel)
2. **Subagent type** - breakdown by Explore, Plan, Bash, etc.
3. **Content type** - system prompts, tool results, conversation, code
4. **Time dimension** - trends over session or across sessions
5. **Input/output split** - input tokens vs output tokens

**UX**: Single dashboard, cycle through dimensional views with Tab key.

## Current Panel Analysis

### Stats Panel
- **Shows**: Request count, Input/Output/Cache tokens, Cache hit %, Models used
- **Data source**: `turns` table, actual API token counts
- **Good**: Real data from API usage fields

### Economics Panel
- **Shows**: Per-tool breakdown (calls, input↑, results↓)
- **Data source**: `tool_invocations` table
- **PROBLEM**: Uses byte-based token estimation (`estimate_tokens("x" * bytes)`) - **FAKE DATA**
- **User mandate**: "We should not be estimating tokens based on bytes. PERIOD."

### Timeline Panel
- **Shows**: Per-turn sequence, budget breakdown (system/tools/conv), cache %, delta
- **Data source**: `turns` table + request_json analysis
- **PROBLEM**: Mixes estimated breakdowns with actual token counts

## Data Availability

### Cache Data ✅
- Available in `turns` table:
  - `cache_read_tokens` - actual tokens from cache
  - `cache_creation_tokens` - actual tokens added to cache
  - `input_tokens` - actual fresh input tokens
- Can compute cache hit rate: `cache_read / (input + cache_read)`

### Subagent Data ⚠️
- **Subagent type IS captured** in request_json:
  ```json
  {"type": "tool_use", "name": "Task", "input": {"subagent_type": "Explore", ...}}
  ```
- **NOT extracted to queryable column** - `tool_invocations` table has no `subagent_type` field
- **Token attribution unclear**:
  - When parent calls Task(subagent_type="Explore"), subagent makes own API calls
  - Do subagent calls appear in same session_id or different session_id?
  - No correlation mechanism to link subagent sessions back to parent Task invocation

### Content Type Data ❌
- **Not tracked by API** - Anthropic doesn't break down input_tokens by content type
- Can only estimate from request_json structure (system blocks, tool blocks, message blocks)
- Estimates are unreliable and user rejected them

### Input/Output Split ✅
- Available in `turns` table:
  - `input_tokens` (fresh input)
  - `cache_read_tokens` (cached input)
  - `output_tokens` (always fresh)

## Critical Decisions Needed

### Decision 1: Subagent Token Attribution

**Option A - Tool-level only**
- Track subagent_type in `tool_invocations` table
- Show "which subagents were called" and "how many times"
- **Cannot show subagent's own API token usage** (only parent's tool invocation bytes)

**Option B - Session correlation**
- Add mechanism to link subagent sessions back to parent Task invocation
- Track session parent/child relationships
- Requires architecture changes to session management

**Option C - Defer feature**
- Ship dashboard without subagent breakdown
- Add subagent tracking in future iteration

### Decision 2: Content Type Breakdown

**Decision: Option B (skip entirely).**

Rationale:
- Anthropic usage data does not provide content-type token attribution.
- Request-JSON-derived estimates were explicitly rejected by the user.
- Analytics dashboard v1 must use only real API token counts.

Decision notes:
- Do not implement content-type token charts/tables in v1.
- Do not backfill with estimated values labeled as "estimated".
- If Anthropic adds authoritative content-type usage fields later, revisit.

### Decision 3: Replace or Augment Panels?

**Option A - Replace all three**
- Remove Stats, Economics, Timeline
- Single Analytics dashboard

**Option B - Add alongside**
- Keep existing panels
- Add new Analytics dashboard
- Let user choose

**Option C - Incremental migration**
- Phase 1: Add Analytics with real data only (cache, input/output, time)
- Phase 2: Deprecate Economics (fake byte estimates)
- Phase 3: Merge Stats + Timeline into Analytics

## What We Can Build Now (No Blockers)

**Minimal Viable Dashboard** with only REAL data:

```
┌─ Analytics Dashboard ─────────────────┐
│ Session: 150K tokens ($1.20)          │
│ ├─ Input:  80K (53%) | Output: 70K   │
│ └─ Cached: 109K (73% hit rate)        │
├────────────────────────────────────────┤
│ Cache Breakdown                        │
│ ├─ Cached:  109K ($0.30)              │
│ └─ Fresh:    41K ($0.90)              │
├────────────────────────────────────────┤
│ [Tab: Timeline View]                   │
│ Turn  Input  Output  Cache%    Δ      │
│    1   15K    12K      0%     --       │
│    2   18K    14K     44%   +2.5K      │
│    3   20K    16K     60%   +1.8K      │
└────────────────────────────────────────┘
```

**Data source**: `turns` table only (all real API counts)

**Views**:
1. **Summary** - session totals, cache efficiency
2. **Timeline** - per-turn progression (already works, just reuse)
3. **Models** - breakdown by model (if multiple models used)

**What's missing**:
- Subagent breakdown (blocked on Decision 1)
- Content type breakdown (blocked on Decision 2)
- Tool economics (blocked on fixing byte estimation)

## Next Steps

1. **User decides** on Decision 1 and 3 (Decision 2 is resolved: skip content-type breakdown)
2. **If going minimal**: Implement dashboard with cache/input/output/timeline only
3. **If doing subagents**: Design session correlation mechanism first
4. **Economics panel**: Either fix to use real data or remove it

## Key Constraints

- **No fake data** - user explicitly rejected byte-based token estimates
- **Real API counts only** - use `turns` table fields, not estimates
- **Cache visibility is critical** - this is the #1 missing metric
