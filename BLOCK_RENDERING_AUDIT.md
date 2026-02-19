# Block Rendering Audit — VisState Behavior per Block Type

## How the Dispatch Works

```
_build_renderer_registry():
  1. For EVERY block type in BLOCK_RENDERERS, assign its renderer to ALL 4 visible states
  2. Then overlay BLOCK_STATE_RENDERERS entries to override specific states
```

This means: **any block type WITHOUT a BLOCK_STATE_RENDERERS entry uses the SAME renderer for all 4 visible states**.

Additionally, `TRUNCATION_LIMITS` post-processes output:
- `(True, False, False)` → 4 lines (summary collapsed)
- `(True, False, True)` → None/unlimited (summary expanded)
- `(True, True, False)` → 4 lines (full collapsed)
- `(True, True, True)` → None/unlimited (full expanded)

**KEY INSIGHT**: Summary collapsed and Full collapsed have IDENTICAL 4-line limits. Summary expanded and Full expanded have IDENTICAL unlimited limits. So the ONLY way to differentiate summary from full is via the RENDERER — but most blocks don't have state-specific renderers.

---

## Legend

- **SC** = Summary Collapsed `VisState(True, False, False)`
- **SE** = Summary Expanded `VisState(True, False, True)`
- **FC** = Full Collapsed `VisState(True, True, False)`
- **FE** = Full Expanded `VisState(True, True, True)`
- **trunc(4)** = generic truncation to 4 lines + collapse indicator
- **SAME** = identical to another state = **BUG**

---

## Block-by-Block Analysis

### 1. SeparatorBlock
**Category**: `METADATA`
**BLOCK_RENDERERS**: `_render_separator` (horizontal line)
**BLOCK_STATE_RENDERERS**: *none*

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC | `_render_separator` | trunc(4) | Horizontal line (1 line, no truncation applies) |
| SE | `_render_separator` | unlimited | Horizontal line |
| FC | `_render_separator` | trunc(4) | Horizontal line |
| FE | `_render_separator` | unlimited | Horizontal line |

**Verdict**: All 4 states identical. **Not a bug** — separator is always 1 line, truncation is irrelevant.

---

### 2. HeaderBlock
**Category**: `METADATA`
**BLOCK_RENDERERS**: `_render_header` (label + timestamp, 1 line)
**BLOCK_STATE_RENDERERS**: *none*

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC | `_render_header` | trunc(4) | "REQUEST (timestamp)" or "RESPONSE (timestamp)" |
| SE | `_render_header` | unlimited | identical |
| FC | `_render_header` | trunc(4) | identical |
| FE | `_render_header` | unlimited | identical |

**Verdict**: All 4 states identical. **Acceptable** — header is always 1 line.

---

### 3. HttpHeadersBlock
**Category**: `METADATA`
**BLOCK_RENDERERS**: `_render_http_headers` (label + all headers, multi-line)
**BLOCK_STATE_RENDERERS**:
- `(True, False, False)` → `_render_http_headers_summary` (one-liner: "HTTP 200 (5 headers) content-type: ...")

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC | `_render_http_headers_summary` | trunc(4) | **One-liner summary** |
| SE | `_render_http_headers` | unlimited | **FULL headers list** |
| FC | `_render_http_headers` | trunc(4) | Full headers truncated to 4 lines |
| FE | `_render_http_headers` | unlimited | Full headers list |

**Verdict**: SC is differentiated. **SE = FE** (BUG). SE should show something between summary and full — currently shows full content unlimited.

---

### 4. MetadataBlock
**Category**: `METADATA`
**BLOCK_RENDERERS**: `_render_metadata` (model/max_tokens/stream/tools/user, 1-2 lines)
**BLOCK_STATE_RENDERERS**: *none*

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC | `_render_metadata` | trunc(4) | model + params (usually fits in 1-2 lines) |
| SE | `_render_metadata` | unlimited | identical |
| FC | `_render_metadata` | trunc(4) | identical |
| FE | `_render_metadata` | unlimited | identical |

**Verdict**: All 4 states identical. **Marginal** — content is short enough that truncation doesn't bite. But there's no summary alternative.

---

### 5. NewSessionBlock
**Category**: `METADATA`
**BLOCK_RENDERERS**: `_render_new_session` (3-line banner with session ID)
**BLOCK_STATE_RENDERERS**: *none*

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC | `_render_new_session` | trunc(4) | 3-line session banner (fits) |
| SE | `_render_new_session` | unlimited | identical |
| FC | `_render_new_session` | trunc(4) | identical |
| FE | `_render_new_session` | unlimited | identical |

