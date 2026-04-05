# Rendering Specification

**Status:** draft
**Scope:** Block rendering pipeline — dispatch model, per-block visual output at each visibility state, truncation limits, gutter indicators, region rendering.

## Why This Exists

Claude Code sends and receives complex API messages containing system prompts, tool definitions, user messages, assistant responses, tool calls, token usage, and metadata. A single turn can contain thousands of lines of content across dozens of block types. Users need progressive disclosure: a glanceable summary by default that expands to full detail on demand. The rendering system converts structured IR (FormattedBlock tree) into pre-rendered terminal strips with category-colored gutters, expandable regions, and truncation indicators.

---

## Visibility Model

Every block is rendered at a specific `VisState(visible, full, expanded)` — three orthogonal boolean axes yielding 8 combinations. Four of those combinations are hidden (`visible=False`), leaving four visible states:

| Shorthand | visible | full | expanded | Meaning |
|-----------|---------|------|----------|---------|
| SC | True | False | False | Summary Collapsed — most compact visible form |
| SE | True | False | True | Summary Expanded — bounded preview |
| FC | True | True | False | Full Collapsed — content with truncation |
| FE | True | True | True | Full Expanded — complete content, no limits |

**Visibility resolution priority** (enforced in `_resolve_visibility`):
1. Programmatic `vis_override` from ViewOverrides (e.g., search reveal)
2. User per-block `expanded` toggle from ViewOverrides
3. Category filter state (keyboard-cycled)

Blocks with no category (errors, newlines, unknown types) always render at `ALWAYS_VISIBLE` (FE).

Source: `_resolve_visibility()` at line 514 in `rendering_impl.py`.

---

## Category Resolution

Each block's category determines which filter controls its visibility. Resolution order:

1. `block.category` field (set by formatting pipeline for context-dependent blocks)
2. `BLOCK_CATEGORY` static mapping (line 443 in `rendering_impl.py`)

The static mapping assigns categories as follows:

| Block Type | Category |
|-----------|----------|
| SeparatorBlock, HeaderBlock, HttpHeadersBlock, MetadataBlock, NewSessionBlock, TurnBudgetBlock, StreamInfoBlock, StopReasonBlock, ResponseUsageBlock, MetadataSection, ResponseMetadataSection | METADATA |
| ToolUseBlock, ToolResultBlock, ToolUseSummaryBlock, StreamToolUseBlock, ToolDefsSection, ToolDefBlock, SkillDefChild, AgentDefChild | TOOLS |
| ThinkingBlock | THINKING |
| SystemSection | SYSTEM |
| MessageBlock, TextContentBlock, TextDeltaBlock, ImageBlock | None (context-dependent — uses `block.category` field) |
| ConfigContentBlock, HookOutputBlock | None (inherits from parent container) |
| ErrorBlock, ProxyErrorBlock, NewlineBlock, UnknownTypeBlock | None (always visible, no category filter) |

Source: `BLOCK_CATEGORY` dict and `get_category()` in `rendering_impl.py`.

---

## Truncation Limits

Generic truncation is applied post-render when a block uses the default render path (no state-specific renderer). Limits are line counts applied to the rendered strip output.

| VisState | Max Lines | Behavior |
|----------|-----------|----------|
| Hidden (any) | 0 | Block produces no output |
| SC (visible, !full, !expanded) | 3 | Truncate to 3 lines + collapse indicator |
| SE (visible, !full, expanded) | 8 | Truncate to 8 lines + collapse indicator |
| FC (visible, full, !expanded) | 5 | Truncate to 5 lines + collapse indicator |
| FE (visible, full, expanded) | None (unlimited) | All content shown |

When truncation is active, the collapse indicator `    ··· N more lines` is appended as a dim strip. The gutter arrow is forced to the collapsed form for truncated blocks (the `(full, False)` key is used for the arrow lookup instead of `(full, expanded)`).

Source: `TRUNCATION_LIMITS` dict at line 420 in `rendering_impl.py`.

---

## Two-Tier Dispatch Model

Rendering uses a unified registry (`RENDERERS`) built from two source tables:

