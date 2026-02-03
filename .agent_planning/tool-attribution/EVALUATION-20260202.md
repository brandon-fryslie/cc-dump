# Evaluation: tool-attribution
Timestamp: 2026-02-02
Git Commit: a11672a

## Executive Summary
Overall: 0% complete | Critical issues: 1 fundamental blocker | Tests reliable: N/A (feature not started)

The Anthropic streaming API does **not** provide per-content-block token counts. Token usage is reported only as turn-level totals in `message_start` and `message_delta` events. This means the ticket as written (cc-dump-un8: "Store actual input_tokens, output_tokens per tool invocation") is **impossible to implement with actual data** from the API. The only options are estimation or approximation, which the user has explicitly rejected.

## Runtime Check Results
| Check | Status | Output |
|-------|--------|--------|
| tests/test_analysis.py | PASS | 41/41 passing |
| Schema existence | PASS | tool_invocations table exists with turn_id FK |
| Current economics panel | WORKS | Shows byte-based estimates (user-rejected approach) |

## Missing Checks
- No test for per-tool token query with actual token data (feature does not exist)
- No integration test verifying what fields the Anthropic API actually returns in streaming events

## Findings

### Current tool_invocations Schema
**Status**: COMPLETE (for what it stores)
**Evidence**: `/Users/bmf/code/cc-dump/src/cc_dump/schema.py:74-82`
```python
CREATE TABLE IF NOT EXISTS tool_invocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id INTEGER NOT NULL REFERENCES turns(id),
    tool_name TEXT NOT NULL,
    tool_use_id TEXT NOT NULL,
    input_bytes INTEGER NOT NULL DEFAULT 0,
    result_bytes INTEGER NOT NULL DEFAULT 0,
    is_error INTEGER NOT NULL DEFAULT 0
);
```
**Issues**: Already has `turn_id` FK, so model and turn-level tokens are already accessible via JOIN. Adding per-tool token columns would require a data source that does not exist.

### Tool Invocation Data Source
**Status**: COMPLETE (for byte data)
**Evidence**: `/Users/bmf/code/cc-dump/src/cc_dump/store.py:138-145`
Tool invocations are extracted from the REQUEST body by `correlate_tools(messages)`. This means:
- `input_bytes` = JSON-serialized size of tool_use input
- `result_bytes` = size of tool_result content
- Both are byte counts of the JSON payload, NOT API token counts

