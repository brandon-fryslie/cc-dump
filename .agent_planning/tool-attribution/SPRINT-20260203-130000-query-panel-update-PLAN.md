# Sprint: query-panel-update - Query Layer & Panel Updates
Generated: 2026-02-03-130000
Confidence: HIGH: 3, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION
Source: EVALUATION-20260202.md

## Sprint Goal
Update the query layer and economics panel to display per-tool token data with cache attribution and normalized cost columns: Calls | Input (Cached) | Output (Cached) | Norm Cost.

## Blocked By
- SPRINT-20260203-120000-token-counting-infra (must have real token data in DB first)

## Scope
**Deliverables:**
- New query function `get_tool_economics()` in `db_queries.py` that JOINs tool_invocations with turns for cache attribution
- Updated `render_economics_panel()` in `panel_renderers.py` with new column layout
- Updated `ToolEconomicsPanel.refresh_from_db()` to use new query
- Updated `ToolAggregates` dataclass with real token fields and norm cost

## Work Items

### P0 - New Query: get_tool_economics()

**Dependencies**: Sprint 1 schema migration (input_tokens, result_tokens columns exist)
**Spec Reference**: PROJECT_SPEC.md "Session-Level Analysis" -- "per-tool cost breakdowns"
**Status Reference**: EVALUATION-20260202.md "Existing Model Economics (for comparison)" and "Economics Panel (Current)"

#### Description
Create a new query function `get_tool_economics()` in `db_queries.py` that returns per-tool aggregated data including real token counts and turn-level cache attribution. The key insight: each tool invocation has a `turn_id`, and each turn has `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, and `model`. We can:
1. Sum per-tool `input_tokens` and `result_tokens` from `tool_invocations` (actual counts from count_tokens API)
2. Attribute cache behavior proportionally: tool's share of turn cache = (tool_input_tokens / turn_total_input_tokens) * turn_cache_read_tokens
3. Include model for pricing calculation

Return a list of `ToolEconomicsRow` (new dataclass) with: name, calls, input_tokens, result_tokens, cache_read_est, model_key, norm_cost.

#### Acceptance Criteria
- [ ] `get_tool_economics()` function exists in `db_queries.py`
- [ ] Returns per-tool aggregates with real token counts (not byte estimates)
- [ ] Cache attribution is proportional based on tool's token share of the turn
- [ ] Results include model information for pricing
- [ ] Query performs well (single SQL query with GROUP BY, not N+1)

#### Technical Notes
- SQL approach: JOIN tool_invocations with turns, compute proportional cache share in Python (SQL can do it but Python is clearer).
- Cache attribution formula: `tool_cache_read = turn_cache_read * (tool_input_tokens / sum_of_all_tool_input_tokens_in_turn)`. If a turn has no tools, ignore. If a turn has tools but token counts are 0 (counting failed), skip cache attribution for that turn.
- The existing `get_model_economics()` pattern (lines 112-148 of db_queries.py) is the template to follow.

---

### P0 - Update ToolAggregates and Add ToolEconomicsRow

**Dependencies**: None
**Spec Reference**: PROJECT_SPEC.md "Session-Level Analysis"
**Status Reference**: EVALUATION-20260202.md "Economics Panel (Current)"

#### Description
The current `ToolAggregates` dataclass in `analysis.py` uses `input_tokens_est` and `result_tokens_est`. We need either:
1. A new `ToolEconomicsRow` dataclass for the economics panel (cleaner, separates concerns)
2. Or extend `ToolAggregates` to include cache and cost fields

Option 1 is preferred to avoid polluting the existing aggregation code. Create `ToolEconomicsRow` in `analysis.py` with fields matching the target panel columns:
- `name: str` -- tool name
- `calls: int` -- invocation count
- `input_tokens: int` -- total input tokens (real)
- `result_tokens: int` -- total result tokens (real)
- `cache_read_tokens: int` -- estimated cache read tokens (proportional)
- `norm_cost: float` -- normalized cost (using ModelPricing)

#### Acceptance Criteria
- [ ] `ToolEconomicsRow` dataclass exists in `analysis.py`
- [ ] Has all fields needed for the panel columns: name, calls, input_tokens, result_tokens, cache_read_tokens, norm_cost
- [ ] `norm_cost` is computed using the existing `ModelPricing` infrastructure
- [ ] Unit test verifies norm_cost calculation

#### Technical Notes
- Norm cost calculation: reuse the `ModelPricing` and `classify_model()` from analysis.py lines 267-302.
- Formula: `norm_cost = input_tokens * pricing.base_input + cache_read * pricing.cache_hit + result_tokens * pricing.output` (all in Haiku-normalized units).

---

### P1 - Update Economics Panel Display

**Dependencies**: ToolEconomicsRow, get_tool_economics()
**Spec Reference**: User directive for columns: "Calls | Input (Cached) | Output (Cached) | Norm Cost"
**Status Reference**: EVALUATION-20260202.md "Economics Panel (Current)" -- currently shows fake byte-based estimates

#### Description
Update `render_economics_panel()` in `panel_renderers.py` to display the new columns:
```
Tool Economics (session total):
  Tool          Calls   Input (Cached)   Output      Norm Cost
  Bash             12   45.2k (89%)      12.3k       1,234
  Read              8   23.1k (92%)       8.7k         567
  ...
```

Also update `ToolEconomicsPanel.refresh_from_db()` in `widget_factory.py` to call `get_tool_economics()` instead of `get_tool_invocations()` + `aggregate_tools()`.

#### Acceptance Criteria
- [ ] Panel shows columns: Tool, Calls, Input (Cached), Output, Norm Cost
- [ ] "Input (Cached)" shows total input tokens with cache hit percentage in parentheses
- [ ] "Output" shows result tokens (tool output, which maps to API input context on next turn)
- [ ] "Norm Cost" shows normalized cost in Haiku units
- [ ] When no tool data exists, shows "(no tool calls yet)"
- [ ] Columns align properly with right-justified numbers

#### Technical Notes
- Follow the existing `render_economics_panel()` pattern (panel_renderers.py lines 37-56).
- The function signature changes from `aggregates: list[ToolAggregates]` to `rows: list[ToolEconomicsRow]`.
- Cache percentage: `cache_pct = 100 * cache_read_tokens / (input_tokens + cache_read_tokens)` if denominator > 0.
- Column widths: Tool (12), Calls (5), Input (14), Output (8), Norm Cost (10).

## Dependencies
- Blocked by Sprint 1 (token-counting-infra) -- needs real token data in DB
- ToolEconomicsRow and get_tool_economics() can be developed in parallel
- Panel display update depends on both

## Risks
- **Cache attribution accuracy**: Proportional allocation is an approximation. A tool with lots of cached content might show lower cache hit than reality. Mitigation: document this as "estimated cache attribution" in the panel header.
- **Zero token counts**: If Sprint 1's count_tokens fails, all token columns show 0. Mitigation: show "-" instead of "0" when all token counts in a row are zero, with a note "(token counting unavailable)".