**Verdict**: All 4 states identical. **Acceptable** — always 3 lines.

---

### 6. TurnBudgetBlock
**Category**: `METADATA`
**BLOCK_RENDERERS**: `_render_turn_budget` (multi-line context/cache breakdown)
**BLOCK_STATE_RENDERERS**:
- `(True, False, False)` → `_render_turn_budget_oneliner` ("Context: 45k tokens")
- `(True, False, True)` → `_render_turn_budget_oneliner` (same one-liner)

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC | `_render_turn_budget_oneliner` | trunc(4) | **One-liner: "Context: 45k tokens"** |
| SE | `_render_turn_budget_oneliner` | unlimited | **One-liner: "Context: 45k tokens"** |
| FC | `_render_turn_budget` | trunc(4) | Full budget truncated to 4 lines |
| FE | `_render_turn_budget` | unlimited | **Full budget with cache breakdown** |

**Verdict**: SC=SE differentiated from FC/FE. **SC=SE is intentional** (both use oneliner). FC vs FE differentiated by truncation. **WORKING CORRECTLY**.

---

### 7. SystemLabelBlock
**Category**: `SYSTEM`
**BLOCK_RENDERERS**: `_render_system_label` ("SYSTEM:", 1 line)
**BLOCK_STATE_RENDERERS**: *none*

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC-FE | All identical | - | "SYSTEM:" label |

**Verdict**: All identical. **Acceptable** — 1 line.

---

### 8. TrackedContentBlock
**Category**: `SYSTEM`
**BLOCK_RENDERERS**: `_render_tracked_content_full` (full markdown content, no tags/diffs)
**BLOCK_STATE_RENDERERS**:
- `(True, False, False)` → `_render_tracked_content_title` (tag + status + line count)
- `(True, False, True)` → `_render_tracked_content_summary` (tag + diff-aware: new=md, ref=unchanged, changed=diff)

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC | `_render_tracked_content_title` | trunc(4) | **Title only: "[tag_id] CHANGED (40→42 lines)"** |
| SE | `_render_tracked_content_summary` | unlimited | **Tag-colored summary with diffs** |
| FC | `_render_tracked_content_full` | trunc(4) | Full markdown, truncated to 4 lines |
| FE | `_render_tracked_content_full` | unlimited | **Full markdown content** |

**Verdict**: **WORKING CORRECTLY** — all 4 states are visually distinct.

---

### 9. RoleBlock
**Category**: `None` (context-dependent, uses `block.category`)
**BLOCK_RENDERERS**: `_render_role` ("USER" / "ASSISTANT" + timestamp, 1 line)
**BLOCK_STATE_RENDERERS**: *none*

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC-FE | All identical | - | Role label + timestamp |

**Verdict**: All identical. **Acceptable** — 1 line.

---

### 10. TextContentBlock ← MAJOR ISSUE
**Category**: `None` (context-dependent: USER, ASSISTANT, or SYSTEM)
**BLOCK_RENDERERS**: `_render_text_content` (full markdown or indented text)
**BLOCK_STATE_RENDERERS**: *none*

**Note**: If `block.content_regions` is populated, takes the **region rendering path** instead of using RENDERERS. But the region path also renders full content — it just adds per-region collapse/expand for XML blocks.

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC | `_render_text_content` | trunc(4) | Full markdown, truncated to 4 lines |
| SE | `_render_text_content` | unlimited | **Full markdown, unlimited** |
| FC | `_render_text_content` | trunc(4) | Full markdown, truncated to 4 lines |
| FE | `_render_text_content` | unlimited | **Full markdown, unlimited** |

**Verdict**: **SC = FC** (same renderer + same truncation). **SE = FE** (same renderer + same truncation). **BUG** — no differentiation between summary and full for the most important content block.

---

