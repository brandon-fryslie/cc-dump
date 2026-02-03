# Definition of Done: model-toggle
Generated: 2026-02-03-150000
Status: READY
Plan: SPRINT-20260203-150000-model-toggle-PLAN.md

## Acceptance Criteria

### Query Layer
- [ ] `get_tool_economics()` has `group_by_model: bool = False` parameter
- [ ] When `group_by_model=False`: returns one row per tool (aggregate)
- [ ] When `group_by_model=True`: returns rows grouped by (tool_name, model)
- [ ] `ToolEconomicsRow.model` field exists (str | None)
- [ ] Aggregate mode sets model=None, breakdown mode sets actual model string
- [ ] Norm cost calculation unchanged (already correct per Sprint 2)

### Panel Widget
- [ ] `ToolEconomicsPanel._breakdown_mode` state exists
- [ ] `toggle_breakdown()` method flips the mode and refreshes display
- [ ] Ctrl+M keybinding calls `toggle_breakdown()`
- [ ] `refresh_from_db()` passes `group_by_model=self._breakdown_mode` to query

### Renderer
- [ ] `render_economics_panel()` detects breakdown mode (rows with model != None)
- [ ] Aggregate layout: `Tool | Calls | Input (Cached) | Output | Norm Cost`
- [ ] Breakdown layout: `Tool | Model | Calls | Input (Cached) | Output | Norm Cost`
- [ ] Model column shows short names: "Sonnet 4.5", "Opus 4.5", "Haiku 4.5"
- [ ] Column alignment correct in both modes

### User Experience
- [ ] Default view is aggregate (one row per tool)
- [ ] Pressing Ctrl+M switches to breakdown view
- [ ] Pressing Ctrl+M again switches back to aggregate
- [ ] View persists during session (state maintained between refreshes)
- [ ] No visual glitches or flicker during toggle

### Tests
- [ ] Test: aggregate mode with mixed models produces single row per tool
- [ ] Test: breakdown mode with same tool + different models produces multiple rows
- [ ] Test: norm cost in aggregate equals sum of breakdown costs for same tool
- [ ] Test: renderer formats both layouts correctly
- [ ] Test: model name shortening works for all known models
- [ ] All existing tests still pass (no regression)

## Verification
- [ ] `uv run pytest` passes
- [ ] `just lint` passes
- [ ] Manual test: run cc-dump, generate traffic with multiple models, verify both views
- [ ] Manual test: Ctrl+M toggles smoothly without errors

## Examples

### Aggregate View (Default)
```
Tool Economics (session total):
  Tool          Calls  Input (Cached)      Output  Norm Cost
  Read             10      50.0k (89%)       12.0k      1,234
  Bash              5      30.0k (45%)        8.0k        890
```

### Breakdown View (Ctrl+M)
```
Tool Economics (by model):
  Tool          Model       Calls  Input (Cached)      Output  Norm Cost
  Read          Sonnet 4.5      7      35.0k (90%)        8.0k        820
  Read          Opus 4.5        3      15.0k (85%)        4.0k        414
  Bash          Haiku 4.5       5      30.0k (45%)        8.0k        890
```