### Tier 1: Full-Content Renderers (`BLOCK_RENDERERS`)

Keyed by block type name (e.g., `"HeaderBlock"`). These produce the complete renderable for a block — used as the default for all four visible VisStates. When no state-specific override exists, the full renderer runs and generic truncation (per `TRUNCATION_LIMITS`) limits the output.

31 block types are registered in `BLOCK_RENDERERS` (line 3309), including `ResponseMetadataSection`, `SkillDefChild`, and `AgentDefChild` as separate entries even though some share renderers (e.g., `SkillDefChild` and `AgentDefChild` share `_render_named_def_child_full`).

### Tier 2: State-Specific Renderers (`BLOCK_STATE_RENDERERS`)

Keyed by `(type_name, visible, full, expanded)`. These override the full renderer for specific states, producing custom output that already respects the desired compactness. When a state-specific renderer is registered, generic truncation is bypassed because the renderer itself controls output size.

### Registry Build

```
for each type_name in BLOCK_RENDERERS:
    populate all 4 visible states with the full renderer
overlay BLOCK_STATE_RENDERERS on top
```

Result: `RENDERERS[(type_name, visible, full, expanded)]` gives exactly one renderer per block type per visible state. Lookup is O(1).

### Region Rendering

Blocks with `content_regions` (populated by text segmentation) bypass the standard dispatch when no state-specific renderer is registered for the current VisState. Instead, `_render_region_block_strips` renders each region part independently, with per-region expand/collapse state. The decision is made by: `use_region_rendering = has_regions and not state_override`.

This means region rendering only applies when a block both has regions AND the current VisState is not covered by a `BLOCK_STATE_RENDERERS` entry. Whether region rendering activates depends on the block type — it activates for any state that lacks a state-specific renderer. In practice, TextContentBlock has state-specific renderers for SC, SE, and FC, so region rendering only activates at FE for that type, but other block types with regions may activate it at different states depending on their renderer registrations.

Collapsible region kinds (defined by `COLLAPSIBLE_REGION_KINDS`):
- `xml_block`: XML tags with expandable inner content
- `code_fence`: Fenced code blocks with syntax highlighting
- `md_fence`: Markdown fences
- `tool_def`: Tool definition blocks

Non-collapsible:
- `md`: Plain markdown segments — rendered as Markdown inline, always shown

Region expand/collapse state is read from `ViewOverrides._regions` keyed by `(block_id, region_index)`.

Source: `_render_block_tree()` at line 3972, `COLLAPSIBLE_REGION_KINDS` at line 73 in `rendering_impl.py`.

---

## Gutter System

Every rendered block is wrapped in a left gutter + optional right gutter that provides category identification and expand/collapse affordance.

### Layout

```
[▌][arrow + "  "] content... [▐]
[▌]["   "]        content... [▐]
[▌]["   "]        content... [▐]
```

- Left gutter: `GUTTER_WIDTH = 4` cells total (`▌` + arrow/space + 2 spaces)
- Right gutter: `RIGHT_GUTTER_WIDTH = 1` cell (`▐`), hidden below `MIN_WIDTH_FOR_RIGHT_GUTTER = 40`
- Content width: `max(1, terminal_width - GUTTER_WIDTH - RIGHT_GUTTER_WIDTH)`

### Gutter Modes

Three rendering modes exist within `_add_gutter_to_strips`:

1. **Category mode** (`indicator_name` is set): Colored `▌`/`▐` bars using filter indicator colors. Arrow shown when expandable.
2. **Neutral mode** (`neutral=True`): Dim `▌`/`▐` bars with no arrow. Used for NewlineBlock and other uncategorized blocks.
3. **No gutter** (else path): Strips returned unchanged. Used when `indicator_name` is None and `neutral` is False.

### Gutter Colors

Filter indicator colors are built by `_build_filter_indicators()` from `ThemeColors.filter_colors`. Each category gets a `(gutter_fg, chip_bg, chip_fg)` triple; the gutter uses `chip_bg` as its `▌` foreground color (with bold style). The same color is used for the arrow character.

Filter colors are generated by `palette.generate_filter_colors()` which places hues in gaps between theme semantic colors (primary, secondary, accent, etc.) for maximum visual distinction.

