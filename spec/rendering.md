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

Blocks with no category (errors, newlines, unknown types) always render at FE.

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

When truncation is active, the collapse indicator `    ··· N more lines` is appended as a dim strip. The gutter arrow is forced to the collapsed form for truncated blocks.

Source: `TRUNCATION_LIMITS` dict in `rendering_impl.py`.

---

## Two-Tier Dispatch Model

Rendering uses a unified registry (`RENDERERS`) built from two source tables:

### Tier 1: Full-Content Renderers (`BLOCK_RENDERERS`)

Keyed by block type name (e.g., `"HeaderBlock"`). These produce the complete renderable for a block — used as the default for all four visible VisStates. When no state-specific override exists, the full renderer runs and generic truncation (per `TRUNCATION_LIMITS`) limits the output.

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

Blocks with `content_regions` (populated by text segmentation) bypass the standard dispatch when no state-specific renderer is registered. Instead, `_render_region_block_strips` renders each region part independently, with per-region expand/collapse state. Region kinds:

- `xml_block`: XML tags with expandable inner content
- `code_fence`: Fenced code blocks with syntax highlighting
- `md_fence`: Markdown fences
- `tool_def`: Tool definition blocks
- `md`: Plain markdown segments (not collapsible — rendered inline)

Collapsed regions show a one-line preview. Expanded regions show full content.

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
- Content width: `terminal_width - GUTTER_WIDTH - RIGHT_GUTTER_WIDTH`

### Gutter Colors

The `▌` bar and `▐` right bar are colored by category. Colors are derived from the active Textual theme via `build_theme_colors()`:

| Category | Color Derivation |
|----------|-----------------|
| user | theme primary |
| assistant | theme secondary |
| tools | palette-generated (gap between theme colors) |
| system | theme accent |
| metadata | palette-generated |
| thinking | palette-generated |
| (no category) | dim neutral style |

Filter indicator colors are built by `palette.generate_filter_colors()` and stored in `ThemeColors.filter_colors`. Each category gets a `(gutter_fg, chip_bg, chip_fg)` triple; the gutter uses `chip_bg` as its foreground color.

### Arrow Indicators

Arrows appear on the first strip line of expandable blocks. The arrow character encodes the current VisState:

| State | Arrow | Meaning |
|-------|-------|---------|
| Summary Collapsed | `▷` (U+25B7) | Hollow right — summary, more available |
| Summary Expanded | `▽` (U+25BD) | Hollow down — summary, expanded |
| Full Collapsed | `▶` (U+25B6) | Solid right — full, more available |
| Full Expanded | `▼` (U+25BC) | Solid down — full, all shown |

Arrows are suppressed for: non-expandable blocks, continuation blocks within the same category (coalesced), and neutral-mode blocks (no category).

### Expandability

A block is expandable when any of:
1. It has children (hierarchical container)
2. The collapsed and expanded renderers for its current level are different functions
3. The rendered output exceeds the collapsed truncation limit for its level

---

## Block Rendering by Type

### HeaderBlock (Category: METADATA)

| State | Output |
|-------|--------|
| SC | ` REQUEST ` (or ` RESPONSE `) — bold, role-colored label only |
| SE | ` REQUEST  (2026-03-28 14:30:05)` — label + dim timestamp |
| FC | Falls through to generic `_render_header` (label + timestamp) + truncation |
| FE | Label + timestamp line, then `    type: request | request: 3` on a second line |

### SeparatorBlock (Category: METADATA)

Uses `─` (heavy) or `┄` (light) characters.

| State | Output |
|-------|--------|
| SC | 18-char line |
| SE | 36-char line |
| FC | 54-char line |
| FE | 70-char line (default renderer) |

### HttpHeadersBlock (Category: METADATA)

| State | Output |
|-------|--------|
| SC | `  HTTP 200  (N headers)` — one-line status summary |
| SE | Status + first few headers as `key: value` pairs |
| FC | Status + sorted header listing (truncated to 5 lines) |
| FE | Full sorted header listing with all key-value pairs |

### MetadataBlock (Category: METADATA)

