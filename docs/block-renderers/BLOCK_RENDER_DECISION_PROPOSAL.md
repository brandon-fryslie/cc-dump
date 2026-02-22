# Block Rendering Decision Proposal

Date: 2026-02-22
Scope: Proposed target rendering behavior for every known block type at every visibility level.

## Inputs Reviewed

- `docs/block-renderers/BLOCK_RENDER_FORMAT_REFERENCE.md`
- `docs/block-renderers/BLOCK_RENDERING_AUDIT.md`
- `docs/side-channel/buckets/02-block-summary-generation-and-cache.md`
- `src/cc_dump/tui/rendering.py`
- `src/cc_dump/formatting.py`

## Core Decision Frame

- `// [LAW:one-source-of-truth]` Every block should have one canonical summary payload shape (`summary_compact`, `summary_detail`) and one canonical full payload shape (`full_preview`, `full_body`). Renderers read those shapes rather than re-deriving ad hoc.
- `// [LAW:dataflow-not-control-flow]` All blocks run the same 5-state rendering pipeline every time: `Hidden -> SC -> SE -> FC -> FE`; variability is in payload values and limits, not whether steps run.
- `// [LAW:single-enforcer]` Visibility policy (line limits, expanded/collapsed semantics, and override precedence) should be enforced only in renderer orchestration, not duplicated in individual block renderers.

## Global Visibility Contract (Proposed)

| State | Goal | Global Target Limit |
|---|---|---|
| Hidden | No content output | 0 lines |
| Summary Collapsed (SC) | Glanceable critical signal | 2-3 lines (default 3) |
| Summary Expanded (SE) | Rich summary, still not full | <= 8 lines |
| Full Collapsed (FC) | Real content snippet | <= 5 lines |
| Full Expanded (FE) | Full content | unlimited |

Notes:
- `// [LAW:dataflow-not-control-flow]` These limits apply uniformly as data values; block-specific renderers can emit fewer lines but should not bypass the stage.
- `// [LAW:no-mode-explosion]` Avoid introducing new per-block state flags. Keep the 5-state model canonical.

## Summary Generation Policy (Proposed)

- Deterministic first-pass summary for all content blocks (fast, local, parse-based).
- Optional side-channel summary augmentation for high-entropy blocks (long markdown, long tool output, tracked diffs, thinking).
- Summary cache key: `block_content_hash + summary_prompt_version + renderer_version`.
- `// [LAW:one-source-of-truth]` Cache key derives from canonical block content hash only.
- `// [LAW:dataflow-not-control-flow]` Pipeline always executes; cache hit/miss only changes summary values.

## Block-by-Block Proposed Rendering Matrix

### Turn Framing / Structural Markers

| Block Type | Hidden | SC | SE | FC | FE |
|---|---|---|---|---|---|
| `SeparatorBlock` | none | 1-line thin separator | 1-line thin separator | 1-line heavy separator | 1-line heavy separator |
| `HeaderBlock` | none | `REQUEST/RESPONSE + time` | add `request_id/session short` | same as SE + transport badge | same as FC |
| `RoleBlock` (legacy) | none | role label only | role + timestamp | role + timestamp + agent badge | same as FC |
| `NewlineBlock` | none | empty | empty | empty | empty |
| `NewSessionBlock` | none | 1-line `NEW SESSION <short id>` | 2-line banner (short id + reason/new lane) | 3-line full banner | 3-line full banner |
| `MessageBlock` | none | `ROLE[idx]` + child counts (`text/tools/errors`) | add timestamp + agent label + summary badges | add first child type preview | same header as FC; full children rendered |
| `MetadataSection` | none | `METADATA` + item count | `METADATA` + key badges (`headers/model/budget`) | same as SE | same as FC |
| `SystemSection` | none | `SYSTEM` + block count | add changed/new/ref counts | same as SE | same as FC |
| `ToolDefsSection` | none | `N tools / tokens` | add top 3 heavy tools | add dense list preview | same as FC |
| `ResponseMetadataSection` | none | `RESPONSE METADATA` | add status/model badges | same as SE | same as FC |
| `ResponseMessageBlock` | none | `ASSISTANT` | `ASSISTANT + content/tool counts` | add first content preview | same header as FC; full children rendered |

### Message Content (Critical)

| Block Type | Hidden | SC | SE | FC | FE |
|---|---|---|---|---|---|
| `TextContentBlock` (USER/ASSISTANT/SYSTEM) | none | 1-line intent summary + line count + badges (`code/xml/md`) | 5-8 line structured summary: intent, key artifacts (paths/commands), constraints, asks | first 5 lines of actual segmented content (with collapsed region indicators) | full segmented content with per-region controls |
| `TextDeltaBlock` | none | `delta preview + total delta lines` | rolling summary of accumulated deltas in current stream chunk | first 5 lines of current accumulated delta text | full accumulated delta text |
| `ImageBlock` | none | `[image] media_type + dimensions(if known)` | add source/origin + alt/annotation preview(if any) | metadata + first caption line | full metadata + caption/annotation body |
| `ThinkingBlock` | none | `[thinking] line count + topic keywords` | 4-8 line reasoning summary (claims, plan, open risks) | first 5 lines raw thinking | full thinking |
| `TrackedContentBlock` | none | `tag + status + line delta` | diff-aware summary with changed hunks/topics (not full body) | first 5 lines of current canonical content | full canonical content |
| `ConfigContentBlock` | none | source + line count + first directive | summary of key directives/constraints + referenced files/tools | first 5 lines raw config content | full config content |
| `HookOutputBlock` | none | hook name + status + line count | summary of hook effect (what was injected/modified) | first 5 lines raw hook output | full hook output |