### Arrow Indicators

Arrows appear on the first strip of expandable blocks. The arrow character encodes the current VisState via `GUTTER_ARROWS`:

| Key (full, expanded) | Arrow | Meaning |
|----------------------|-------|---------|
| (False, False) | `▷` (U+25B7) | Summary collapsed — hollow right (hollow = summary/partial data, right = collapsed/more to reveal) |
| (False, True) | `▽` (U+25BD) | Summary expanded — hollow down (hollow = summary/partial data, down = expanded/contents shown) |
| (True, False) | `▶` (U+25B6) | Full collapsed — solid right (solid = full/complete data, right = collapsed/more to reveal) |
| (True, True) | `▼` (U+25BC) | Full expanded — solid down (solid = full/complete data, down = expanded/contents shown) |

Arrows are suppressed (empty string) for:
- Non-expandable blocks (`is_expandable=False`)
- Continuation blocks within the same category (coalesced — arrow forced to `""`)
- Neutral-mode blocks (gutter uses three spaces instead of arrow)

### Expandability

A block is expandable (`_compute_expandable`) when any of:
1. It has children (hierarchical container)
2. The collapsed and expanded renderers for its current level are different functions (identity comparison: `RENDERERS.get(collapsed_key) is not RENDERERS.get(expanded_key)`)
3. The rendered output exceeds the collapsed truncation limit for its level

When a block is determined non-expandable, any stale expansion override in ViewOverrides is cleared (`block_vs.expanded = None`).

Source: `_compute_expandable()` at line 3871, `_update_block_expandability_state()` at line 3956 in `rendering_impl.py`.

---

## Block Rendering by Type

### HeaderBlock (Category: METADATA)

| State | Output |
|-------|--------|
| SC | ` REQUEST ` (or ` RESPONSE `) — bold, role-colored label only |
| SE | ` REQUEST  (2026-03-28 14:30:05)` — label + dim timestamp (delegates to `_render_header`) |
| FC | Falls through to generic `_render_header` (label + timestamp) + truncation |
| FE | Label + timestamp line, then `    type: request | request: 3` on a second line |

Label coloring: `REQUEST` uses `tc.info` (primary), `RESPONSE` uses `tc.success`.

### SeparatorBlock (Category: METADATA)

Uses `─` (U+2500, heavy) or `┄` (U+2504, light) characters depending on `block.style`.

| State | Output |
|-------|--------|
| SC | 18-char line |
| SE | 36-char line |
| FC | 54-char line |
| FE | 70-char line (default renderer) |

All rendered in dim style.

### HttpHeadersBlock (Category: METADATA)

| State | Output |
|-------|--------|
| SC | `  HTTP 200  (N headers)  content-type: ...` — one-line status + header count + inline content-type |
| SE | Status line + up to 6 sorted headers as `key: value` pairs + `··· N more headers` remainder |
| FC | Status line + up to 3 unsorted headers + `··· N more headers [snippet]` remainder |
| FE | Full sorted header listing with all key-value pairs |

Request headers use `"Request Headers"` label styled with `tc.info`. Response headers use `"HTTP {status_code}"` styled with `tc.success`.

### MetadataBlock (Category: METADATA)

| State | Output |
|-------|--------|
| SC | `  model: claude-sonnet... | tools: 5 | stream: true` — bold model name + key request identity fields |
| SE | SC content + `max_tokens` field + optional second line with truncated identity fields (user/account/session) |
| FC | Default renderer (all fields including max_tokens, stream, tool_count, identity hashes) + truncation |
| FE | Default renderer content + `    identity: user_hash=... | account_id=... | session_id=...` with full (untruncated) identity values |

### ResponseUsageBlock (Category: METADATA)

| State | Output |
|-------|--------|
| SC | `  Usage: 128K in (92% cached) → 2.1K out` — compact one-liner |
| SE | Same one-liner (bold token counts) + `    cache: 118K read | 3K created | 7K fresh` on second line |
| FC | `  usage: 128K in → 2.1K out (92% cached)` — dim compact form (lowercase "usage", all dim styling) |
| FE | Full breakdown: usage line + `    cache read: ... | created: ... | fresh: ...` + optional `    cost: $0.0042` line |