### 11. ToolDefinitionsBlock
**Category**: `TOOLS`
**BLOCK_RENDERERS**: `_render_tool_defs_summary_collapsed`
**BLOCK_STATE_RENDERERS**:
- `(True, False, False)` → `_render_tool_defs_summary_collapsed` ("42 tools / 15k tokens")
- `(True, False, True)` → `_render_tool_defs_summary_expanded` (two-column name + token list)
- `(True, True, False)` → `_render_tool_defs_full_collapsed` ("Tools: Bash, Read, Write...")
- `(True, True, True)` → *not in BLOCK_STATE_RENDERERS* → falls through to region rendering via `_render_tool_def_region_parts`

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC | `_render_tool_defs_summary_collapsed` | trunc(4) | **"42 tools / 15k tokens"** |
| SE | `_render_tool_defs_summary_expanded` | unlimited | **Two-column name/token list** |
| FC | `_render_tool_defs_full_collapsed` | trunc(4) | **"Tools: Bash, Read, Write..."** |
| FE | region rendering | unlimited | **Per-tool expand/collapse with descriptions** |

**Verdict**: **WORKING CORRECTLY** — all 4 states are visually distinct.

---

### 12. ToolUseBlock
**Category**: `TOOLS`
**BLOCK_RENDERERS**: `_render_tool_use_full` (tool-specific: Bash shows `$ command`, Edit shows old/new counts, others fall back to oneliner)
**BLOCK_STATE_RENDERERS**:
- `(True, True, False)` → `_render_tool_use_oneliner` ("[Use: Bash] path (5 lines)")
- `(True, True, True)` → `_render_tool_use_full_with_desc` (full + description line)

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC | `_render_tool_use_full` | trunc(4) | Full rendering (Bash: header+command), truncated to 4 lines |
| SE | `_render_tool_use_full` | unlimited | **Full rendering, unlimited** |
| FC | `_render_tool_use_oneliner` | trunc(4) | **"[Use: Bash] (5 lines)" one-liner** |
| FE | `_render_tool_use_full_with_desc` | unlimited | **Full + description** |

**Verdict**: FC and FE are differentiated. **SC and SE use the FULL renderer** (BUG). SC gets truncated to 4 but uses full renderer instead of a summary renderer. **SE = full content unlimited = same as FE** (BUG).

---

### 13. ToolResultBlock
**Category**: `TOOLS`
**BLOCK_RENDERERS**: `_render_tool_result_full` (header + content: Read gets syntax highlighting, Write/Edit get checkmark, others get dim content)
**BLOCK_STATE_RENDERERS**:
- `(True, True, False)` → `_render_tool_result_summary` (header only, no content)

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC | `_render_tool_result_full` | trunc(4) | Full result truncated to 4 lines |
| SE | `_render_tool_result_full` | unlimited | **Full result, unlimited** |
| FC | `_render_tool_result_summary` | trunc(4) | **Header only: "[Result: Bash] (12 lines)"** |
| FE | `_render_tool_result_full` | unlimited | **Full result with content** |

**Verdict**: FC is differentiated from FE. **SC uses full renderer** (BUG — should use summary or header-only). **SE = FE** (BUG).

---

### 14. ToolUseSummaryBlock
**Category**: `TOOLS`
**BLOCK_RENDERERS**: `_render_tool_use_summary` ("[used 5 tools: Bash 3x, Read 2x]")
**BLOCK_STATE_RENDERERS**: *none*

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC-FE | All identical | - | Summary line |

**Verdict**: All identical. **Acceptable** — this is already a summary block (used when tools are hidden).

---

### 15. ImageBlock
**Category**: `None` (context-dependent)
**BLOCK_RENDERERS**: `_render_image` ("[image: image/png]", 1 line)
**BLOCK_STATE_RENDERERS**: *none*

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC-FE | All identical | - | "[image: image/png]" |

**Verdict**: All identical. **Acceptable** — 1 line.

---

### 16. UnknownTypeBlock
**Category**: `None` (always visible)
**BLOCK_RENDERERS**: `_render_unknown_type` ("[type_name]", 1 line)
**BLOCK_STATE_RENDERERS**: *none*

**Verdict**: Always 1 line. Acceptable.

---

### 17. StreamInfoBlock
**Category**: `METADATA`
**BLOCK_RENDERERS**: `_render_stream_info` ("model: claude-...", 1 line)
**BLOCK_STATE_RENDERERS**: *none*

**Verdict**: Always 1 line. Acceptable.

---

### 18. StreamToolUseBlock
**Category**: `TOOLS`
**BLOCK_RENDERERS**: `_render_stream_tool_use` ("[tool_use] name", 1 line)
**BLOCK_STATE_RENDERERS**: *none*

**Verdict**: Always 1 line. Acceptable.

---

