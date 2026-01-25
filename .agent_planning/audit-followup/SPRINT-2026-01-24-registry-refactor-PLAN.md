# Sprint: registry-refactor - Refactor render_block to Registry Pattern
Generated: 2026-01-24
Confidence: HIGH: 2, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Replace the 38-way if/elif dispatch in render_block() with a registry pattern, reducing complexity and enabling easy addition of new block types.

## Scope
**Deliverables:**
- Block type registry mapping FormattedBlock subclasses to render functions
- Individual render functions for each block type
- Simplified render_block() that dispatches via registry lookup

## Work Items

### P0: Create block renderer registry
**Confidence: HIGH**

**Current State:**
```python
def render_block(block: FormattedBlock, filters: dict) -> Text | None:
    if isinstance(block, SeparatorBlock):
        # 5 lines of rendering logic
    if isinstance(block, HeaderBlock):
        # 10 lines of rendering logic
    # ... 36 more if blocks
```
Total: 137 lines, cyclomatic complexity 38

**Target State:**
```python
# Registry mapping block type to renderer function
BLOCK_RENDERERS: dict[type[FormattedBlock], Callable] = {
    SeparatorBlock: _render_separator,
    HeaderBlock: _render_header,
    # ... all block types
}

def render_block(block: FormattedBlock, filters: dict) -> Text | None:
    renderer = BLOCK_RENDERERS.get(type(block))
    if renderer is None:
        return None
    return renderer(block, filters)
```

**Acceptance Criteria:**
- [ ] Registry dict maps all 19 block types to render functions
- [ ] Each render function has signature `(block, filters) -> Text | None`
- [ ] render_block() is <10 lines
- [ ] All existing tests pass (hot-reload tests still work)
- [ ] Adding new block type requires only: 1) define block class, 2) add registry entry

**Technical Notes:**
- Extract each if-block into a named function: `_render_separator()`, `_render_header()`, etc.
- Registry lives at module level for hot-reload compatibility
- Type hints: `dict[type[FormattedBlock], Callable[[FormattedBlock, dict], Text | None]]`

### P1: Add unit tests for refactored renderers
**Confidence: HIGH**

**Acceptance Criteria:**
- [ ] Test each renderer function independently
- [ ] Test registry lookup for known and unknown block types
- [ ] Test filter behavior (headers, tools, system, expand, metadata)
- [ ] Test that render_block returns None for filtered-out blocks

**Technical Notes:**
- Create `tests/test_rendering.py`
- Use fixtures for filter combinations
- Test both "returns Text" and "returns None" cases

## Dependencies
- Sprint 1 (unit-tests) should complete first for safety net

## Risks
- **Breaking hot-reload**: Registry is module-level, will be reloaded correctly
- **Missing block type**: Add fallback for unknown types → return None with warning

## Block Types to Register (19 total)

| Block Type | Filter Key | Render Function |
|------------|------------|-----------------|
| SeparatorBlock | headers | _render_separator |
| HeaderBlock | headers | _render_header |
| MetadataBlock | metadata | _render_metadata |
| SystemLabelBlock | system | _render_system_label |
| TrackedContentBlock | system/expand | _render_tracked_content |
| DiffBlock | expand | _render_diff |
| RoleBlock | (always) | _render_role |
| TextContentBlock | (always) | _render_text_content |
| ToolUseBlock | tools | _render_tool_use |
| ToolResultBlock | tools | _render_tool_result |
| ImageBlock | (always) | _render_image |
| UnknownTypeBlock | (always) | _render_unknown_type |
| StreamInfoBlock | metadata | _render_stream_info |
| StreamToolUseBlock | tools | _render_stream_tool_use |
| TextDeltaBlock | (always) | _render_text_delta |
| StopReasonBlock | metadata | _render_stop_reason |
| ErrorBlock | (always) | _render_error |
| ProxyErrorBlock | (always) | _render_proxy_error |
| LogBlock | (always) | _render_log |
| NewlineBlock | (always) | _render_newline |
| TurnBudgetBlock | expand | _render_turn_budget |

## Success Metrics
- render_block() complexity: 38 → 1
- Line count reduction: 137 → ~20 (main function) + 19×~10 (renderers) = ~210 total (but simpler)
- Each renderer is independently testable
- Adding new block type is trivial