Token counts are formatted via `fmt_tokens()` (e.g., `128K`, `2.1K`). Cache percentages use `_pct()`. Colors: input tokens in `tc.info` (primary), output tokens in `tc.warning`, cache hit percentage in `tc.success`. Cost estimate computed via `compute_session_cost()` when model is known.

### TurnBudgetBlock (Category: METADATA)

| State | Output |
|-------|--------|
| SC | `  Context: 128K tokens` — one-line total |
| SE | `  Context: 128K tokens` + second line: `    sys: 45K (35%) | tools: 32K (25%) | conv: 51K (40%)` |
| FC | `  Context: 128K tokens | sys: 45K (35%) | tools: 32K (25%) | conv: 51K (40%)` — same stats on one line |
| FE | FC content + optional `    tool_use: ... | tool_results: ... (Bash: 12K, Read: 8K, ...)` breakdown line showing per-tool-name token distribution (top 5 tools) |

Colors: system tokens in `tc.info`, tool tokens in `tc.warning`, conversation tokens in `tc.success`.

### TextContentBlock (Category: context-dependent — USER, ASSISTANT, or SYSTEM)

| State | Output |
|-------|--------|
| SC | `  First line preview text...  (47 lines)` — one-line with line count |
| SE | Summary line + up to 6 dim preview lines + `··· N more lines` if needed (max 8 total) |
| FC | Bounded plain-text snippet (max 4 rendered lines via `_render_full_collapsed_snippet`) |
| FE | Full content rendered as Markdown (for USER/ASSISTANT/SYSTEM categories) or plain indented text. Uses segmented region rendering with independently expandable XML blocks, code fences, and markdown fences. |

Preview lines are generated by `_preview_line()` which normalizes whitespace (collapses runs to single space) and truncates at 100-120 characters with `…` suffix. SC uses `max_chars=110`, SE uses `max_chars=120` for inner preview lines.

### ToolUseBlock (Category: TOOLS)

| State | Output |
|-------|--------|
| SC | `  [Use: Bash]` — bold colored tool name + optional special-marker badges |
| SE | `  [Use: Bash] detail (N lines)` one-liner + dim italic description first line (max 120 chars) |
| FC | One-liner header + tool-specific input preview on second line |
| FE | Tool-specific full rendering + description line if available (via `_render_tool_use_full_with_desc`) |

SE uses the oneliner format which includes `block.detail` and `block.input_size` as `(N lines)`.

**Tool-specific input previews at FC** (via `_TOOL_USE_COLLAPSED_PREVIEWS`):

| Tool | Preview Format |
|------|---------------|
| Bash | `$ first-line-of-command` |
| Edit | `replace 5 -> 3 lines` |
| Read | `path/to/file.py (offset=0 limit=all)` |
| Write | `path/to/file.py + first 80 chars of content...` |
| Grep | `/pattern/ in path` |
| Glob | `**/*.py @ src/` |
| (other) | `block.detail` or empty |

**Tool-specific full renderers at FE** dispatch via `_TOOL_USE_FULL_RENDERERS` table. The table has entries for: Bash, Edit, Read, Write, Grep, and Glob. Each gets a dedicated renderer (e.g., Bash gets syntax-highlighted command rendering). Tools not in the table fall back to the generic one-liner via `_render_tool_use_oneliner`.

### ToolResultBlock (Category: TOOLS)

| State | Output |
|-------|--------|
| SC | `  [Result]  (47 lines)` or `  [Result ERROR]  (47 lines)` — colored, with line count |
| SE | Header + one-line bounded content preview (120 chars max via `_preview_line`) |
| FC | Header only (same as `_render_tool_result_summary` — no content) |
| FE | Tool-specific full rendering via `_TOOL_RESULT_CONTENT_RENDERERS` dispatch |

**Tool-specific full renderers at FE** (via `_TOOL_RESULT_CONTENT_RENDERERS`):