### 19. TextDeltaBlock
**Category**: `None` (context-dependent, streaming)
**BLOCK_RENDERERS**: `_render_text_delta` (markdown or plain text)
**BLOCK_STATE_RENDERERS**: *none*

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC-FE | All identical | - | Same markdown content |

**Verdict**: **BUG** during streaming, but streaming blocks skip truncation anyway (`is_streaming=True`). Low priority.

---

### 20. StopReasonBlock
**Category**: `METADATA`
**BLOCK_RENDERERS**: `_render_stop_reason` ("stop: end_turn", 1 line)
**BLOCK_STATE_RENDERERS**: *none*

**Verdict**: Always 1 line. Acceptable.

---

### 21. ErrorBlock
**Category**: `None` (always visible)
**BLOCK_RENDERERS**: `_render_error`
**BLOCK_STATE_RENDERERS**: *none*

**Verdict**: Always visible, always 1-2 lines. Acceptable.

---

### 22. ProxyErrorBlock
**Category**: `None` (always visible)

**Verdict**: Same as ErrorBlock. Acceptable.

---

### 23. NewlineBlock
**Category**: `None` (always visible)

**Verdict**: Empty line. Acceptable.

---

### 24. ThinkingBlock
**Category**: `THINKING`
**BLOCK_RENDERERS**: `_render_thinking` ("[thinking] full content, dim italic")
**BLOCK_STATE_RENDERERS**:
- `(True, False, False)` → `_render_thinking_summary` ("[thinking] (42 lines)")
- `(True, False, True)` → `_render_thinking_summary` (same)

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC | `_render_thinking_summary` | trunc(4) | **"[thinking] (42 lines)"** |
| SE | `_render_thinking_summary` | unlimited | **"[thinking] (42 lines)"** |
| FC | `_render_thinking` | trunc(4) | Full thinking truncated to 4 lines |
| FE | `_render_thinking` | unlimited | **Full thinking content** |

**Verdict**: **WORKING CORRECTLY** — SC/SE clearly different from FC/FE.

---

### 25. ConfigContentBlock
**Category**: `None` (inherits from parent, typically USER)
**BLOCK_RENDERERS**: `_render_config_content` ("[config: source] full content")
**BLOCK_STATE_RENDERERS**:
- `(True, False, False)` → `_render_config_content_summary` ("[config: source] (N lines)")
- `(True, False, True)` → `_render_config_content_summary` (same)

| State | Renderer | Truncation | Result |
|-------|----------|-----------|--------|
| SC | `_render_config_content_summary` | trunc(4) | **"[config: CLAUDE.md] (42 lines)"** |
| SE | `_render_config_content_summary` | unlimited | **"[config: CLAUDE.md] (42 lines)"** |
| FC | `_render_config_content` | trunc(4) | Full content truncated to 4 lines |
| FE | `_render_config_content` | unlimited | **Full content** |

**Verdict**: **WORKING CORRECTLY** — SC/SE clearly different from FC/FE.

---

### 26. HookOutputBlock
**Category**: `None` (inherits from parent)
**BLOCK_RENDERERS**: `_render_hook_output` ("[hook: name] full content")
**BLOCK_STATE_RENDERERS**:
- `(True, False, False)` → `_render_hook_output_summary` ("[hook: name] (N lines)")
- `(True, False, True)` → `_render_hook_output_summary` (same)

**Verdict**: **WORKING CORRECTLY** — same pattern as ConfigContentBlock.

---

### 27. MessageBlock
**Category**: `None` (context-dependent)
**BLOCK_RENDERERS**: `_render_message_block` ("USER [0] timestamp", 1 line)
**BLOCK_STATE_RENDERERS**: *none*

**Verdict**: Always 1 line. Acceptable.

---

### 28. MetadataSection
**Category**: `METADATA`
**BLOCK_RENDERERS**: `_render_metadata_section` ("METADATA", 1 line)
**BLOCK_STATE_RENDERERS**: *none*

**Verdict**: Always 1 line. Acceptable.

---

### 29. SystemSection
**Category**: `SYSTEM`
**BLOCK_RENDERERS**: `_render_system_section` ("SYSTEM", 1 line)
**BLOCK_STATE_RENDERERS**: *none*

**Verdict**: Always 1 line. Acceptable.

---

### 30. ToolDefsSection
**Category**: `TOOLS`
**BLOCK_RENDERERS**: `_render_tool_defs_section` ("42 tools / 15k tokens", 1 line)
**BLOCK_STATE_RENDERERS**: *none*

