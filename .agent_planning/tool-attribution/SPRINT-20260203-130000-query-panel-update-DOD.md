# Definition of Done: query-panel-update
Generated: 2026-02-03-130000
Status: READY FOR IMPLEMENTATION
Plan: SPRINT-20260203-130000-query-panel-update-PLAN.md

## Acceptance Criteria

### get_tool_economics() Query
- [ ] Function exists in `db_queries.py` with signature `get_tool_economics(db_path: str, session_id: str) -> list[ToolEconomicsRow]`
- [ ] Returns per-tool aggregates with real token counts from `tool_invocations.input_tokens` and `result_tokens`
- [ ] Cache attribution is proportional: tool's cache share = tool_input_tokens / turn_total_tool_tokens * turn_cache_read_tokens
- [ ] Model key is included per row for pricing
- [ ] Query uses a single SQL statement (no N+1 queries)
- [ ] Test verifies correct aggregation with mock DB data

### ToolEconomicsRow Dataclass
- [ ] Exists in `analysis.py` as `@dataclass class ToolEconomicsRow`
- [ ] Fields: name (str), calls (int), input_tokens (int), result_tokens (int), cache_read_tokens (int), norm_cost (float)
- [ ] Test verifies norm_cost calculation matches ModelPricing formulas

### Economics Panel Display
- [ ] `render_economics_panel()` signature accepts `list[ToolEconomicsRow]`
- [ ] Output columns: Tool, Calls, Input (Cached), Output, Norm Cost
- [ ] Input column shows "45.2k (89%)" format -- token count with cache hit percentage
- [ ] Numbers are right-aligned, tool names left-aligned
- [ ] When all token counts are 0, shows "--" instead of "0"
- [ ] Empty state shows "(no tool calls yet)"
- [ ] Test verifies formatted output matches expected column layout

### ToolEconomicsPanel Wiring
- [ ] `refresh_from_db()` calls `get_tool_economics()` (not `get_tool_invocations()` + `aggregate_tools()`)
- [ ] `_refresh_display()` passes `ToolEconomicsRow` list to renderer
- [ ] Panel updates correctly after each turn completes

## Verification
- [ ] `uv run pytest` passes with all new and existing tests
- [ ] `just lint` passes
- [ ] Manual verification: run cc-dump, observe economics panel shows real token data with cache percentages
- [ ] Visual check: columns align properly at various terminal widths