| Tool | Rendering |
|------|-----------|
| Read | Header + `Syntax()` with language inferred from file extension (`_EXT_TO_LANG` table) |
| Write, Edit | Header + `✓` (bold green) for success, or error content in `tc.error` style |
| Bash | Header + content in `tc.error` (error) or `tc.foreground` (success) |
| Grep | Header + content with pattern matches highlighted in `bold tc.accent` |
| Glob | Header + file paths in `tc.secondary` |
| (other) | Header + dim content |

### ToolUseSummaryBlock (Category: TOOLS)

Created by `_collapse_children()` when tools category is not at FULL level — consecutive ToolUse/ToolResult pairs are collapsed into a single summary. Blocks with `vis_override` in ViewOverrides are exempt from collapsing (e.g., search reveal forces them visible).

| State | Output |
|-------|--------|
| SC | `  [used 5 tools] top: Bash 3x` |
| SE | `  [used 5 tools: Bash 3x, Read 1x, Edit 1x] (+2 more)` — top 3 tools shown |
| FC | Multi-line: header + up to 3 tools with `- name: Nx` + `··· N more tools` |
| FE | Full sorted breakdown with all tools, counts, and percentages (e.g., `- Bash: 3x (60%)`) |

Tool entries are sorted by descending count, then case-insensitive name, then case-sensitive name.

### ThinkingBlock (Category: THINKING)

| State | Output |
|-------|--------|
| SC | `[thinking] (47 lines)` |
| SE | Header + up to 6 dim italic preview lines (120 chars each) + `··· N more lines` |
| FC | Header (line count) + bounded snippet (max 3 lines via `_render_full_collapsed_snippet`) |
| FE | `[thinking] ` (bold dim) + full content in dim italic |

### ToolDefBlock (Category: TOOLS)

| State | Output |
|-------|--------|
| SC | `  Bash               1.2K tokens` — left-aligned name (18 chars wide) + token count |
| SE | Header + first line of description (max 80 chars, truncated with `...`, dim italic) |
| FC | Header + `params: 5 (3 required)` schema footprint (derived from `input_schema.properties`) |
| FE | Full tool definition content (default renderer) |

### SkillDefChild / AgentDefChild (Category: TOOLS)

Named definition children within ToolDefsSection. Both share the same renderers.

| State | Output |
|-------|--------|
| SC | Bold name only |
| SE | Name + one-line description preview (90 chars max) |
| FC | SE content + first detail line (dim italic) |
| FE | Name + full description + all metadata detail lines |

### ToolDefsSection (Category: TOOLS, container)

| State | Output |
|-------|--------|
| SC | `5 tools` + special-marker badges (no token count) |
| SE | Falls through to default renderer: `5 tools` + badges + `/ 12K tokens` (full count) |
| FC | Header (with tokens) + `    avg: 2.4K tokens/tool` detail line |
| FE | Header (with tokens) + up to 6 child tool names + `(+N more)` + metadata line. Children rendered recursively. |

Note: SC has a dedicated state-specific renderer that omits the token count for compactness. SE has no state-specific renderer, so it uses the default `_render_tool_defs_section` (which includes token count) with truncation.

### SystemSection (Category: SYSTEM, container)

| State | Output |
|-------|--------|
| SC | `SYSTEM` — bold dim label (default renderer, no SC-specific override) |
| SE | `SYSTEM` + child type counts (via `_render_section_with_counts`) |
| FC | `SYSTEM` + compact child count (via `_render_section_compact_count`) |
| FE | `SYSTEM` + all child types + metadata line. Children rendered recursively. |

### MetadataSection (Category: METADATA, container)

| State | Output |
|-------|--------|
| SC | `METADATA` — bold dim label (default renderer) |
| SE | `METADATA` + child type counts |
| FC | `METADATA` + compact child count |
| FE | `METADATA` + all child type composition |

### ResponseMetadataSection (Category: METADATA, container)

| State | Output |
|-------|--------|
| SC | `RESPONSE METADATA` — bold dim label (default renderer) |
| SE | `RESPONSE METADATA` + child type counts |
| FC | `RESPONSE METADATA` + compact child count |
| FE | `RESPONSE METADATA` + all child type composition |