| State | Output |
|-------|--------|
| SC | One-line with type label and dim key-value pairs |
| SE | Type label + expanded metadata pairs |
| FC | Default renderer + truncation |
| FE | Type label + full metadata + additional detail line |

### ResponseUsageBlock (Category: METADATA)

| State | Output |
|-------|--------|
| SC | `  Usage: 128K in (92% cached) → 2.1K out` — compact one-liner |
| SE | Same one-liner plus `    cache: 118K read | 3K created | 7K fresh` on second line |
| FC | `  usage: 128K in → 2.1K out (92% cached)` — dim compact form |
| FE | Full breakdown with all token fields (default renderer) |

Token counts are formatted via `fmt_tokens()` (e.g., `128K`, `2.1K`). Cache percentages use `_pct()`. Colors: input tokens in `tc.info` (primary), output tokens in `tc.warning`, cache hit percentage in `tc.success`.

### TurnBudgetBlock (Category: METADATA)

| State | Output |
|-------|--------|
| SC | One-line total budget figure |
| SE | Total + breakdown of budget components |
| FC | Compact budget with key stats |
| FE | Full budget details (default renderer) |

### TextContentBlock (Category: context-dependent — USER, ASSISTANT, or SYSTEM)

| State | Output |
|-------|--------|
| SC | `  First line preview text...  (47 lines)` — one-line with line count |
| SE | Summary line + up to 6 dim italic preview lines + `··· N more lines` if needed (max 8 total) |
| FC | Bounded plain-text snippet (max 4 rendered lines via `_render_full_collapsed_snippet`) |
| FE | Full content rendered as Markdown (for USER/ASSISTANT/SYSTEM) or plain indented text. Uses segmented rendering with independently expandable XML blocks, code fences, and markdown fences. |

Preview lines are generated by `_preview_line()` which normalizes whitespace and truncates at 100-120 characters with `…` suffix.

### ToolUseBlock (Category: TOOLS)

| State | Output |
|-------|--------|
| SC | `  [Use: Bash]` — bold colored tool name, optional special-marker badges |
| SE | `  [Use: Bash] $ command...` one-liner + dim italic description first line (max 120 chars) |
| FC | Header one-liner + tool-specific input preview on second line |
| FE | Tool-specific full rendering + description line if available |

**Tool-specific input previews at FC:**

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
| SE | Header + bounded content preview |
| FC | Header only (same as summary renderer) |
| FE | Header + full result content (default renderer) |

### ToolUseSummaryBlock (Category: TOOLS)

Created by `_collapse_children()` when tools are below FULL level — consecutive ToolUse/ToolResult pairs are collapsed into a single summary.

| State | Output |
|-------|--------|
| SC | `  [used 5 tools] top: Bash 3x` |
| SE | `  [used 5 tools: Bash 3x, Read 1x, Edit 1x] (+2 more)` — top 3 tools shown |
| FC | Multi-line breakdown: header + up to 3 tools with `- name: Nx` + `··· N more tools` |
| FE | Full sorted breakdown with all tools and percentages |

### ThinkingBlock (Category: THINKING)

| State | Output |
|-------|--------|
| SC | `[thinking] (47 lines)` |
| SE | Header + up to 6 dim italic preview lines + `··· N more lines` |
| FC | Header + bounded snippet (max 3 lines) |
| FE | `[thinking] ` + full content in dim italic |

### ToolDefBlock (Category: TOOLS)

| State | Output |
|-------|--------|
| SC | `  Bash               1.2K tokens` — aligned name + token count |
| SE | Header + first line of description (max 80 chars, dim italic) |
| FC | Header + `params: 5 (3 required)` schema footprint |
| FE | Full tool definition content (default renderer) |

### ToolDefsSection (Category: TOOLS, container)

| State | Output |
|-------|--------|
| SC | `  5 tools` + special-marker badges + `/ 12K tokens` — compact one-liner |
| SE | Section header + child composition hints (type counts) |
| FC | Compact count |
| FE | Header + full child type composition. Children rendered recursively. |

### SystemSection (Category: SYSTEM, container)

