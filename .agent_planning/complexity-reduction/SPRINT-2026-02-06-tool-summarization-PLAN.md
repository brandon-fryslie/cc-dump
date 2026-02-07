# Sprint: tool-summarization - Extract Tool Use Summarization from render_blocks()
Generated: 2026-02-06
Confidence: HIGH: 6, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION
Source: EVALUATION-2026-02-06-050000.md

## Sprint Goal
Extract tool-use summarization from render_blocks() into a ToolUseSummaryBlock IR type and a pure pre-pass function, making render_blocks() a clean block dispatcher with no aggregation state.

## Scope
**Deliverables:**
- ToolUseSummaryBlock dataclass in formatting.py
- `collapse_tool_runs(blocks, tools_on)` pure function in rendering.py
- ToolUseSummaryBlock renderer and registry entries in rendering.py
- Simplified render_blocks() that delegates to the pre-pass
- Verify/close bug cc-dump-1vp (evaluation found the reported root cause was wrong)
- Updated and new tests covering the full display path

## Work Items

### P0 - Verify Bug cc-dump-1vp

**Dependencies**: None
**Spec Reference**: ARCHITECTURE.md (two-stage pipeline) | **Status Reference**: EVALUATION-2026-02-06-050000.md "Bug cc-dump-1vp is Likely Misdiagnosed"

#### Description
The evaluation found that the bug description is factually incorrect: `render_turn_to_strips()` at rendering.py:479 already iterates over `render_blocks()` output, so the summary IS generated for completed turns. Before changing any code, verify whether the bug is real or stale by inspecting the code paths. If stale, close cc-dump-1vp with a reason. If real (e.g., cache invalidation issue), document the actual root cause as a finding before proceeding.

#### Acceptance Criteria
- [ ] Confirmed that `render_turn_to_strips()` calls `render_blocks()` (not `render_block()` individually)
- [ ] Confirmed that `TurnData.compute_relevant_keys()` includes "tools" when ToolUseBlocks are present
- [ ] cc-dump-1vp closed with documented rationale, OR actual root cause documented as a new finding
- [ ] If bug is real, root cause is captured and addressed in subsequent work items

#### Technical Notes
The evaluation already traced the code and concluded the bug description is wrong. The verification is a confirmation step, not research. Check: (1) rendering.py:479 uses `render_blocks()`, (2) widget_factory.py:62-73 `compute_relevant_keys()` iterates blocks and looks up `BLOCK_FILTER_KEY`, (3) ToolUseBlock maps to "tools" in `BLOCK_FILTER_KEY`. The streaming path uses `StreamToolUseBlock` (not `ToolUseBlock`), so it's a non-issue for streaming turns.

---

### P0 - Create ToolUseSummaryBlock Dataclass

**Dependencies**: None (can proceed in parallel with bug verification)
**Spec Reference**: ARCHITECTURE.md "Stage 1 -- formatting.py" | **Status Reference**: EVALUATION-2026-02-06-050000.md "Pre-Pass vs Post-Pass Design Question"

#### Description
Add a `ToolUseSummaryBlock(FormattedBlock)` dataclass to formatting.py. This block replaces a consecutive run of ToolUseBlocks when the tools filter is off. It stores the tool name counts needed for the summary display (e.g., `{"Bash": 2, "Read": 1}`) and the total count. It also stores the index of the first ToolUseBlock it replaced, so `render_blocks()` can return the correct block index for the summary line (needed by `render_turn_to_strips()` cache keying and `block_strip_map`).

#### Acceptance Criteria
- [ ] `ToolUseSummaryBlock` dataclass exists in formatting.py with fields: `tool_counts: dict` (name -> count), `total: int`, `first_block_index: int`
- [ ] Dataclass inherits from `FormattedBlock`
- [ ] Default values for all fields (empty dict, 0, 0) so construction is flexible
- [ ] Import added to rendering.py's import block

#### Technical Notes
Place the dataclass after `ToolResultBlock` (around line 120) to keep tool-related blocks grouped. Use `field(default_factory=dict)` for `tool_counts`. The `first_block_index` field stores the index in the original (pre-collapse) block list, not in the collapsed list. This is needed for `render_blocks()` to return the correct `(block_index, Text)` pair.

---