### MessageBlock (Category: context-dependent — USER or ASSISTANT, container)

| State | Output |
|-------|--------|
| SC | `USER [0]` or `ASSISTANT [1]` — role label with message index, no timestamp |
| SE | Role label with timestamp + `  | summary blocks: N content:M tools:K thinking:J` composition stats |
| FC | Role label with timestamp + `  | blocks: N content:M tools:K thinking:J other:L` composition stats |
| FE | Role label with timestamp + metadata detail line. Children rendered recursively. |

### ErrorBlock (Category: None — always visible)

| State | Output |
|-------|--------|
| SC | `  [HTTP 500]` — bold error-colored status code |
| SE | `  [HTTP 500 Internal Server Error]` + `    request failed` (dim italic second line) |
| FC | `  [HTTP 500 Internal Server Error] [failed]` — status + dim failure marker |
| FE | `  [HTTP 500 Internal Server Error]` — full default renderer (bold error-colored) |

### ProxyErrorBlock (Category: None — always visible)

| State | Output |
|-------|--------|
| SC | `  [PROXY ERROR]` — bold error-colored |
| SE | `  [PROXY ERROR: connection refused]` + `    upstream transport failed` (dim italic) |
| FC | `  [PROXY ERROR: connection refused] [failed]` — error text + dim failure marker |
| FE | `  [PROXY ERROR: connection refused]` — full default renderer |

### NewSessionBlock (Category: METADATA)

| State | Output |
|-------|--------|
| SC | `  NEW SESSION` — bold info-colored one-liner |
| SE | `  NEW SESSION: a1b2c3d4e5f6g7h8` — marker + truncated session ID (16 chars) |
| FC | `═` (24-char frame) + ` NEW SESSION ` + truncated session ID + `═` frame |
| FE | `═` (40-char frame) + ` NEW SESSION: ` + full session ID + `═` frame |

### UnknownTypeBlock (Category: None — always visible)

| State | Output |
|-------|--------|
| SC | `  [unknown: block_type]` — dim one-liner |
| SE | `  [unknown: block_type]` + `    unrecognized block type` (dim italic) |
| FC | Falls through to default renderer + truncation |
| FE | `  [unknown: block_type]` + metadata detail line (type details) |

### ConfigContentBlock (Category: None — inherits from parent)

Configuration content within system messages (e.g., CLAUDE.md files).

| State | Output |
|-------|--------|
| SC | `[config: source]` (bold dim) + special-marker badges + `(N lines)` |
| SE | Header + up to 6 preview lines (dim, 120 chars max each) + `··· N more lines` |
| FC | Header + bounded snippet (max 3 lines via `_render_full_collapsed_snippet`) |
| FE | `[config: source]` header + badges + full content rendered as Markdown |

### HookOutputBlock (Category: None — inherits from parent)

Hook output content within user messages.

| State | Output |
|-------|--------|
| SC | `[hook: hook_name]` (bold dim) + `(N lines)` |
| SE | Header + up to 4 preview lines (dim, 120 chars max each) + `··· N more lines` |
| FC | Header + bounded snippet (max 3 lines via `_render_full_collapsed_snippet`) |
| FE | `[hook: hook_name]` header + full content rendered as Markdown |

### TextDeltaBlock (Category: context-dependent — ASSISTANT during streaming)

Streaming text delta accumulated during SSE processing.

| State | Output |
|-------|--------|
| SC | `  [delta] 1,234 chars / 47 lines` — compact char/line count signal |
| SE | SC header + up to 2 dim preview lines (120 chars each) + `··· N more lines` |
| FC | `  [delta]` header + bounded snippet (max 3 lines) |
| FE | Full content rendered as Markdown (for ASSISTANT category) or plain text |

### StreamInfoBlock (Category: METADATA)

| State | Output |
|-------|--------|
| SC | `  model: claude-sonnet...` — truncated to 24 chars with `…` |
| SE | `  model: claude-sonnet-4-20250514` (full) + `    stream metadata` (dim italic) |
| FC | Same as SC (delegates to `_render_stream_info_summary_collapsed`) |
| FE | `  model: claude-sonnet-4-20250514` — full model name, dim styling |

