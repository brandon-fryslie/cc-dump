# Definition of Done: tool-correlation-summaries
Generated: 2026-01-30-110000
Status: PARTIALLY READY
Plan: SPRINT-20260130-110000-tool-correlation-summaries-PLAN.md

## Acceptance Criteria

### IR Extensions
- [ ] ToolUseBlock has `tool_use_id: str = ""` field
- [ ] ToolResultBlock has `tool_use_id: str = ""` field
- [ ] ToolResultBlock has `tool_name: str = ""` field
- [ ] `format_request()` populates `tool_use_id` on both block types
- [ ] `format_request()` populates `tool_name` on ToolResultBlock via lookup
- [ ] Existing code creating these blocks without new fields works (defaults)

### Color Correlation
- [ ] ToolUseBlock and matching ToolResultBlock share the same `msg_color_idx` value
- [ ] Different tool_use_id pairs get different cycling color indices
- [ ] Color assignment is deterministic for the same request body
- [ ] Rendering code unchanged (reads existing `msg_color_idx` field)

### Tool Result Summary
- [ ] `_render_tool_result` with tools filter ON: shows `[tool_result] ToolName (N bytes)`
- [ ] `_render_tool_result` with tools filter OFF: shows dim summary `[ToolName] (N bytes)`
- [ ] Error results show `[tool_result:error]` in full mode, `[ToolName:error]` in summary
- [ ] BLOCK_FILTER_KEY updated appropriately for ToolResultBlock

### Tests
- [ ] Unit test: format_request with tool_use/tool_result pairs verifies tool_use_id and tool_name populated
- [ ] Unit test: matching ToolUseBlock/ToolResultBlock have same color index
- [ ] Unit test: _render_tool_result with tool_name shows name in output
- [ ] Unit test: _render_tool_result with tools filter OFF shows summary
- [ ] All existing tests pass

## Exit Criteria (MEDIUM confidence items)
- [ ] Confirmed tool_use always precedes tool_result in API message order
- [ ] Color pool decision documented (same MSG_COLORS or separate)
- [ ] BLOCK_FILTER_KEY approach for summary visibility decided
- [ ] Re-render performance acceptable with filter key change
