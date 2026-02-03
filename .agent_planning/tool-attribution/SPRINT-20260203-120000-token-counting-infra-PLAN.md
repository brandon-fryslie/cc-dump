# Sprint: token-counting-infra - Token Counting Infrastructure
Generated: 2026-02-03-120000
Updated: 2026-02-03 (tiktoken decision)
Confidence: HIGH: 3, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION
Source: EVALUATION-20260202.md, user decision: use tiktoken

## Sprint Goal
Add per-tool-invocation token counting using tiktoken (local tokenizer), store results in the database, and populate on each turn commit.

## Context
The EVALUATION-20260202.md identifies that the Anthropic streaming API provides only turn-level token totals. User decision: use tiktoken for local token counting instead of API calls to avoid rate limits and network latency. tiktoken provides ~95% accuracy for Claude models, which is sufficient for economics analysis. No API calls needed - fast, simple, zero rate limit concerns.

## Scope
**Deliverables:**
- Token counter module (`src/cc_dump/token_counter.py`) using tiktoken for local counting
- Schema migration: add `input_tokens` and `result_tokens` columns to `tool_invocations` table
- Update `store.py` to call the token counter during `_commit_turn()` and populate the new columns
- Add tiktoken dependency to project

## Work Items

### P0 - Token Counter Module

**Dependencies**: tiktoken library (add to pyproject.toml)
**Spec Reference**: PROJECT_SPEC.md "Session-Level Analysis"
**Status Reference**: User decision: use tiktoken for local counting

#### Description
Create `src/cc_dump/token_counter.py` -- a pure utility module that uses tiktoken for local token counting. This module needs:
- A function `count_tokens(text: str, model: str = "cl100k_base") -> int` that uses tiktoken to count tokens
- Use the cl100k_base encoding (same as GPT-4, close approximation for Claude)
- No network calls, no API keys needed
- Fast: ~1ms per text string on modern hardware

Claude models use a custom tokenizer, but tiktoken's cl100k_base provides ~95% accuracy which is sufficient for economics analysis.

#### Acceptance Criteria
- [ ] `token_counter.py` exists with `count_tokens(text: str, model: str) -> int` function
- [ ] Returns accurate token counts using tiktoken
- [ ] Module has no dependencies on other cc_dump modules (pure utility, leaf in dependency graph)
- [ ] Unit tests verify correct token counts for sample texts
- [ ] tiktoken added to pyproject.toml dependencies

#### Technical Notes
- Import: `import tiktoken`
- Get encoding: `enc = tiktoken.get_encoding("cl100k_base")`
- Count: `len(enc.encode(text))`
- Cache the encoding instance (create once, reuse)
- This module is RELOADABLE (no state, pure functions)
- No error handling needed (tiktoken is reliable, no network/auth failures)

---

### P0 - Schema Migration: Add Token Columns to tool_invocations

**Dependencies**: None (can be done in parallel with token counter)
**Spec Reference**: ARCHITECTURE.md "Database Layer"
**Status Reference**: EVALUATION-20260202.md "Current tool_invocations Schema"

#### Description
Add `input_tokens INTEGER NOT NULL DEFAULT 0` and `result_tokens INTEGER NOT NULL DEFAULT 0` columns to the `tool_invocations` table. Use SQLite's `ALTER TABLE ADD COLUMN` for backward compatibility with existing databases. Bump `SCHEMA_VERSION` to 3.

#### Acceptance Criteria
- [ ] `schema.py` creates `tool_invocations` table with `input_tokens` and `result_tokens` columns for new databases
- [ ] Existing databases get the columns added via `ALTER TABLE ADD COLUMN` migration
- [ ] `SCHEMA_VERSION` incremented to 3
- [ ] Unit test verifies both fresh creation and migration paths

#### Technical Notes
- SQLite `ALTER TABLE ADD COLUMN` with `DEFAULT 0` is safe and backward-compatible. Existing rows get 0.
- The migration should be idempotent -- check if columns exist before adding.
- Pattern: check `PRAGMA table_info(tool_invocations)` for column existence.

---

### P1 - Wire Token Counting into store.py _commit_turn()

**Dependencies**: Token Counter Module, Schema Migration
**Spec Reference**: ARCHITECTURE.md "Database Layer" and "Event Flow"
**Status Reference**: EVALUATION-20260202.md "Tool Invocation Data Source"

#### Description
Update `store.py._commit_turn()` to call the token counter for each tool invocation and store actual token counts. For each `ToolInvocation` from `correlate_tools()`:
1. Count tokens for tool input (the JSON-serialized tool input)
2. Count tokens for tool result (the tool_result content)
3. Store both in the new `input_tokens` and `result_tokens` columns

This happens synchronously during `_commit_turn()` since the DB write is already in the DirectSubscriber path (not the TUI thread). Local counting is fast (~1ms per text), so performance impact is negligible.

#### Acceptance Criteria
- [ ] `_commit_turn()` calls token counter for each tool invocation's input and result
- [ ] `input_tokens` and `result_tokens` columns are populated with real counts from tiktoken
- [ ] Existing `input_bytes` and `result_bytes` columns continue to be populated (backward compat)
- [ ] Performance: token counting adds <10ms per turn (even with 10 tool invocations)
- [ ] Integration test verifies end-to-end: mock request with tool use → commit → query DB → verify token counts

#### Technical Notes
- `correlate_tools()` already extracts `input_str` and `result_str` -- pass these directly to count_tokens
- No model parameter needed from request - use default "cl100k_base" encoding
- No error handling needed - tiktoken is reliable and fast
- Cache the tiktoken encoding in module scope for reuse

## Dependencies
- Token Counter Module and Schema Migration are independent (parallel)
- Wiring into store.py depends on both above

## Risks
- **tiktoken accuracy for Claude**: ~95% accurate vs Claude's tokenizer. Acceptable for economics analysis. Mitigation: clearly label as "estimated tokens" in UI if needed.
- **Performance**: tiktoken is fast (~1ms per call), so no performance concerns even with many tools per turn.