### Request / Response Metadata

| Block Type | Hidden | SC | SE | FC | FE |
|---|---|---|---|---|---|
| `MetadataBlock` | none | model + stream + tools count | add max_tokens, user/account/session short ids | compact key-value snippet (first 5 kv fields) | full metadata kv set |
| `HttpHeadersBlock` | none | status/request + header count + content-type | prioritized header summary (auth/cache/content/security; max 8 lines) | first 5 raw headers in importance order | full raw headers |
| `TurnBudgetBlock` | none | total context tokens + utilization status | component breakdown (`sys/tools/conv/cache`) with percentages and trend badge | compact raw budget lines (<=5) | full budget + per-tool contribution |
| `StopReasonBlock` | none | stop reason enum | stop reason + concise interpretation | raw stop metadata snippet | full stop metadata |
| `StreamInfoBlock` | none | model id | model + lane/stream mode | model + stream technical fields snippet | full stream metadata |
| `SystemLabelBlock` | none | `SYSTEM:` | `SYSTEM:` + count of tracked children | same as SE | same as FC |

### Tool Definitions

| Block Type | Hidden | SC | SE | FC | FE |
|---|---|---|---|---|---|
| `ToolDefinitionsBlock` | none | total tools + total tokens + heavy-tool badge | grouped summary by family + top tools + token distribution | dense flat list of tool names (up to 5 lines) | full per-tool expandable definitions |
| `ToolDefBlock` | none | tool name + token estimate + required-param count | name + one-line purpose + key required params | name + short param table (fit 5 lines) | full description + schema |
| `SkillDefChild` | none | skill name + short purpose | add plugin/source + one-line capability/risk | include key usage hint | full child details |
| `AgentDefChild` | none | agent name + one-line responsibility | add tool access scope + one-line constraints | include key behavior hints | full child details |

### Tool Usage (Critical)

| Block Type | Hidden | SC | SE | FC | FE |
|---|---|---|---|---|---|
| `ToolUseBlock` | none | tool call identity only (`name`, risk badge, target path/subject) | call intent + sanitized key args + one-line tool description | true payload snippet (first 5 lines of actual tool input representation) | full tool input rendering + description |
| `ToolResultBlock` | none | result status signal (`ok/error`, line count, exit code if known) | outcome summary (files changed/hits/errors/key lines) | first 5 lines of raw result body with key highlights | full tool result body |
| `ToolUseSummaryBlock` | none | aggregate counts (`N tools, top calls`) | short chronology (`first -> ... -> last`) + hotspots | detailed aggregate table (tool, count, error-rate if known) | full aggregate chronology for collapsed tool run |
| `StreamToolUseBlock` | none | `[tool_use] name` | add tool-use id + short detail | add first argument key preview | full streamed tool-use payload snapshot |

### Errors / Unknowns

| Block Type | Hidden | SC | SE | FC | FE |
|---|---|---|---|---|---|
| `ErrorBlock` | none (always visible) | HTTP code + reason | add actionable retry hint + request correlation id | include short raw body preview | full raw error payload |
| `ProxyErrorBlock` | none (always visible) | proxy error title | add route/upstream phase + retryability | short raw proxy details snippet | full proxy error details |
| `UnknownTypeBlock` | none (always visible) | unknown type label | unknown type + payload size + parent context | unknown type + raw preview | full unknown payload |

## High-Value Renderer Improvements Beyond Current Draft

1. Unified structured summary schema for all content blocks.
- `// [LAW:one-type-per-behavior]` Text-like blocks (`TextContentBlock`, `TextDeltaBlock`, `ConfigContentBlock`, `HookOutputBlock`, `ThinkingBlock`) should share one summary extractor with block-specific adapters.

2. Importance-ordered metadata rendering.
- `// [LAW:single-enforcer]` Define one canonical header priority order (`status`, `content-type`, auth, cache, security, trace) for `HttpHeadersBlock`; do not let each renderer choose its own ordering.

3. Tool result semantic extraction layer.
- Add one extraction pass producing `result_facts` (`changed_files`, `match_count`, `exit_code`, `duration`, `error_kind`) consumed by SC/SE/FC.
- `// [LAW:one-source-of-truth]` Facts are computed once and reused by all tool-result renderer states.

4. Region-aware summary (not only region-aware full).
- SC/SE for text should include region digest lines: `code fences: N`, `xml blocks: M`, `largest region: ...`.

5. Optional sixth visibility state (future): `Presence Hint`.
- Behavior: always 1-line existence marker for hidden categories (`[3 tool blocks hidden]`).
- `// [LAW:no-mode-explosion]` Only add if this becomes a true sixth canonical state across all categories, not a per-category toggle.

## Feasible Rollout Plan

1. Phase 1 (immediate)
- Adopt global limits: SC=3, SE=8, FC=5, FE=unbounded.
- Ensure every content/tool block has distinct SC/SE/FC/FE renderer outputs.
- Align `TextContentBlock`, `ToolUseBlock`, `ToolResultBlock`, `HttpHeadersBlock` with matrix above.

2. Phase 2
- Add structured summary extraction and caching for text/tool-result/thinking/tracked-content.
- Add tool-result semantic facts extraction.

3. Phase 3
- Add optional side-channel summary augmentation for long or complex blocks.
- Add presence-hint state only if validated by usage data.

## Acceptance Criteria for This Proposal

- Every block type has explicit behavior for all 5 current visibility states.
- Content-bearing blocks have materially different summary vs full renderings.
- Summary-expanded is still summary (bounded, digest-oriented), not full-content fallback.
- FE remains full content for every block containing intrinsic payload.
- Structural blocks remain stable and subtle across states, while still conveying extra context in expanded modes.