### StreamToolUseBlock (Category: TOOLS)

| State | Output |
|-------|--------|
| SC | `  [tool_use] Bash` — bold info-colored label + name |
| SE | SC content + `    pending tool_result` (dim italic) |
| FC | `  [tool_use]` — label only (no tool name) |
| FE | `  [tool_use] Bash` — full default renderer (with leading newline) |

### StopReasonBlock (Category: METADATA)

| State | Output |
|-------|--------|
| SC | `  stop: end_turn` — compact reason |
| SE | SC content + `    assistant completed turn` (dim italic hint from `_STOP_REASON_HINTS`) |
| FC | `  stop` — dim label only (no reason value, more compact than SC) |
| FE | `  stop: end_turn` — full default renderer (with leading newline) |

Stop reason hints: `end_turn` = "assistant completed turn", `max_tokens` = "generation hit token limit", `stop_sequence` = "matched configured stop sequence", `tool_use` = "assistant requested tool execution", `""` (empty) = "stream still in progress or reason unavailable".

### NewlineBlock (Category: None — always visible)

Structural whitespace. Rendered with neutral (dim) gutters, no category color.

| State | Output |
|-------|--------|
| SC | Suppressed — returns `None` (no output produced) |
| SE | `Text("")` — explicit empty renderable, produces a blank spacer line |
| FC | `Text("")` — falls through to default `_render_newline`, produces a blank spacer line |
| FE | `Text("")` — explicit empty renderable, produces a blank spacer line |

The distinction matters: SC returns `None` which suppresses the block entirely (zero lines), while SE/FC/FE return `Text("")` which produces one empty line for visual spacing.

### ImageBlock (Category: context-dependent)

| State | Output |
|-------|--------|
| SC | Compact image signal |
| SE | Image metadata |
| FC | Image metadata (bounded) |
| FE | `  [image: image/png]` — dim one-liner (default renderer) |

---

## Content Region Rendering

TextContentBlock and other text-bearing blocks with `content_regions` use sub-block segmentation for independently expandable regions within a single block. Region rendering is activated only at FE (since SC, SE, FC all have state-specific renderers that bypass regions).

### Region Kinds and Defaults

| Kind | Expanded Threshold (lines) | Collapsed Preview |
|------|---------------------------|-------------------|
| `xml_block` | 10 | `▷ <tag>preview text...<tag>` (max 60 chars) |
| `code_fence` | 12 | `▷ ` `` ```lang``` `` ` (N lines) preview...` (max 60 chars) |
| `md_fence` | 14 | `▷ ` `` ```md``` `` ` (N lines) preview...` (max 60 chars) |
| `tool_def` | (same mechanism) | Collapsed tool definition preview |
| `md` | N/A | Rendered as Markdown inline (not collapsible) |

The "Expanded Threshold" column is a threshold for whether a region **starts expanded**, not a maximum when expanded. A region with fewer lines than the threshold starts expanded; a region with more starts collapsed. Once a user expands a region, all content is shown regardless of this threshold.

These defaults are overridable via environment variables:
- `CC_DUMP_XML_BLOCK_DEFAULT_EXPANDED_MAX_LINES` (default: 10)
- `CC_DUMP_CODE_FENCE_DEFAULT_EXPANDED_MAX_LINES` (default: 12)
- `CC_DUMP_MD_FENCE_DEFAULT_EXPANDED_MAX_LINES` (default: 14)

Region expansion state resolution: ViewOverrides override (from `overrides._regions[(block_id, region_index)]`) takes priority. If no override exists, the default policy function determines initial state.

### Expanded XML Rendering

```
▽ <system-reminder>         ← arrow + styled open tag
  [markdown content]        ← inner content rendered as Markdown
</system-reminder>          ← styled close tag
```

XML tag styling: `<` `/` `>` in dim foreground, tag name in `tc.secondary`, arrow in dim secondary.

### Collapsed XML Rendering

```
▷ <system-reminder>Preview of inner text content...<system-reminder>
```

Inner text preview: whitespace-normalized, max 60 characters, truncated with `…`.