| State | Output |
|-------|--------|
| SC/SE default | `SYSTEM` — bold dim label |
| SE | `SYSTEM` + child type counts |
| FC | `SYSTEM` + compact child count |
| FE | `SYSTEM` + all child types + metadata line. Children rendered recursively. |

### MessageBlock (Category: context-dependent — USER or ASSISTANT, container)

| State | Output |
|-------|--------|
| SC | Compact collapsed — minimal signal |
| SE | Compact expanded — child composition |
| FC | Full collapsed with child counts |
| FE | Default renderer. Children rendered recursively. |

### ErrorBlock / ProxyErrorBlock (Category: None — always visible)

| State | Output |
|-------|--------|
| SC | Compact error signal |
| SE | Error with bounded detail |
| FC | Error with compact context |
| FE | Full error content |

### NewSessionBlock (Category: METADATA)

Session boundary indicator. Has state-specific renderers for SC, SE, and FC.

| State | Output |
|-------|--------|
| SC | Compact session boundary signal |
| SE | Session boundary with expanded detail |
| FC | Compact session boundary |
| FE | Full session boundary (default renderer) |

### MetadataSection (Category: METADATA, container)

Container for metadata blocks within a turn. Has state-specific renderers for SE, FC, and FE.

### ResponseMetadataSection (Category: METADATA, container)

Container for response metadata. Has state-specific renderers for SE, FC, and FE.

### ConfigContentBlock (Category: None — inherits from parent)

Configuration content block. Has state-specific renderers for SC and SE.

### HookOutputBlock (Category: None — inherits from parent)

Hook output content. Has state-specific renderers for SC, SE, and FC.

### TextDeltaBlock (Category: None — ASSISTANT during streaming)

Streaming text delta. Has state-specific renderers for SC, SE, and FC.

| State | Output |
|-------|--------|
| SC | Compact delta signal |
| SE | Bounded delta preview |
| FC | Bounded delta content |
| FE | Full delta content (default renderer) |

### StreamInfoBlock / StreamToolUseBlock / StopReasonBlock (Category: METADATA)

Streaming metadata blocks with progressive detail at each level. All follow the same SC/SE/FC/FE pattern of increasing verbosity.

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
| FE | Full image block (default renderer) |

---

## Content Region Rendering

TextContentBlock and other text-bearing blocks with `content_regions` use sub-block segmentation for independently expandable regions within a single block.

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

---

## Coalescing

Consecutive blocks of the same category suppress the arrow on continuation blocks. This creates a visual grouping effect — the colored gutter runs continuously, but only the first block in a run shows an arrow.

Implemented via `_coalesce_consecutive_same_category` in `_BLOCK_TRANSFORMS`.

---

## Streaming

During streaming (`is_streaming=True`):
- Truncation is disabled (all content shown)
- A dedicated lightweight path `render_streaming_preview()` bypasses the full dispatch pipeline
- Streaming preview renders accumulated text as Markdown with assistant-category gutter
- No visibility resolution, expandability, block caching, or region handling

---

## Search Highlighting

Search highlighting is NOT part of the rendering pipeline. It is a post-render strip overlay applied at `render_line()` time in ConversationView. Search matches use:
- All matches: `tc.search_all_bg` (surface color) background
- Current match: `tc.search_current_style` (bold, accent-based inverted)

---

## Empty Block Suppression

Leaf blocks (no children) that produce no visible text in their rendered strips are suppressed by `_hide_empty_leaf_blocks`. Structural empty blocks (`NewlineBlock`) are exempt from this check. This is the sole block-emission transform in `_BLOCK_EMIT_TRANSFORMS`.

---

## Theme Integration

All colors are derived from the active Textual theme via `build_theme_colors()`. The rendering pipeline never hardcodes colors — it reads from `ThemeColors` which provides semantic aliases:

- Role colors: `user` (primary), `assistant` (secondary), `system` (accent)
- Functional: `info` (primary), `warning`, `error`, `success`
- Code: `code_theme` switches between `"github-dark"` and `"friendly"` based on dark mode
- Markdown: Full Rich markdown theme dict derived from theme colors

Theme changes flow through `set_theme()` which rebuilds all derived state in `RenderRuntime`.