### P1 - Implement collapse_tool_runs() Pre-Pass

**Dependencies**: ToolUseSummaryBlock dataclass
**Spec Reference**: ARCHITECTURE.md "Stage 2 -- rendering.py" | **Status Reference**: EVALUATION-2026-02-06-050000.md "Recommended approach: Pure-function pre-pass"

#### Description
Add a `collapse_tool_runs(blocks, tools_on)` pure function in rendering.py. When `tools_on=True`, returns the input list unchanged. When `tools_on=False`, scans for consecutive runs of ToolUseBlock and replaces each run with a single ToolUseSummaryBlock. Non-ToolUseBlock items pass through unchanged. The function returns a new list; the input list is never mutated.

The function must preserve the original block indices: each element in the returned list carries the index it had in the original list (or, for ToolUseSummaryBlock, the index of the first block in the run). This is handled by returning `list[tuple[int, FormattedBlock]]` or by storing `first_block_index` on the summary block itself.

#### Acceptance Criteria
- [ ] `collapse_tool_runs(blocks, tools_on=True)` returns the original list with original indices
- [ ] `collapse_tool_runs(blocks, tools_on=False)` replaces consecutive ToolUseBlock runs with ToolUseSummaryBlock
- [ ] Non-ToolUseBlock items are never modified or reordered
- [ ] ToolUseSummaryBlock.tool_counts correctly tallies names from the replaced run
- [ ] ToolUseSummaryBlock.total equals the number of replaced blocks
- [ ] Function is pure (no side effects, no mutation of input)

#### Technical Notes
Return type: `list[tuple[int, FormattedBlock]]` where int is the original block index. This mirrors what `render_blocks()` already returns as `(block_index, Text)`. The function uses `type(block).__name__ == "ToolUseBlock"` for hot-reload safety (same pattern as existing code at rendering.py:411). Place the function after `_make_tool_use_summary()` (around line 378) since it replaces that function's role.

---

### P1 - Register ToolUseSummaryBlock in Renderer Registry

**Dependencies**: ToolUseSummaryBlock dataclass, collapse_tool_runs() function
**Spec Reference**: ARCHITECTURE.md "Stage 2 -- rendering.py" | **Status Reference**: EVALUATION-2026-02-06-050000.md "Interaction with BLOCK_FILTER_KEY Registry"

#### Description
Add a `_render_tool_use_summary()` renderer function and register `ToolUseSummaryBlock` in both `BLOCK_RENDERERS` and `BLOCK_FILTER_KEY`. The renderer produces the same output as the current `_make_tool_use_summary()` helper (dim text showing tool count and name breakdown). The filter key maps to `"tools"`. Since the summary only exists when tools=False, the filter value in the cache key will be False, and when tools=True the block is absent from the prepared list entirely.

#### Acceptance Criteria
- [ ] `_render_tool_use_summary(block, filters)` renders the same text format as current `_make_tool_use_summary()`
- [ ] `"ToolUseSummaryBlock"` registered in `BLOCK_RENDERERS` dict
- [ ] `"ToolUseSummaryBlock"` registered in `BLOCK_FILTER_KEY` with value `"tools"`
- [ ] Renderer always returns a Text (never None), since the summary should always be visible when it exists

#### Technical Notes
The renderer signature must match `BlockRenderer = Callable[[FormattedBlock, dict], Text | None]`. The function reads `block.tool_counts` and `block.total` instead of receiving a list of ToolUseBlock objects. The existing `_make_tool_use_summary()` can be removed after this is done (it becomes dead code). The filter key `"tools"` ensures `TurnData.compute_relevant_keys()` picks it up automatically for cache invalidation.

---

### P1 - Simplify render_blocks() to Use Pre-Pass

**Dependencies**: collapse_tool_runs(), ToolUseSummaryBlock renderer registration
**Spec Reference**: ARCHITECTURE.md "Stage 2 -- rendering.py" | **Status Reference**: EVALUATION-2026-02-06-050000.md "render_blocks() Dual Responsibility"

#### Description
Refactor `render_blocks()` to use `collapse_tool_runs()` as a pre-pass, removing the `pending_tool_uses` accumulation state and the inner `flush_tool_uses()` function. The new implementation: (1) call `collapse_tool_runs(blocks, tools_on)` to get the prepared list with indices, (2) iterate the prepared list, calling `render_block()` for each, (3) collect non-None results as `(original_index, Text)`. This makes render_blocks() a clean dispatcher with no aggregation logic.

