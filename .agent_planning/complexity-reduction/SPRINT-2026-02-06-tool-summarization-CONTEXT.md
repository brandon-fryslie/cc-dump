# Implementation Context: tool-summarization
Generated: 2026-02-06
Source: EVALUATION-2026-02-06-050000.md
Plan: SPRINT-2026-02-06-tool-summarization-PLAN.md

## File Map

### Files to Modify
- `/Users/bmf/code/cc-dump/src/cc_dump/formatting.py` (add dataclass)
- `/Users/bmf/code/cc-dump/src/cc_dump/tui/rendering.py` (pre-pass, renderer, registry, simplify render_blocks)
- `/Users/bmf/code/cc-dump/tests/test_tool_rendering.py` (update and expand tests)

### Files Read-Only Reference
- `/Users/bmf/code/cc-dump/src/cc_dump/tui/widget_factory.py` (understand cache interaction, no changes needed)

---

## Work Item 1: Verify cc-dump-1vp

### Evidence locations
- `render_turn_to_strips()` at `/Users/bmf/code/cc-dump/src/cc_dump/tui/rendering.py` line 479:
  ```python
  for block_idx, text in render_blocks(blocks, filters, expanded_overrides):
  ```
  This proves render_turn_to_strips DOES call render_blocks(), contradicting the bug description.

- `compute_relevant_keys()` at `/Users/bmf/code/cc-dump/src/cc_dump/tui/widget_factory.py` lines 62-73:
  ```python
  def compute_relevant_keys(self):
      keys = set()
      for block in self.blocks:
          key = cc_dump.tui.rendering.BLOCK_FILTER_KEY.get(type(block).__name__)
          if key is not None:
              keys.add(key)
      self.relevant_filter_keys = keys
  ```

- `BLOCK_FILTER_KEY` at `/Users/bmf/code/cc-dump/src/cc_dump/tui/rendering.py` line 334:
  ```python
  "ToolUseBlock": "tools",
  ```

### Action
Close the issue:
```bash
bd close cc-dump-1vp --reason "Bug description was factually incorrect. render_turn_to_strips() at rendering.py:479 iterates render_blocks() output, which includes tool summary logic. The summary IS generated for completed turns. compute_relevant_keys() picks up 'tools' from ToolUseBlock via BLOCK_FILTER_KEY, so filter toggles trigger re-render correctly." --json
```

---

## Work Item 2: ToolUseSummaryBlock Dataclass

### Target file
`/Users/bmf/code/cc-dump/src/cc_dump/formatting.py`

### Insert location
After `ToolResultBlock` (line 119), before `ImageBlock` (line 122). This keeps tool-related blocks grouped.

### Code to add
```python
@dataclass
class ToolUseSummaryBlock(FormattedBlock):
    """Summary of a collapsed run of tool_use blocks (when tools filter is off)."""
    tool_counts: dict = field(default_factory=dict)  # {tool_name: count}
    total: int = 0
    first_block_index: int = 0  # index in original block list
```

### Pattern to follow
Same pattern as all other FormattedBlock subclasses in the file (lines 28-188). All use `@dataclass`, inherit from `FormattedBlock`, use default values for all fields.

---

## Work Item 3: collapse_tool_runs() Pre-Pass

### Target file
`/Users/bmf/code/cc-dump/src/cc_dump/tui/rendering.py`

### Insert location
After `_make_tool_use_summary()` (line 367-377), before `render_blocks()` (line 380). The function replaces the role of `_make_tool_use_summary()`.

### Import to add
At `/Users/bmf/code/cc-dump/src/cc_dump/tui/rendering.py` line 10-17, add `ToolUseSummaryBlock` to the import:
```python
from cc_dump.formatting import (
    FormattedBlock, SeparatorBlock, HeaderBlock, HttpHeadersBlock, MetadataBlock,
    SystemLabelBlock, TrackedContentBlock, RoleBlock, TextContentBlock,
    ToolUseBlock, ToolResultBlock, ImageBlock, UnknownTypeBlock,
    StreamInfoBlock, StreamToolUseBlock, TextDeltaBlock, StopReasonBlock,
    ErrorBlock, ProxyErrorBlock, LogBlock, NewlineBlock, TurnBudgetBlock,
    ToolUseSummaryBlock,
    make_diff_lines,
)
```

