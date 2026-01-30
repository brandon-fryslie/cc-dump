# Sprint: tool-correlation-summaries - Tool Correlation Colors and Result Summaries
Generated: 2026-01-30-110000
Confidence: HIGH: 1, MEDIUM: 3, LOW: 0
Status: PARTIALLY READY
Source: EVALUATION-20260130.md

## Sprint Goal
Visually link tool_use and tool_result blocks via correlated colors, and show meaningful summaries for tool results (including when collapsed).

## Scope
**Deliverables:**
- ToolUseBlock and ToolResultBlock store `tool_use_id` for correlation
- ToolResultBlock stores `tool_name` for summary display
- Color assignment based on tool_use_id correlation instead of message position
- Collapsed/filtered tool result summaries showing tool name + size

## Work Items

### P0 [MEDIUM] Add `tool_use_id` and `tool_name` to IR blocks

**Dependencies**: None (but Sprint 3 should be done first to avoid merge conflicts on ToolUseBlock)
**Spec Reference**: Roadmap Item 4, 7 | **Status Reference**: EVALUATION-20260130.md "Item 4/7"

#### Description
Extend ToolUseBlock with `tool_use_id: str = ""` and ToolResultBlock with `tool_use_id: str = ""` and `tool_name: str = ""`.

During formatting (formatting.py:359-373), extract `tool_use_id` from the raw API blocks:
- `tool_use` blocks have `cblock.get("id", "")` which is the tool_use_id
- `tool_result` blocks have `cblock.get("tool_use_id", "")` which references the matching tool_use

For `tool_name` on ToolResultBlock: build a lookup dict `{tool_use_id: name}` while iterating message content blocks. When processing a `tool_result`, look up the name from the corresponding `tool_use`.

#### Acceptance Criteria
- [ ] ToolUseBlock has `tool_use_id: str = ""` field
- [ ] ToolResultBlock has `tool_use_id: str = ""` and `tool_name: str = ""` fields
- [ ] `format_request()` populates `tool_use_id` on ToolUseBlock from `cblock["id"]`
- [ ] `format_request()` populates `tool_use_id` and `tool_name` on ToolResultBlock
- [ ] Unit test: format a request with tool_use and tool_result, verify IDs and names are set

#### Technical Notes
- The tool_use_id is always present in API messages (it is required by the Anthropic API)
- The lookup dict must be built across ALL messages in the request (tool_use in assistant messages, tool_result in user messages), so it needs to be built in a first pass or accumulated during the existing message loop
- Current message loop at formatting.py:336-378 iterates messages sequentially. A tool_use in message[i] may have its tool_result in message[i+1]. The simplest approach: do a pre-pass to build `{tool_use_id: name}` before the main loop, or build it incrementally (tool_use always comes before tool_result in message order).

#### Unknowns to Resolve
1. **Pre-pass vs incremental**: Should we scan all messages for tool_use IDs before the main formatting loop, or build the lookup incrementally? Incremental is simpler if tool_use always precedes tool_result (which it does in the Anthropic API).
   Research: Verify by examining sample API message sequences.

#### Exit Criteria (to reach HIGH)
- [ ] Confirmed that tool_use always precedes tool_result in message order
- [ ] Implementation approach chosen (incremental recommended)

---

### P1 [MEDIUM] Color correlation by tool_use_id

**Dependencies**: "Add tool_use_id and tool_name to IR blocks"
**Spec Reference**: Roadmap Item 4 | **Status Reference**: EVALUATION-20260130.md "Item 4"

#### Description
Replace per-message `msg_color_idx` with per-tool-correlation color indexing. Both the ToolUseBlock and its matching ToolResultBlock should share the same color.

Current behavior: `msg_color_idx = i % MSG_COLOR_CYCLE` where `i` is the message index. This means a tool_use in message 3 (assistant) gets color 3, but its tool_result in message 4 (user) gets color 4.

New behavior: Assign a `tool_color_idx` based on the tool_use_id. Maintain a dict `{tool_use_id: color_idx}` during formatting. When creating a ToolUseBlock, assign the next color and record it. When creating a ToolResultBlock, look up the color from the tool_use_id.

#### Acceptance Criteria
- [ ] ToolUseBlock and matching ToolResultBlock have the same color index
- [ ] Different tool_use_id pairs have different (cycling) colors
- [ ] Color assignment is deterministic (same messages produce same colors)
- [ ] Existing rendering code works without changes (it reads `msg_color_idx`)
- [ ] Unit test: format request with 2 tool_use/tool_result pairs, verify matching colors

#### Technical Notes
- Reuse the `msg_color_idx` field name to avoid changing rendering.py. Just assign it differently.
- The color state dict `{tool_use_id: int}` should be local to `format_request()`, not part of the persistent `state` dict, because tool correlation is per-request, not cross-request.
- Alternative: rename field to `color_idx` on both blocks. But renaming requires touching rendering.py too. Keeping `msg_color_idx` is simpler.