### Region Caching

Region-rendered blocks are cached with a composite key: `(block_id, render_width, vis_state, region_cache_state)` where `region_cache_state` is a tuple of `(region_index, expanded_override)` for each region. This means a change to any region's expanded state invalidates the cache for the entire block.

---

## Coalescing

Consecutive blocks of the same category suppress the arrow on continuation blocks. This creates a visual grouping effect — the colored gutter runs continuously, but only the first block in a run shows an arrow.

Implemented via `_coalesce_consecutive_same_category` in `_BLOCK_TRANSFORMS`. The tracking uses `ctx.last_rendered_indicator` which is updated after each block is emitted.

---

## Child Recursion

Container blocks (those with `children`) render their children recursively, but only when the container is at FE state (`visible=True, full=True, expanded=True`). This is enforced by `_recurse_visible_children()`.

Before recursing, tool collapsing is applied: when the `tools` category filter is not at FULL level, `_collapse_children()` merges consecutive ToolUse/ToolResult pairs into ToolUseSummaryBlock instances. Blocks with `vis_override` in ViewOverrides are exempt from collapsing.

---

## Streaming

During streaming (`is_streaming=True`):
- Truncation is disabled (all content shown regardless of limits)
- A dedicated lightweight path `render_streaming_preview()` bypasses the full dispatch pipeline
- Streaming preview renders accumulated text as Markdown with assistant-category gutter
- No visibility resolution, expandability, block caching, region handling, or search highlighting

Source: `render_streaming_preview_with_runtime()` at line 4046 in `rendering_impl.py`.

---

## Search Highlighting

Search highlighting is NOT part of the rendering pipeline. It is a post-render strip overlay applied at `render_line()` time in `ConversationView` (in `widget_factory.py`).

The overlay works by:
1. Extracting plain text from the strip's segments
2. Running the search pattern's regex against the plain text
3. Using `Segment.divide()` to split segments at match boundaries
4. Applying highlight styles to matched segments in reverse order (to maintain stable offsets)

Search match styles:
- All matches in non-current block: `Style(bgcolor=tc.search_all_bg)` — surface-colored background
- All matches in current-match block: `Style.parse(tc.search_current_style)` — bold, accent-based inverted style

Current-match detection uses block identity comparison (`current.block is block`) rather than index comparison, which handles the flat-vs-hierarchical index mismatch introduced by container blocks.

Source: Search overlay logic at line 1057 in `widget_factory.py`.

---

## Empty Block Suppression

Leaf blocks (no children) that produce no visible text in their rendered strips are suppressed by `_hide_empty_leaf_blocks`. Structural empty blocks (`NewlineBlock`) are exempt from this check. Blocks with children are always passed through. This is the sole block-emission transform in `_BLOCK_EMIT_TRANSFORMS`.

Source: `_BLOCK_EMIT_TRANSFORMS` at line 3684 in `rendering_impl.py`.

---

## Theme Integration

All colors are derived from the active Textual theme via `build_theme_colors()`. The rendering pipeline never hardcodes colors — it reads from `ThemeColors` which provides semantic aliases:

- Role colors: `user` (primary), `assistant` (secondary), `system` (accent)
- Functional: `info` (primary), `warning`, `error`, `success`
- Code: `code_theme` switches between `"github-dark"` and `"friendly"` based on dark mode
- Markdown: Full Rich markdown theme dict derived from theme colors
- Search: `search_all_bg` (surface), `search_current_style` (accent-based)
- Footer: `follow_active_style`, `follow_engaged_style`
- Search bar: `search_prompt_style`, `search_active_style`, `search_error_style`, `search_keys_style`

Theme changes flow through `set_theme()` which rebuilds all derived state in `RenderRuntime`, including `role_styles`, `tag_styles`, `msg_colors`, and `filter_indicators`.

ANSI color normalization: Theme colors are normalized to `#RRGGBB` hex via `_normalize_color()`. The special value `"ansi_default"` (meaning terminal's unknowable default) is treated as None and uses a fallback. When all of bg/fg/surface are unknowable, dark mode is assumed since TUI users overwhelmingly use dark backgrounds.
