# Definition of Done: Database as Single Source of Truth

**Sprint**: 2026-01-25-db-ssot
**Topic**: sqlite-tui
**Status**: READY FOR IMPLEMENTATION
**Confidence**: HIGH

## Acceptance Criteria

### 1. Database Query Layer
- [ ] `src/cc_dump/db_queries.py` exists with read-only query functions
- [ ] `get_session_stats(db_path, session_id, current_turn=None)` returns cumulative token counts
- [ ] `get_tool_invocations(db_path, session_id)` returns tool invocation data
- [ ] `get_turn_timeline(db_path, session_id)` returns turn data for timeline
- [ ] All queries use read-only connections (`file:path?mode=ro`)

### 2. StatsPanel Refactored
- [ ] StatsPanel queries database instead of accumulating token counts in-memory
- [ ] `refresh_from_db(db_path, session_id, current_turn=None)` method exists
- [ ] Token counts match database values (verified via SQL query)
- [ ] Current turn usage is merged for real-time feedback during streaming

### 3. TimelinePanel Refactored
- [ ] TimelinePanel queries database instead of using `turn_budgets` list
- [ ] Cache% displays realistic values (not 0% or 100% for all turns)
- [ ] Cache% calculated as: `cache_read / (input + cache_read) * 100`
- [ ] `refresh_from_db(db_path, session_id)` method exists

### 4. ToolEconomicsPanel Refactored
- [ ] ToolEconomicsPanel queries database instead of using `all_invocations` list
- [ ] `refresh_from_db(db_path, session_id)` method exists
- [ ] Aggregation matches database content

### 5. App State Cleanup
- [ ] `app_state["all_invocations"]` removed
- [ ] `app_state["turn_budgets"]` removed
- [ ] `app_state["current_budget"]` removed
- [ ] Only `current_turn_usage` dict exists for in-progress streaming

### 6. Hot-Reload Integration
- [ ] `db_queries.py` added to `_RELOAD_IF_CHANGED` in hot_reload.py
- [ ] Query module can be hot-reloaded while TUI is running

### 7. Tests Pass
- [ ] All existing tests pass
- [ ] New tests for db_queries functions exist and pass
- [ ] No runtime errors when running the proxy

## Verification Commands

```bash
# Run all tests
python -m pytest tests/ -v

# Verify db_queries module exists and is importable
python -c "from cc_dump import db_queries; print('OK')"

# Run the proxy and verify TUI works
# (manual verification - interact with TUI, check panels update correctly)
```

## SQL Verification

```sql
-- Verify stats panel shows correct cumulative counts
SELECT SUM(input_tokens), SUM(output_tokens), SUM(cache_read_tokens)
FROM turns WHERE session_id = ?;

-- Verify cache% calculation
SELECT sequence_num,
       ROUND(CAST(cache_read_tokens AS FLOAT) / NULLIF(input_tokens + cache_read_tokens, 0) * 100, 1) as cache_pct
FROM turns WHERE session_id = ? ORDER BY sequence_num;
```

## Exit Criteria

Implementation is complete when:
1. All acceptance criteria are checked off
2. All tests pass
3. The TUI runs without errors
4. Cache% shows realistic values for turns with actual cache data