After simplification, delete the now-unused `_make_tool_use_summary()` helper.

#### Acceptance Criteria
- [ ] `render_blocks()` no longer contains `pending_tool_uses` list or `flush_tool_uses()` inner function
- [ ] `render_blocks()` calls `collapse_tool_runs()` as first step
- [ ] `render_blocks()` return type and semantics unchanged: `list[tuple[int, Text]]` with original block indices
- [ ] `_make_tool_use_summary()` removed (dead code after refactor)
- [ ] All existing tests in test_tool_rendering.py still pass without modification (or with minimal adaptation to new block type)

#### Technical Notes
The `expanded_overrides` parameter still works: the pre-pass preserves original indices, so `expanded_overrides.get(i)` looks up the correct block. For ToolUseSummaryBlock, expanded_overrides is irrelevant (it's not expandable), but the index mapping must be consistent. The `render_turn_to_strips()` function does NOT change -- it already iterates `render_blocks()` output, so the refactoring is invisible to it.

---

### P2 - Update and Expand Tests

**Dependencies**: All above items
**Spec Reference**: CLAUDE.md "Test" section | **Status Reference**: EVALUATION-2026-02-06-050000.md "Missing Checks"

#### Description
Update existing tests in test_tool_rendering.py and add new tests to cover:
1. The `collapse_tool_runs()` function directly (unit tests)
2. The `_render_tool_use_summary()` renderer (unit test)
3. Integration test through `render_turn_to_strips()` verifying the summary appears in strip output
4. Filter toggle test: tools=True produces individual blocks, tools=False produces summary

The evaluation identified that no existing test exercises the summary through the `render_turn_to_strips()` path. Add at least one test that calls `render_turn_to_strips()` with ToolUseBlocks and tools=False and verifies the output strips contain summary text.

#### Acceptance Criteria
- [ ] Unit tests for `collapse_tool_runs()`: passthrough when tools_on=True, collapse when False, mixed block sequences, empty list, single ToolUseBlock
- [ ] Unit test for `_render_tool_use_summary()` renderer: correct text format, correct style
- [ ] Existing `TestRenderBlocksToolSummary` tests still pass (may need minor adaptation if render_blocks output changes)
- [ ] At least one integration test calling `render_turn_to_strips()` with ToolUseBlocks and verifying summary in strip text output
- [ ] Full test suite passes: `uv run pytest` shows no new failures

#### Technical Notes
For the `render_turn_to_strips()` integration test, a Rich Console is needed. Use `from rich.console import Console; console = Console(width=80, force_terminal=True)`. The strip text can be extracted by joining segments: `"".join(seg.text for strip in strips for seg in strip._segments)`. The test should verify that when tools=False, the summary text like "[used 3 tools:" appears in the strip output.

## Dependencies
```
P0: Verify cc-dump-1vp  (independent)
P0: ToolUseSummaryBlock  (independent)
         |
         v
P1: collapse_tool_runs() (depends on ToolUseSummaryBlock)
         |
         v
P1: Register renderer    (depends on collapse_tool_runs)
         |
         v
P1: Simplify render_blocks() (depends on renderer registration)
         |
         v
P2: Tests                (depends on all above)
```

## Risks
- **Cache key stability**: ToolUseSummaryBlock objects are created by the pure pre-pass function, so they get new `id()` values each call. In `render_turn_to_strips()`, the cache key uses `id(blocks[block_idx])`. Since `block_idx` refers to the original block list (not the collapsed list), the cache lookup will use `id(original_tooluse_block)`, which IS stable. The summary block is only used for rendering, not for cache keying. Verify this during implementation.
- **Index mapping correctness**: The pre-pass must return original block indices so `block_strip_map`, `expanded_overrides`, and cache keys all work. Off-by-one errors here would cause subtle display bugs. Mitigate with explicit tests for index values.
- **Hot-reload import pattern**: rendering.py imports from formatting.py with `from cc_dump.formatting import ...`. The new `ToolUseSummaryBlock` must be added to this import. Since rendering.py is a reloadable module, this follows the existing pattern and should work.
