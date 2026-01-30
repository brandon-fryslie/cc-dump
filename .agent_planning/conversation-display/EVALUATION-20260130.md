# Evaluation: conversation-display Roadmap Items 1, 3, 4, 5, 6, 7
Timestamp: 2026-01-30-100000
Git Commit: 53d0827

## Executive Summary
Overall state: Sprints 1-2 COMPLETE. 6 roadmap items remain unimplemented.

**Completed infrastructure:**
- FormattedBlock IR pipeline (formatting.py -> rendering.py -> widget_factory.py)
- BLOCK_RENDERERS registry and BLOCK_FILTER_KEY optimization map
- ConversationView with Line API, TurnData, render_line, filter toggle re-render
- Follow mode, turn selection, click-to-select, j/k/n/N/g/G navigation
- Scroll anchor preservation across filter changes
- 23 Sprint 1 tests + Sprint 2 tests passing

## Gap Analysis: 6 Remaining Items

### Item 1: Front-ellipsed filenames for Read tool
**Current**: ToolUseBlock stores `name` and `input_size`. The `input` dict (which contains `file_path` for Read) is discarded at formatting.py:361-362.
**Gap**: No `file_path` field on ToolUseBlock. No extraction logic. Renderer shows generic `[tool_use] Read (243 bytes)`.
**Confidence**: HIGH -- clear extraction point, single field addition.

### Item 3: Headers show HTTP headers
**Current**: The "headers" filter controls SeparatorBlock and HeaderBlock (REQUEST/RESPONSE labels). The proxy (proxy.py:50-52, 76-82) has access to HTTP request and response headers but does NOT put them on the event queue. Events are `("request", body)` and `("response_event", event_type, data)` -- body-only, no headers.
**Gap**: HTTP headers are not captured in the event pipeline. proxy.py would need to emit headers alongside request/response data. A new block type (e.g. HttpHeadersBlock) would be needed. The entire data flow from proxy -> event queue -> formatting -> rendering needs a new path.
**Confidence**: MEDIUM -- requires proxy layer changes and new event structure.

### Item 4: Tool use/response color correlation
**Current**: ToolUseBlock has `msg_color_idx` (assigned per message position, formatting.py:339,363). ToolResultBlock has `msg_color_idx` (same). No `tool_use_id` stored in either block. Color is per-message, not per-tool-correlation.
**Gap**: Neither ToolUseBlock nor ToolResultBlock stores `tool_use_id`. The correlation exists in analysis.py `correlate_tools()` but uses raw API messages, not the IR. To color-correlate in the rendering layer, both blocks need `tool_use_id` and a color assignment mechanism that maps tool_use_id -> consistent color index.
**Confidence**: MEDIUM -- structural IR change with downstream effects on rendering and re-render optimization.

### Item 5: Show skill name for Skill tool
**Current**: ToolUseBlock stores `name="Skill"` and `input_size`. The `input` dict (which contains `skill` field) is discarded.
**Gap**: Same pattern as Item 1. Need to extract `skill` field during formatting and store/render it.
**Confidence**: HIGH -- identical pattern to Item 1.

### Item 6: Bash command preview
**Current**: ToolUseBlock stores `name="Bash"` and `input_size`. The `input` dict (which contains `command` field) is discarded.
**Gap**: Same pattern as Items 1 and 5. Extract `command` field, truncate to preview length.
**Confidence**: HIGH -- identical pattern to Items 1 and 5.

### Item 7: Meaningful collapsed tool result summaries
**Current**: ToolResultBlock has `size`, `is_error`, `msg_color_idx`. No `tool_name` field. When tools filter is off, these blocks are completely hidden.
**Gap**: ToolResultBlock needs the tool name to show summaries. This requires either (a) storing tool_name during formatting by looking up the tool_use_id in the same message context, or (b) a post-processing pass. Also need a "summary" rendering mode (shown even when tools filter is off).
**Confidence**: MEDIUM -- touches filter semantics (summary visible when filter off) and requires tool name lookup.

## Sprint Grouping

### Sprint 3: Tool Display Enrichment (Items 1, 5, 6)
**Confidence**: HIGH
**Rationale**: All three follow identical pattern: add optional `detail` field to ToolUseBlock, extract tool-specific data during formatting, render in the existing renderer. No structural changes to IR hierarchy or filter system.

### Sprint 4: Tool Correlation and Summaries (Items 4, 7)
**Confidence**: MEDIUM
**Rationale**: Item 4 (correlation colors) and Item 7 (result summaries) both require adding `tool_use_id` and/or `tool_name` to the IR. Item 7 specifically needs tool_name on ToolResultBlock, which naturally pairs with Item 4's need for tool_use_id. Grouping them avoids touching the IR twice.

### Sprint 5: HTTP Headers Display (Item 3)
**Confidence**: MEDIUM
**Rationale**: Stands alone because it requires changes outside the formatting/rendering pipeline (proxy.py event emission). Different risk profile from the other items.

## Dependency Graph

```
Sprint 3 (tool-display-enrich) -- no dependencies, ready to implement
    |
    v
Sprint 4 (tool-correlation-summaries) -- benefits from Sprint 3 patterns but not blocked
    |
Sprint 5 (http-headers) -- independent, no dependencies
```

## Risk Assessment

1. **Item 7 filter semantics**: Showing summaries when tools filter is off creates a new visibility mode. Currently BLOCK_FILTER_KEY maps ToolResultBlock -> "tools". If summaries should show when filter is off, the filter logic needs a conditional path, or a new block type.

2. **Item 4 color assignment**: Tool correlation colors must not conflict with MSG_COLORS cycling. Need a separate color pool or use MSG_COLORS with tool_use_id-based indexing.

3. **Item 3 proxy changes**: Modifying the event queue format risks breaking the TUI event handler contract. Needs careful backward compatibility.
