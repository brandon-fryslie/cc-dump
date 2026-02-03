# Definition of Done: token-counting-infra
Generated: 2026-02-03-120000
Status: READY FOR IMPLEMENTATION
Plan: SPRINT-20260203-120000-token-counting-infra-PLAN.md

## Acceptance Criteria

### Token Counter Module
- [ ] `src/cc_dump/token_counter.py` exists with `count_tokens(text: str, model: str) -> int` function
- [ ] Uses tiktoken with cl100k_base encoding for token counting
- [ ] Returns accurate token counts (~95% accuracy vs Claude's tokenizer)
- [ ] Module has zero imports from other cc_dump modules (leaf dependency)
- [ ] Unit tests in `tests/test_token_counter.py` verify:
  - Correct token counts for sample texts
  - Empty string returns 0
  - Large texts handled correctly
  - Encoding cached and reused
- [ ] tiktoken added to pyproject.toml dependencies

### Schema Migration
- [ ] `schema.py` `_create_tables()` includes `input_tokens` and `result_tokens` columns in `tool_invocations` CREATE TABLE
- [ ] Migration function adds columns to existing databases via `ALTER TABLE ADD COLUMN`
- [ ] `SCHEMA_VERSION` is 3
- [ ] Test verifies fresh DB has both columns
- [ ] Test verifies existing DB (version 2) gets columns added without data loss

### Wiring in store.py
- [ ] `_commit_turn()` INSERT includes `input_tokens` and `result_tokens` values
- [ ] Values come from tiktoken local counting (not estimates, not API calls)
- [ ] `input_bytes` and `result_bytes` continue to be populated
- [ ] Performance: token counting adds <10ms overhead per turn
- [ ] Integration test verifies end-to-end: mock request with tool use → commit → query DB → verify token counts

## Verification
- [ ] `uv run pytest` passes with all new and existing tests
- [ ] `just lint` passes
- [ ] `tiktoken` appears in `uv pip list` after installation
- [ ] Manual verification: run cc-dump with a real Claude Code session, check DB for non-zero `input_tokens` and `result_tokens` in `tool_invocations` table (should be accurate within ~5% of actual)
