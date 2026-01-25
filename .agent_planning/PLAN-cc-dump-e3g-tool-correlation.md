# Implementation Plan: Tool Use and Tool Response Color Correlation (cc-dump-e3g)

## Objective
Enable visual correlation between `tool_use` and `tool_response` blocks via consistent color coding, making it easier to trace tool invocations through the conversation history.

## Current State Analysis

### Architecture Summary
- **Tool blocks**: `ToolUseBlock` and `ToolResultBlock` (in `formatting.py`)
- **Color system**: `MSG_COLORS` palette (6 colors, line 38 in `rendering.py`)
- **Current correlation**: Both blocks receive `msg_color_idx` (message-level color assignment)
- **Tool ID tracking**: Exists separately in `ToolInvocation` dataclass but not propagated to rendering

### Key Insight
The current implementation **already visually correlates** tool_use with tool_result through message index (`msg_color_idx`). Both blocks in the same message share the same color from `MSG_COLORS`.

**Problem**: This is implicit and only works when tool_use and tool_result are in the same message. The correlation is not explicit or tool-specific.

## Options for Enhancement

### Option A: Tool-Specific Color Correlation (RECOMMENDED)
**Approach**: Assign colors based on tool *name* rather than message index
- **Pro**: Same tool always gets the same color across the entire conversation
- **Pro**: Easier to visually track a specific tool's invocations
- **Pro**: Tool use and result pair guaranteed to match even in different messages
- **Con**: Limited to 6 unique tools at a time before color reuse
- **Implementation effort**: Medium (requires passing tool_id through to renderer)

### Option B: Unique Tool Invocation Correlation
**Approach**: Use `tool_use_id` to create dynamic color mapping
- **Pro**: Each tool invocation pair is uniquely identifiable
- **Pro**: Scales to unlimited tool invocations
- **Con**: Higher visual complexity; harder to follow patterns
- **Implementation effort**: High (requires rendering-layer changes)

### Option C: Enhanced Visual Markers
**Approach**: Keep message-level colors but add additional markers (borders, brackets, line numbers)
- **Pro**: Minimal implementation effort
- **Pro**: Maintains current color scheme
- **Con**: Less elegant than color-based correlation
- **Implementation effort**: Low

## Recommended Implementation Path

### Phase 1: Propagate Tool IDs to Rendering Layer
**Files to modify**:
1. `src/cc_dump/formatting.py`
   - Add `tool_id` field to `ToolUseBlock` and `ToolResultBlock`
   - Capture from `correlate_tools()` result when creating blocks

2. `src/cc_dump/tui/rendering.py`
   - Update `_render_tool_use()` and `_render_tool_result()` to accept tool_id
   - Create a tool name → color mapping function
   - Use tool name (lowercase, hashed) to select stable color from `MSG_COLORS`

3. `src/cc_dump/tui/widget_factory.py`
   - Pass tool_id through to renderer

### Phase 2: Implement Tool-Name Color Mapping
**In `rendering.py`**:
```python
def _get_tool_color(tool_name: str) -> str:
    """Stable color assignment based on tool name."""
    tool_idx = hash(tool_name) % len(MSG_COLORS)
    return MSG_COLORS[tool_idx]
```

Update rendering functions:
```python
def _render_tool_use(block: ToolUseBlock, filters: dict) -> Text | None:
    if not filters.get("tools", False):
        return None
    color = _get_tool_color(block.tool_id)  # Change this line
    t = Text("  ")
    t.append("[tool_use]", style="bold {}".format(color))
    t.append(" {} ({} bytes)".format(block.name, block.input_size))
    return t
```

### Phase 3: Update Block IR Creation
**In `formatting.py`**:
- Modify `format_request()` and `format_response_event()` to include tool ID
- Ensure `tool_id` is consistent with `ToolInvocation.tool_use_id`

### Phase 4: Testing and Validation
**Test scenarios**:
1. Single tool invocation: use and result same color
2. Multiple invocations of same tool: all use same color
3. Multiple tools: each gets distinct color
4. Tool color consistency: reload/filter doesn't change colors
5. Hot-reload: color palette changes take effect immediately

## Acceptance Criteria

- [ ] Tool use and tool response blocks in same message visually linked by color
- [ ] Tool use and tool response blocks of same tool (even different messages) share color
- [ ] Color assignment is deterministic (same tool always same color across session)
- [ ] Existing filter behavior unchanged (tools can still be hidden)
- [ ] Hot-reload preserves color mapping across reloads
- [ ] No performance regression in rendering

## Risk Assessment

- **Low risk**: Changes are localized to `formatting.py` and `rendering.py`
- **No breaking changes**: Only adding fields and updating color logic
- **Backwards compatible**: Message index color fallback can be retained as backup

## File Dependencies

```
formatting.py → ToolUseBlock/ToolResultBlock (add tool_id)
              ↓
event_handlers.py → format_request/format_response (pass tool_id)
              ↓
rendering.py → _render_tool_use/_render_tool_result (use tool_id for color)
              ↓
widget_factory.py → ConversationView (displays colored blocks)
```

## Estimated Complexity: Medium
- Requires understanding of current tool correlation pipeline
- Multiple files involved but changes are straightforward
- Primary complexity: ensuring tool_id flows through entire pipeline
