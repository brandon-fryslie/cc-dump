# Sprint: model-toggle - Tool Economics Model Breakdown Toggle
Generated: 2026-02-03-150000
Confidence: HIGH
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Add Ctrl+M toggle to economics panel to switch between aggregate view (default) and per-model breakdown view.

## User Requirements Clarification
- Tools are called with different models throughout a session (Sonnet, Opus, Haiku)
- Database already tracks model per tool invocation via turn_id → turns.model JOIN
- User wants two views:
  - **Default (aggregate)**: One row per tool, all models combined
  - **Breakdown (Ctrl+M)**: Separate rows per (tool, model) combination

## Scope

### In Scope
- Query layer: `get_tool_economics()` with `group_by_model` parameter
- Panel state: track current view mode (aggregate vs breakdown)
- Keybinding: Ctrl+M to toggle view
- Renderer: support both layouts with model column when in breakdown mode
- Column cleanup: ensure clear naming (already done in Sprint 2)

### Out of Scope
- Sub-agent identification (deferred, not needed for this feature)
- Cost in dollars (only normalized units)
- Additional views beyond aggregate/breakdown

## Work Items

### P1 - Update Query Layer [HIGH]

**File**: `src/cc_dump/db_queries.py`

Add `group_by_model` parameter to `get_tool_economics()`:
- When `False` (default): aggregate by tool_name only (existing behavior)
- When `True`: group by (tool_name, model) for breakdown view

Return structure needs model field:
- Update `ToolEconomicsRow` dataclass to include optional `model` field
- When aggregate: model=None
- When breakdown: model="claude-sonnet-4-20250514" etc.

SQL changes:
- Aggregate mode: `GROUP BY ti.tool_name`
- Breakdown mode: `GROUP BY ti.tool_name, t.model`
- Sorting: by norm_cost DESC, then by tool_name, then by model

### P2 - Update Panel Widget [HIGH]

**File**: `src/cc_dump/tui/widget_factory.py`

Add to `ToolEconomicsPanel`:
- `_breakdown_mode: bool = False` state
- `toggle_breakdown()` method to flip mode
- `refresh_from_db()` passes `group_by_model=self._breakdown_mode` to query
- Keybinding handler for Ctrl+M

### P3 - Update Renderer [HIGH]

**File**: `src/cc_dump/tui/panel_renderers.py`

Update `render_economics_panel()`:
- Detect breakdown mode by checking if any row has model != None
- **Aggregate layout**: `Tool | Calls | Input (Cached) | Output | Norm Cost`
- **Breakdown layout**: `Tool | Model | Calls | Input (Cached) | Output | Norm Cost`
- Model column shows short name: "Sonnet 4.5", "Opus 4.5", "Haiku 4.5"

### P4 - Update Dataclass [HIGH]

**File**: `src/cc_dump/analysis.py`

Update `ToolEconomicsRow`:
- Add `model: str | None = None` field
- Keep all existing fields unchanged

### P5 - Tests [HIGH]

**File**: `tests/test_tool_economics.py`

Add test cases:
- Query with `group_by_model=True` returns per-model rows
- Same tool with different models produces separate rows
- Norm cost correctly calculated per model
- Aggregate mode sums across models correctly
- Renderer handles both layouts

## Dependencies
- Sprint 2 complete ✓ (query layer and rendering exist)
- No external blockers

## Risks
- **Model name formatting**: Full model names are long ("claude-sonnet-4-20250514"). Solution: create helper to extract short name ("Sonnet 4.5").

## Technical Notes

### Model Name Extraction
Use existing `classify_model()` from `analysis.py` to get model family, or add helper:
```python
def format_model_short(model: str) -> str:
    if "opus" in model.lower():
        return "Opus 4.5"
    elif "sonnet" in model.lower():
        return "Sonnet 4.5"
    elif "haiku" in model.lower():
        return "Haiku 4.5"
    return model[:20]  # fallback
```

### Column Width Adjustments
Breakdown view needs wider first column or split columns:
- Aggregate: `Tool` (12 chars)
- Breakdown: `Tool` (12 chars) + `Model` (10 chars)

## Exit Criteria
- [ ] Ctrl+M toggles between views without errors
- [ ] Aggregate view shows one row per tool (existing behavior maintained)
- [ ] Breakdown view shows separate rows for each (tool, model) pair
- [ ] Both views show correct normalized costs
- [ ] Tests pass for both modes
- [ ] No regression in existing panel functionality