#### Unknowns to Resolve
1. **Color pool**: Should tool correlation colors use the same MSG_COLORS pool (6 colors) or a different palette? Using the same pool keeps visual consistency but means 7+ concurrent tools will repeat colors.
   Research: Count typical concurrent tool_use blocks in a single request.

#### Exit Criteria (to reach HIGH)
- [ ] Color pool decision made
- [ ] Rendering verified to not need changes (just reads msg_color_idx)

---

### P1 [MEDIUM] Tool result summary rendering

**Dependencies**: "Add tool_use_id and tool_name to IR blocks"
**Spec Reference**: Roadmap Item 7 | **Status Reference**: EVALUATION-20260130.md "Item 7"

#### Description
When tools filter is ON, show tool name in the tool_result line:
- Current: `  [tool_result] (1523 bytes)`
- New: `  [tool_result] Read ...path/file.ts (1523 bytes)`

When tools filter is OFF, show a compact summary line instead of hiding completely:
- Summary: `  [Read] ...path/file.ts (1523 bytes)` (dimmed, no filter indicator)

This requires a change to the filter visibility logic for ToolResultBlock.

#### Acceptance Criteria
- [ ] Tool result with tools filter ON shows tool name after [tool_result] label
- [ ] Tool result with tools filter OFF shows compact summary line
- [ ] Summary line is styled dim to not compete with main content
- [ ] Error tool results show `[tool_result:error]` label in both modes
- [ ] Unit test: render ToolResultBlock with tool_name, verify name appears in output
- [ ] Unit test: render ToolResultBlock with tools filter OFF, verify summary appears

#### Technical Notes
- Current `_render_tool_result` returns `None` when filter is off (rendering.py:168-169). Change to return a summary Text when filter is off.
- BLOCK_FILTER_KEY currently maps `ToolResultBlock: "tools"`. If we want summaries visible when filter is off, we need to either:
  (a) Change BLOCK_FILTER_KEY to `None` and handle visibility inside the renderer (renderer returns full or summary based on filter), or
  (b) Return the summary from the renderer even when filter is "off" (but the current pattern is renderer returns None for filtered blocks)
- Option (a) is cleaner: make ToolResultBlock always visible (BLOCK_FILTER_KEY -> None), and the renderer decides what to show based on filter state.
- This changes TurnData.re_render optimization: turns with only ToolResultBlock will now always re-render. Acceptable since the summary is cheap.

#### Unknowns to Resolve
1. **Filter key change**: Changing BLOCK_FILTER_KEY for ToolResultBlock from "tools" to None means the re-render optimization won't skip ToolResultBlock turns when tools filter toggles. Is this acceptable?
   Research: Measure re-render cost for a typical conversation (likely negligible).
2. **Detail in summary**: Should the summary include the Sprint 3 `detail` field from the corresponding ToolUseBlock? If so, ToolResultBlock also needs a `detail` field, or the detail must be embedded in the tool_name.
   Research: Decide during implementation -- can always add detail to ToolResultBlock later.

#### Exit Criteria (to reach HIGH)
- [ ] Filter key approach decided (recommend option a: BLOCK_FILTER_KEY -> None)
- [ ] Summary format finalized

---

### P2 [HIGH] Update ToolUseBlock rendering with tool_name on tool_result

**Dependencies**: "Add tool_use_id and tool_name to IR blocks"
**Spec Reference**: Roadmap Item 7 | **Status Reference**: EVALUATION-20260130.md "Item 7"

#### Description
Update `_render_tool_result()` to include the tool name in the output when available.

#### Acceptance Criteria
- [ ] When `block.tool_name` is non-empty, it appears in the rendered output
- [ ] When `block.tool_name` is empty, output is identical to current behavior
- [ ] No regression in existing filter behavior

#### Technical Notes
- Simple addition to rendering.py:166-175
- Append tool name after label, before size

## Dependencies
- Sprint 3 (tool-display-enrich) should be done first to avoid merge conflicts on ToolUseBlock dataclass
- Internal: IR changes must precede rendering changes

## Risks
- **Medium**: Changing BLOCK_FILTER_KEY for ToolResultBlock affects re-render optimization. If conversations have many tool results, this could cause unnecessary re-renders. Mitigate by measuring.
- **Medium**: The tool_use_id lookup during formatting requires accumulating state across messages. If a tool_result references a tool_use_id from a previous request (not in the current request body), the lookup will fail. This is acceptable -- the summary will just lack a tool name.
- **Low**: Color cycling with many concurrent tools may produce same-colored pairs. This is cosmetic only.