### Function signature and implementation pattern
```python
def collapse_tool_runs(blocks: list, tools_on: bool) -> list[tuple[int, FormattedBlock]]:
    """Pre-pass: collapse consecutive ToolUseBlock runs into ToolUseSummaryBlock.

    When tools_on=True, returns blocks with their original indices unchanged.
    When tools_on=False, consecutive ToolUseBlock runs are replaced with a
    single ToolUseSummaryBlock containing the aggregated counts.

    Returns list of (original_block_index, block) tuples.
    """
```

### Hot-reload pattern
Use `type(block).__name__ == "ToolUseBlock"` for block type checking (same as rendering.py line 411). Do NOT use `isinstance()`.

### Key logic
1. If `tools_on`, return `[(i, block) for i, block in enumerate(blocks)]`
2. If not `tools_on`, iterate blocks. Accumulate consecutive ToolUseBlock runs. When a non-ToolUseBlock is encountered (or end of list), flush the accumulated run as a ToolUseSummaryBlock. Use `collections.Counter` for tallying names (same as `_make_tool_use_summary` at line 369).

### Counter import
`collections.Counter` is already used inside `_make_tool_use_summary()` as a local import (line 369). For the new function, either import at module level or keep as local import. The existing pattern is local import, but since this is now a module-level function (not a helper), a module-level import from `collections` is cleaner.

---

## Work Item 4: ToolUseSummaryBlock Renderer

### Target file
`/Users/bmf/code/cc-dump/src/cc_dump/tui/rendering.py`

### Insert location
After `_render_tool_result()` (line 225), before `_render_image()` (line 228). Groups tool-related renderers together.

### Renderer function
```python
def _render_tool_use_summary(block: ToolUseSummaryBlock, filters: dict) -> Text | None:
    """Render a collapsed tool use summary line."""
    parts = ["{} {}x".format(name, count) for name, count in block.tool_counts.items()]
    t = Text("  ")
    t.append("[used {} tool{}: {}]".format(
        block.total, "" if block.total == 1 else "s", ", ".join(parts),
    ), style="dim")
    return t
```

This mirrors the existing `_make_tool_use_summary()` output format exactly (line 371-377).

### Registry entries

In `BLOCK_RENDERERS` dict (line 295-317), add:
```python
"ToolUseSummaryBlock": _render_tool_use_summary,
```

In `BLOCK_FILTER_KEY` dict (line 323-345), add:
```python
"ToolUseSummaryBlock": "tools",
```

---

## Work Item 5: Simplify render_blocks()

### Target file
`/Users/bmf/code/cc-dump/src/cc_dump/tui/rendering.py`

### Current code to replace (lines 380-424)
```python
def render_blocks(
    blocks: list[FormattedBlock],
    filters: dict,
    expanded_overrides: dict[int, bool] | None = None,
) -> list[tuple[int, Text]]:
    # ... current implementation with pending_tool_uses ...
```

### New implementation
```python
def render_blocks(
    blocks: list[FormattedBlock],
    filters: dict,
    expanded_overrides: dict[int, bool] | None = None,
) -> list[tuple[int, Text]]:
    """Render a list of FormattedBlock to indexed Rich Text objects, applying filters.

    When the tools filter is off, consecutive ToolUseBlocks are collapsed
    into a single summary line like '[used 3 tools: Bash 2x, Read 1x]'.

    Args:
        expanded_overrides: Optional dict mapping block_index -> expand state.
            Overrides filters["expand"] for individual collapsible blocks.

    Returns:
        List of (block_index, Text) pairs. The block_index is the position
        in the original blocks list. Summary lines use the index of the
        first ToolUseBlock in the collapsed run.
    """
    tools_on = filters.get("tools", False)
    prepared = collapse_tool_runs(blocks, tools_on)

    rendered: list[tuple[int, Text]] = []
    for orig_idx, block in prepared:
        block_expanded = expanded_overrides.get(orig_idx) if expanded_overrides else None
        r = render_block(block, filters, expanded=block_expanded)
        if r is not None:
            rendered.append((orig_idx, r))
    return rendered
```