**Verdict**: Always 1 line. Acceptable.

---

### 31. ToolDefBlock
**Category**: `TOOLS`
**BLOCK_RENDERERS**: `_render_tool_def` ("ToolName (500 tokens)", 1 line)
**BLOCK_STATE_RENDERERS**: *none*

**Verdict**: Always 1 line. Acceptable.

---

### 32. SkillDefChild / AgentDefChild
**Category**: `TOOLS`
**BLOCK_RENDERERS**: `_render_skill_def_child` / `_render_agent_def_child` (name + description preview, 1 line)
**BLOCK_STATE_RENDERERS**: *none*

**Verdict**: Always 1 line. Acceptable.

---

### 33. ResponseMetadataSection
**Category**: `METADATA`

**Verdict**: Always 1 line. Acceptable.

---

### 34. ResponseMessageBlock
**Category**: `None` (context-dependent)

**Verdict**: Always 1 line. Acceptable.

---

## Summary: Blocks with BROKEN Differentiation

These blocks render **identically** at SUMMARY and FULL levels, which is the P0 bug:

| Block Type | Category | Problem |
|-----------|----------|---------|
| **TextContentBlock** | USER/ASSISTANT/SYSTEM | **SC=FC** (same renderer + same 4-line truncation). **SE=FE** (same renderer, unlimited). This is the most visible content in the app. |
| **ToolUseBlock** | TOOLS | **SC uses full renderer** (should use oneliner). SE=FE (both show full content unlimited). State overrides exist but only for `full=True`. |
| **ToolResultBlock** | TOOLS | **SC uses full renderer** (should use summary/header-only). SE=FE. State overrides exist but only for `full=True, collapsed`. |
| **HttpHeadersBlock** | METADATA | SE=FE (summary expanded shows full headers). SC is correct. |

## Summary: Blocks that WORK Correctly

| Block Type | Why it works |
|-----------|-------------|
| **TrackedContentBlock** | Has 3 distinct renderers: title, summary, full |
| **ToolDefinitionsBlock** | Has 4 distinct renderers for all 4 states |
| **TurnBudgetBlock** | Oneliner for summary, full budget for full |
| **ThinkingBlock** | Summary shows line count, full shows content |
| **ConfigContentBlock** | Summary shows line count, full shows content |
| **HookOutputBlock** | Summary shows line count, full shows content |

## Summary: Blocks where Identical Rendering is ACCEPTABLE

All single-line blocks: SeparatorBlock, HeaderBlock, RoleBlock, SystemLabelBlock, MetadataBlock, NewSessionBlock, ImageBlock, UnknownTypeBlock, StreamInfoBlock, StreamToolUseBlock, StopReasonBlock, ErrorBlock, ProxyErrorBlock, NewlineBlock, ToolUseSummaryBlock, MessageBlock, MetadataSection, SystemSection, ToolDefsSection, ToolDefBlock, SkillDefChild, AgentDefChild, ResponseMetadataSection, ResponseMessageBlock.

## Root Cause

`_build_renderer_registry()` populates ALL 4 visible states with the same `BLOCK_RENDERERS` function, then `BLOCK_STATE_RENDERERS` overrides specific states. The overrides are incomplete:

1. **ToolUseBlock/ToolResultBlock**: State overrides only exist for `full=True` states. The `full=False` (summary) states fall through to the full renderer.
2. **TextContentBlock**: No state overrides AT ALL. Most important block type has zero summary/full differentiation.
3. **TRUNCATION_LIMITS**: Summary and Full both use 4/unlimited, so truncation alone cannot differentiate them.

## The Fix Needed

For each broken block, we need BLOCK_STATE_RENDERERS entries for the summary states `(True, False, False)` and `(True, False, True)`:

- **TextContentBlock**: Needs a summary renderer (e.g., first N lines with "..." indicator, or a "text (42 lines)" one-liner for collapsed)
- **ToolUseBlock**: Needs `(True, False, False)` → oneliner and `(True, False, True)` → oneliner or oneliner+desc
- **ToolResultBlock**: Needs `(True, False, False)` → header-only and `(True, False, True)` → header-only or header+preview
- **HttpHeadersBlock**: Needs `(True, False, True)` → summary (currently falls through to full)

Additionally, `TRUNCATION_LIMITS` should likely differ between summary and full (e.g., summary collapsed = 2 lines, full collapsed = 6 lines) to provide visual differentiation even for blocks that use the same renderer.