### Token Data Availability from API
**Status**: FUNDAMENTAL BLOCKER
**Evidence**: Anthropic streaming API documentation (https://docs.anthropic.com/en/api/messages-streaming)
- `message_start.message.usage`: `{input_tokens, cache_read_input_tokens, cache_creation_input_tokens}` -- turn-level totals
- `message_delta.usage`: `{output_tokens}` -- turn-level total
- No `content_block_start` or `content_block_stop` usage data
- No per-tool-use token attribution exists in the API

### Existing Model Economics (for comparison)
**Status**: COMPLETE
**Evidence**: `/Users/bmf/code/cc-dump/src/cc_dump/db_queries.py:112-148`, `/Users/bmf/code/cc-dump/src/cc_dump/analysis.py:267-336`
Model economics work because the `turns` table already stores per-turn `model`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`. These are real API values. A `GROUP BY model` query gives real per-model attribution.

### Economics Panel (Current)
**Status**: WORKING BUT FAKE
**Evidence**: `/Users/bmf/code/cc-dump/src/cc_dump/db_queries.py:96-103`
```python
# Estimate tokens from bytes (using same heuristic as analysis module)
invocations.append(ToolInvocation(
    ...
    input_tokens_est=estimate_tokens("x" * input_bytes),
    result_tokens_est=estimate_tokens("x" * result_bytes),
    ...
))
```
These "token estimates" are `max(1, bytes // 4)`. User explicitly rejected this: "We should not be estimating tokens based on bytes. PERIOD." (per `docs/plans/2026-02-01-analytics-dashboard-findings.md:29`)

## Ambiguities Found

| Area | Question | How LLM Might Guess | Impact |
|------|----------|---------------------|--------|
| Token source | Can we get per-tool token counts from Anthropic API? | Assume yes, add columns | **CRITICAL**: API does not provide this. Implementation would store zeros or estimates. |
| Attribution semantics | What does "per-tool tokens" mean when API only has turn-level totals? | Estimate from bytes or proportional allocation | User rejected estimates; proportional allocation is also an estimate. |
| Ticket intent | Does cc-dump-un8 want actual API token counts per tool, or just better data than bytes? | Assume actual tokens | If actual tokens are impossible, the ticket needs rewriting. |
| Turn vs tool granularity | A turn may have 0 or many tool uses. How to allocate turn tokens to tools? | Proportional to bytes | Any allocation is an estimate, which is rejected. |

## Technical Options Analysis

### Option A: Add token columns to tool_invocations (as ticket describes)
- **Problem**: No data source. API provides turn-level tokens only.
- **Would store**: Either zeros (useless) or estimates (rejected).
- **Verdict**: Cannot implement as written.

### Option B: Show turn-level real tokens, grouped by which tools were used in that turn
- **Approach**: Since `tool_invocations.turn_id` already links to `turns`, query:
  ```sql
  SELECT ti.tool_name, COUNT(*) as calls,
         SUM(t.input_tokens) as input_tokens, ...
  FROM tool_invocations ti
  JOIN turns t ON ti.turn_id = t.id
  WHERE t.session_id = ?
  GROUP BY ti.tool_name
  ```
- **Problem**: A turn with Bash + Read would attribute ALL turn tokens to BOTH tools. Double-counting.
- **Mitigation**: Show "turns containing this tool" not "tokens used by this tool"
- **Verdict**: Feasible, but semantics are different from what ticket requests.

### Option C: Proportional allocation based on bytes
- **Approach**: Tool's share of turn tokens = tool's bytes / total tool bytes in turn
- **Problem**: This is still an estimate. User rejected estimates.
- **Verdict**: Violates user mandate.

### Option D: Use token counting API pre-request
- **Approach**: Call `messages.countTokens` endpoint before each tool invocation
- **Problem**: cc-dump is a passive proxy. It observes traffic, it does not make additional API calls.
- **Verdict**: Architectural violation. Proxy should not generate API traffic.

### Option E: Show only what we actually have (bytes + turn-level real tokens)
- **Approach**: Keep bytes in tool_invocations, show model economics with real data, drop fake token estimates
- **Fix**: Remove `estimate_tokens()` calls from economics panel, show bytes as bytes
- **Verdict**: Honest, but may not satisfy the ticket.

## Dependencies and Blockers

1. **cc-dump-nen** (new panel columns) is explicitly blocked by cc-dump-un8 (this ticket)
2. **cc-dump-dos** (remove byte estimates) can be done independently
3. **cc-dump-5nd** (subagent attribution) is a separate decision
4. **cc-dump-t9f** (column naming) can be done independently

## Recommendations

1. **PAUSE cc-dump-un8** -- The ticket as written assumes per-tool token data exists in the API. It does not. The ticket needs to be rewritten with achievable scope. Ask user: "The Anthropic API only provides turn-level token totals, not per-tool-use counts. What attribution semantics do you want?"

2. **Do cc-dump-dos now** -- Remove byte-based token estimates from the economics panel. Show bytes as bytes (e.g., "Input: 2.4KB") or show call counts only. This is independently valuable and unblocked.

3. **Consider Option B with clear labeling** -- Show "turns containing tool X: N turns, M total tokens" rather than "tool X used M tokens". This is honest about what the data actually represents.

4. **Model as first-class dimension** -- Since model IS available per-turn, and pricing differs by model, the economics panel could show model+tool matrix with real turn-level tokens. This gives the cost visibility the user wants.

## Verdict
- [ ] CONTINUE - Issues clear, implementer can fix
- [x] PAUSE - Ambiguities need clarification

**PAUSE reason**: The core ticket (cc-dump-un8) requests "Store actual input_tokens, output_tokens per tool invocation" but the Anthropic streaming API does not provide per-tool token counts. Only turn-level totals exist. The user needs to decide:

1. **What attribution semantics are acceptable?** Turn-level tokens grouped by tools present in that turn (with double-counting)? Proportional byte-based allocation (an estimate)? Or just call counts + bytes honestly labeled?
2. **Is cc-dump-dos (remove fake estimates) the right first step?** This is independently achievable and removes the most egregious problem.
3. **Should cc-dump-un8 be rewritten?** The current description assumes data that does not exist.