### Code to delete
- `_make_tool_use_summary()` function (lines 367-377) -- dead code after refactor
- The entire old body of `render_blocks()` (lines 399-424): `pending_tool_uses`, `flush_tool_uses()`, the for loop with special-casing

### Interaction with render_turn_to_strips()
`render_turn_to_strips()` (line 441-513) calls `render_blocks()` at line 479. It then uses `block_idx` from the returned tuples to look up `blocks[block_idx]` at line 484 for cache keying. Since `block_idx` still refers to the original block list (not the collapsed list), `blocks[block_idx]` correctly resolves to the original ToolUseBlock (or whatever block). For summary lines, `block_idx` is the first ToolUseBlock's index, so `blocks[block_idx]` is a ToolUseBlock, and `id(blocks[block_idx])` is stable across calls. Cache keying works correctly.

The `filter_key` lookup at line 485:
```python
filter_key = BLOCK_FILTER_KEY.get(type(block).__name__)
```
This looks up the type of the ORIGINAL block (ToolUseBlock), not ToolUseSummaryBlock. The filter key is "tools" in both cases, so the cache key is the same. No issue here.

### Important: render_turn_to_strips cache key uses original block, not summary block
At rendering.py:484, the code does `block = blocks[block_idx]`. Since `blocks` is the original list and `block_idx` from `collapse_tool_runs` is the first ToolUseBlock's index, this correctly gets the original ToolUseBlock for cache keying. The ToolUseSummaryBlock is only used for rendering via `render_block()`, not for cache identity.

---

## Work Item 6: Tests

### Target file
`/Users/bmf/code/cc-dump/tests/test_tool_rendering.py`

### Imports to add
```python
from cc_dump.formatting import ToolUseSummaryBlock
from cc_dump.tui.rendering import collapse_tool_runs, _render_tool_use_summary, render_turn_to_strips
```

### New test class: TestCollapseToolRuns
Place after existing `TestRenderBlocksToolSummary` class.

Test cases:
1. `test_passthrough_when_tools_on` -- `collapse_tool_runs([blocks], tools_on=True)` returns all blocks with correct indices
2. `test_collapse_consecutive_tool_uses` -- 3 consecutive ToolUseBlocks become 1 ToolUseSummaryBlock
3. `test_mixed_blocks_preserved` -- Text, ToolUse, ToolUse, Text -> Text, Summary, Text
4. `test_empty_list` -- returns empty list
5. `test_single_tool_use` -- single ToolUseBlock becomes ToolUseSummaryBlock with total=1
6. `test_non_consecutive_runs` -- ToolUse, Text, ToolUse -> Summary, Text, Summary (two separate runs)
7. `test_indices_correct` -- verify orig_idx values are correct for each returned item

### New test class: TestRenderToolUseSummary
Test cases:
1. `test_summary_format` -- verify text matches "[used N tool(s): Name Mx, ...]"
2. `test_single_tool_singular` -- "[used 1 tool: Bash 1x]"
3. `test_multiple_tools_plural` -- "[used 3 tools: Bash 2x, Read 1x]"

### Integration test class: TestRenderTurnToStripsToolSummary
Test cases:
1. `test_summary_in_strips` -- calls `render_turn_to_strips()` with ToolUseBlocks, tools=False, verifies summary text in strip output

Console setup for integration test:
```python
from rich.console import Console
console = Console(width=80, force_terminal=True)
```

Extract text from strips:
```python
text = "".join(seg.text for strip in strips for seg in strip._segments)
assert "used 3 tools" in text
```

### Existing tests to verify
- `TestRenderBlocksToolSummary.test_tool_uses_collapsed_to_summary` (line 237): may need index adjustment if render_blocks output changes. Currently checks `result[1][0] == 1` (index of first ToolUseBlock). This should still hold.
- `TestRenderBlocksToolSummary.test_single_tool_use_summary` (line 273): checks `"1 tool" in result[0][1].plain`. Still correct.
- All tests in `TestRenderToolUseWithDetail` and `TestRenderToolResultSummary`: these test `_render_tool_use` and `_render_tool_result` directly, no changes needed.

### Run verification
```bash
uv run pytest tests/test_tool_rendering.py -v
uv run pytest
just lint
```
