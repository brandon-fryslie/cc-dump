# Definition of Done: tool-summarization
Generated: 2026-02-06
Status: READY FOR IMPLEMENTATION
Plan: SPRINT-2026-02-06-tool-summarization-PLAN.md
Source: EVALUATION-2026-02-06-050000.md

## Acceptance Criteria

### Bug cc-dump-1vp Verification
- [ ] Confirmed render_turn_to_strips() calls render_blocks() (not render_block() individually)
- [ ] Confirmed TurnData.compute_relevant_keys() includes "tools" for turns with ToolUseBlocks
- [ ] cc-dump-1vp issue closed with documented rationale (via `bd close cc-dump-1vp --reason "..."`)

### ToolUseSummaryBlock Dataclass
- [ ] Dataclass exists in formatting.py inheriting from FormattedBlock
- [ ] Fields: tool_counts (dict, default_factory=dict), total (int, default 0), first_block_index (int, default 0)
- [ ] Imported in rendering.py's import block

### collapse_tool_runs() Function
- [ ] Pure function in rendering.py: `collapse_tool_runs(blocks, tools_on) -> list[tuple[int, FormattedBlock]]`
- [ ] tools_on=True returns original blocks with their indices unchanged
- [ ] tools_on=False replaces consecutive ToolUseBlock runs with ToolUseSummaryBlock
- [ ] Non-ToolUseBlock items pass through with original indices
- [ ] Input list is never mutated

### ToolUseSummaryBlock Renderer
- [ ] `_render_tool_use_summary(block, filters)` function renders summary text
- [ ] Output matches existing format: "[used N tool(s): Name Mx, Name2 Nx]"
- [ ] Registered in BLOCK_RENDERERS as "ToolUseSummaryBlock"
- [ ] Registered in BLOCK_FILTER_KEY as "ToolUseSummaryBlock" -> "tools"

### Simplified render_blocks()
- [ ] No `pending_tool_uses` list in render_blocks()
- [ ] No `flush_tool_uses()` inner function in render_blocks()
- [ ] Uses collapse_tool_runs() as pre-pass
- [ ] Return type unchanged: list[tuple[int, Text]]
- [ ] Block indices in output refer to original block list positions
- [ ] `_make_tool_use_summary()` helper removed (dead code)

### Tests
- [ ] Unit tests for collapse_tool_runs(): passthrough, collapse, mixed sequences, empty, single block
- [ ] Unit test for _render_tool_use_summary() renderer
- [ ] Existing TestRenderBlocksToolSummary tests pass
- [ ] Integration test through render_turn_to_strips() with tools=False verifying summary in strips
- [ ] Full test suite passes: `uv run pytest` shows 0 failures

### Code Quality
- [ ] `just lint` passes with no new warnings
- [ ] `just fmt` produces no changes (code is formatted)
- [ ] No regressions in existing functionality
