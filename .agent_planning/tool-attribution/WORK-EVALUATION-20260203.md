# Work Evaluation - 2026-02-03
Scope: tool-attribution/token-counting-infra (Sprint 1)
Confidence: FRESH

## Goals Under Evaluation
From SPRINT-20260203-120000-token-counting-infra-DOD.md:
1. Token Counter Module (`token_counter.py` with tiktoken)
2. Schema Migration (v2 to v3, add input_tokens/result_tokens)
3. Wiring into store.py (`_commit_turn()` populates token counts)

## Persistent Check Results
| Check | Status | Output Summary |
|-------|--------|----------------|
| `uv run pytest` (sprint tests) | PASS | 56/56 passed in 0.12s |
| `uv run pytest` (all non-TUI) | PASS | 232/232 passed in 25.81s |
| `just lint` (sprint files) | PASS | All checks passed |
| tiktoken installed | PASS | tiktoken 0.12.0 |

Note: TUI integration/hot-reload/visual-indicator tests (59 failures) are caused by a pre-existing corruption in `formatting.py` working tree (line 1: `this is not valid python syntax !!!`). The committed version of `formatting.py` is clean. These failures are unrelated to this sprint.

## Acceptance Criteria Verification

### Token Counter Module
| Criterion | Status | Evidence |
|-----------|--------|----------|
| `token_counter.py` exists with `count_tokens(text, model) -> int` | PASS | File at `src/cc_dump/token_counter.py`, signature matches |
| Uses tiktoken with cl100k_base encoding | PASS | `_ENCODING = tiktoken.get_encoding("cl100k_base")` |
| Returns accurate token counts | PASS | Tests verify "Hello, world!" -> 3-4 tokens, JSON, code, unicode all correct |
| Zero imports from other cc_dump modules | PASS | Only imports: `import tiktoken` |
| Unit tests in `test_token_counter.py` | PASS | 8 tests: empty string, simple text, longer text, JSON, large text, caching, unicode, code |
| tiktoken in pyproject.toml | PASS | `"tiktoken>=0.5.0"` in dependencies |

### Schema Migration
| Criterion | Status | Evidence |
|-----------|--------|----------|
| `_create_tables()` includes input_tokens/result_tokens | PASS | CREATE TABLE has `input_tokens INTEGER NOT NULL DEFAULT 0, result_tokens INTEGER NOT NULL DEFAULT 0` |
| Migration via ALTER TABLE ADD COLUMN | PASS | `_migrate_v2_to_v3()` checks PRAGMA table_info then adds columns |
| SCHEMA_VERSION is 3 | PASS | `SCHEMA_VERSION = 3` in schema.py |
| Test: fresh DB has both columns | PASS | `test_fresh_database_has_token_columns` |
| Test: v2 DB migrated without data loss | PASS | `test_migration_adds_token_columns` verifies existing rows preserved with DEFAULT 0 |

### Wiring in store.py
| Criterion | Status | Evidence |
|-----------|--------|----------|
| INSERT includes input_tokens/result_tokens | PASS | `_commit_turn()` line 147-150 |
| Values from tiktoken (not estimates) | PASS | `input_tokens = count_tokens(inv.input_str)` uses real tiktoken |
| input_bytes/result_bytes still populated | PASS | `inv.input_bytes, inv.result_bytes` still in INSERT |
| Performance <10ms per turn | PASS | 10 tool invocations (20 calls): 1.2ms |
| Integration test end-to-end | PASS | `test_store_populates_token_counts`: mock request -> commit -> query DB -> verify non-zero tokens |

## Data Flow Verification
| Step | Expected | Actual | Status |
|------|----------|--------|--------|
| Tool input serialized | JSON string | `'{"file_path": "/foo.txt"}'` | PASS |
| Tool result extracted | Raw string | `'file contents here'` | PASS |
| count_tokens called | Returns int > 0 | Returns correct count | PASS |
| Stored in DB | Non-zero INTEGER | Verified via SQLite query | PASS |
| input_bytes preserved | Still populated | Still in INSERT statement | PASS |

## Break-It Testing
| Attack | Expected | Actual | Severity |
|--------|----------|--------|----------|
| Empty tool input `{}` | Minimal tokens | 1+ tokens (from `"{}"` serialization) | OK |
| Empty tool result `""` | 0 tokens | 0 tokens | OK |
| Multiple tools per turn | All counted | 2/2 invocations with tokens | OK |
| model param ignored | Uses cl100k_base | Same result regardless of model param | MINOR |

## Test Quality Assessment

### test_store_token_counting.py - NOT tautological
These tests call `writer.on_event()` which exercises the real `SQLiteWriter._commit_turn()` path, then queries the actual SQLite database. If you deleted `count_tokens` from `store.py`, these tests would fail with 0 token counts.

### test_token_counter.py - Proper unit tests
Direct tests of the `count_tokens` function with real tiktoken execution. Range assertions are appropriate (exact token counts depend on tiktoken version).

### test_schema.py - Proper migration tests
Tests both fresh creation and v2->v3 migration with real SQLite databases. Idempotency test is solid.

## Ambiguities Found
| Decision | What Was Assumed | Impact |
|----------|------------------|--------|
| `model` parameter ignored | Always use cl100k_base regardless of model arg | LOW - Plan explicitly says this, but param name `model` is misleading. The default value is `"cl100k_base"` which is an encoding name, not a model name. |
| Global mutable `_ENCODING` | Module-level cache via global | LOW - Acceptable for pure utility, but hot-reload may create stale reference if token_counter is reloaded (encoding would be re-created, which is fine since tiktoken encodings are stateless) |

## Assessment

### Working
- Token counter module: complete, correct, fast, properly isolated
- Schema migration: v2->v3 works, idempotent, preserves data
- Store wiring: real tiktoken counts stored in DB alongside existing byte counts
- All 56 sprint-specific tests pass
- All 232 non-TUI tests pass (no regressions)
- Performance well within bounds (1.2ms for 10 tools)

### Not Working
- Nothing. All acceptance criteria met.

### Minor Notes
- The `model` parameter in `count_tokens()` is misleadingly named -- it accepts encoding names like `"cl100k_base"` but the parameter is called `model`. However, the value is never used (always hardcoded to cl100k_base). This is a cosmetic issue, not a bug.
- The `_ENCODING` global cache is simple and effective. No thread-safety concern since tiktoken encoding objects are safe to share.

## Verdict: COMPLETE

All acceptance criteria verified through automated tests and manual runtime verification. No regressions detected. Performance within bounds. Integration test exercises the real system boundary end-to-end.
