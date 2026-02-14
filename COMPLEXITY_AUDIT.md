# Complexity Audit: cc-dump

**Date:** 2026-02-06
**Scope:** Full codebase audit for complexity, dead code, incomplete refactorings, and feature-level cost/benefit.

## Executive Summary

The codebase is **7,327 lines across 26 modules** with a two-stage pipeline (formatting IR -> Rich rendering). Overall code quality is high — clean separation, no TODO/FIXME debris, well-documented hot-reload patterns. However, complexity has accumulated unevenly:

- **widget_factory.py** (1,483 lines) is a god module handling 8 distinct concerns
- **23 FormattedBlock subclasses** where ~5 are dead/unused
- **Filter state duplicated** across 4 files with no single source of truth
- **Dual token estimation** (heuristic in analysis.py + tiktoken in token_counter.py)
- Several features add complexity disproportionate to their value

Implementing expand/collapse of user/assistant blocks will be **difficult** in the current architecture because ConversationView already manages scroll preservation, per-block expand overrides, filter-aware lazy re-rendering, and streaming — all in one class. Adding another expand dimension (turn-level) on top of the existing block-level expand would compound the scroll anchor complexity significantly.

---

## Module Complexity Map

| Module | Lines | Complexity | Role |
|--------|-------|-----------|------|
| `widget_factory.py` | 1,483 | **HIGH** | God module: virtual rendering + streaming + selection + navigation + expand + caching |
| `rendering.py` | 748 | MODERATE | 22 render functions + filter dispatch + tool collapse pre-pass |
| `app.py` | 695 | MODERATE | Event routing + 9 reactive filters + hot-reload orchestration |
| `formatting.py` | 637 | MODERATE | 23 block types + content tracking + tool correlation |
| `analysis.py` | 386 | LOW | Pure computation, good seams |
| `db_queries.py` | 370 | LOW | SQL queries, leaf module |
| `har_recorder.py` | 342 | LOW | Event -> HAR, clean |
| `har_replayer.py` | 327 | LOW | HAR -> Events, clean |
| `event_handlers.py` | 298 | MODERATE | Event dispatch, some coupling |
| `palette.py` | 298 | LOW | Two palette systems, clean |
| `custom_footer.py` | 256 | LOW-MODERATE | Footer with filter state sync |
| Everything else | ~1,387 | LOW | Infrastructure modules |

---

## Feature-by-Feature Complexity Assessment

### 1. Content Change Tracking (System Prompt Diffs)
**Complexity: HIGH | Value: HIGH | Verdict: KEEP**

- **What:** Tracks system prompt content across requests, shows new/ref/changed status with expand/collapse and unified diffs
- **Where:** `formatting.py` (track_content, ~65 lines), `rendering.py` (_render_tracked_content, ~70 lines)
- **State:** Persistent cross-request state dict (positions, hashes, counters)
- **UX special cases:** Only first message text >500 bytes gets tracked; others are plain TextContentBlock
- **Why it's complex:** Three-state machine (new/ref/changed) with color assignment, position keys, hash dedup
- **Why keep it:** This IS the core value prop — seeing how Claude Code mutates system prompts

### 2. Tool Correlation (Color-Linked tool_use ↔ tool_result)
**Complexity: MODERATE | Value: MODERATE | Verdict: KEEP but simplify**

- **What:** Colors tool_use and tool_result blocks with matching colors so you can visually pair them
- **Where:** `formatting.py` (tool_id_map, ~20 lines), `rendering.py` (MSG_COLORS lookup)
- **State:** Per-request tool_id_map dict + tool_color_counter
- **Why it's complex:** Independent color counter, per-request state reset, fallback on missing correlation
- **Simplification:** The 6-color cycling for messages AND separate 6-color cycling for tools is over-engineered. A single color scheme could work.

### 3. Tool Detail Extraction (Inline Previews)
**Complexity: LOW-MODERATE | Value: MODERATE | Verdict: KEEP**

- **What:** Shows `Read: ...src/foo.py`, `Bash: ls -la`, `Skill: commit` inline on tool blocks
- **Where:** `formatting.py` (_tool_detail, ~20 lines, _front_ellipse_path, ~17 lines)
- **UX special cases:** Only Read, Bash, Skill get detail extraction; all others show nothing
- **Hardcoded tool names:** String matching against "Read", "Bash", "Skill", MCP read file
- **Simplification:** Could extract first key from any tool input as generic detail. But current approach is good enough.

### 4. Tool Collapse (Summary When Filter Off)
**Complexity: MODERATE | Value: MODERATE | Verdict: KEEP**

- **What:** When tools filter is off, consecutive ToolUseBlocks collapse into `[used 3 tools: Bash 2x, Read 1x]`
- **Where:** `rendering.py` (collapse_tool_runs, ~40 lines), ToolUseSummaryBlock
- **Recent refactoring:** Cleanly extracted from render_blocks in commit 3552bad
- **Why keep:** Without this, turning off tools filter shows nothing between requests — confusing

### 5. Per-Block Expand/Collapse
**Complexity: MODERATE | Value: LOW-MODERATE | Verdict: EVALUATE**

- **What:** Click TrackedContentBlock or TurnBudgetBlock to toggle expand independent of global toggle
- **Where:** `widget_factory.py` (_expanded_overrides dict, ~60 lines), `rendering.py` (expanded parameter threading)
- **State:** `dict[tuple[int, int], bool]` keyed by (turn_index, block_index), cleared on global toggle
- **Impact on expand/collapse feature:** This per-block override system would CONFLICT with turn-level expand/collapse. Adding turn-level means a third expand dimension: global > turn > block.
- **Simplification:** If we add turn-level collapse, per-block expand might become unnecessary or should be folded into it.

### 6. Scroll Position Preservation (3 Anchor Strategies)
**Complexity: HIGH | Value: MODERATE | Verdict: SIMPLIFY**

- **What:** Preserves scroll position when filters change, using 3 fallback strategies
- **Where:** `widget_factory.py` (rerender method, ~80 lines + helpers)
- **Strategies:** (a) Saved anchor from filtered-out block, (b) Turn-level anchor, (c) Block-level anchor
- **Why it's complex:** Each strategy has different semantics and fallback behavior; recursive search for nearest visible turn
- **Impact on expand/collapse:** Turn-level collapse would change line counts dramatically, requiring yet another anchor strategy
- **Simplification:** Could collapse to 1-2 strategies. The "saved anchor" for filtered blocks adds most complexity for least benefit.

### 7. Streaming Inline Rendering
**Complexity: HIGH | Value: HIGH | Verdict: KEEP**

- **What:** Shows response text character-by-character as it streams, with stable/delta strip boundary
- **Where:** `widget_factory.py` (begin/append/finalize streaming turn, ~240 lines)
- **State:** `_text_delta_buffer`, `_stable_strip_count`, `is_streaming` flag
- **Why it's complex:** Two rendering paths (delta tail vs stable prefix), consolidation on finalize, hot-reload state preservation
- **Why keep:** Real-time response display is essential for a proxy monitor

### 8. TurnBudgetBlock (Context Window Analytics)
**Complexity: MODERATE | Value: MODERATE | Verdict: KEEP but consider moving**

- **What:** Per-turn context budget breakdown: system/tools/conversation tokens, cache stats, top-5 tool costs
- **Where:** `analysis.py` (compute_turn_budget, ~80 lines), `rendering.py` (_render_turn_budget, ~50 lines)
- **Filter:** Only visible when "expand" filter is on + per-block override
- **Note:** This is the only block gated by the "expand" filter. The filter name is confusing — it means "show expanded analytics" not "expand blocks."

### 9. Filter System (8 Toggle Filters)
**Complexity: HIGH (distributed) | Value: HIGH | Verdict: CONSOLIDATE**

- **What:** 8 reactive boolean properties controlling visibility of block types and panels
- **Where:** Duplicated across 4 files:
  1. `app.py` — reactive properties + watchers
  2. `app.py` — `active_filters` property (hardcoded dict)
  3. `palette.py` — `_FILTER_INDICATOR_INDEX` (color assignments)
  4. `custom_footer.py` — `ACTION_TO_FILTER` (footer state sync)
- **Violation:** ONE SOURCE OF TRUTH law — filter names exist in 4 places with no mechanical sync
- **Impact:** Adding a new filter requires touching 4 files
- **Content filters** (headers, tools, system, expand, metadata) affect block rendering
- **Panel filters** (stats, economics, timeline) affect widget visibility
- These are two different systems using the same mechanism

### 10. Hot-Reload System
**Complexity: MODERATE | Value: MODERATE | Verdict: KEEP (necessary evil)**

- **What:** Reloads formatting/rendering modules without restarting TUI
- **Where:** `hot_reload.py` (184 lines), `app.py` (widget replacement, ~100 lines)
- **Impact:** Forces `type(block).__name__` string checks everywhere instead of isinstance, requires state serialization/deserialization on all widgets
- **Trade-off:** Development velocity (instant reload) vs architectural cleanliness (string-based dispatch)

### 11. HTTP Headers Display
**Complexity: NEAR-ZERO | Value: MODERATE | Verdict: KEEP — exemplar of good architecture**

- **What:** Shows full HTTP request/response headers in the conversation view
- **Where:** `formatting.py` (HttpHeadersBlock, format_request_headers, format_response_headers), `rendering.py` (_render_http_headers)
- **Cost:** One dataclass, two factory functions, one render function. Registered in BLOCK_RENDERERS and BLOCK_FILTER_KEY like every other block. Filtered by existing "headers" filter. Zero special cases, zero extra state.
- **This is what "free" looks like:** A non-derived property on data we already have, passing through the pipeline exactly as designed. If this pattern were expensive, the architecture would be broken.

### 12. Metadata Block
**Complexity: LOW | Value: MODERATE | Verdict: KEEP**

- **What:** Shows model name, max_tokens, stream flag, tool count per request
- **Where:** `formatting.py` (MetadataBlock), `rendering.py` (_render_metadata)
- **Clean and simple.** Good value for understanding request params.

### 13. Message Color Cycling
**Complexity: LOW | Value: LOW | Verdict: SIMPLIFY**

- **What:** Each message gets a color from 6-color palette based on position index
- **Where:** `formatting.py` (msg_color_idx), `rendering.py` (MSG_COLORS lookup)
- **Two independent color cycles:** msg_color_idx for messages, tool_color_counter for tools
- **Question:** The message-level coloring provides minimal value. The tool correlation coloring is useful. Could drop message colors entirely.

### 14. Turn Selection & Navigation
**Complexity: MODERATE | Value: MODERATE | Verdict: KEEP**

- **What:** j/k navigation between turns, jump to first/last, next tool turn
- **Where:** `widget_factory.py` (select_next_turn, next_tool_turn, ~80 lines)
- **Good feature** for navigating long conversations. Tool-turn navigation is particularly useful.

### 15. Logs Panel
**Complexity: LOW | Value: LOW | Verdict: EVALUATE**

- **What:** Shows app-level log messages in a side panel
- **Where:** `widget_factory.py` (LogsPanel, ~30 lines), `app.py` (log routing)
- **Question:** Is this actually used for debugging? Or is it vestigial from early development?

---

## Dead Code & Quick Wins

### Dead/Unused Block Types
| Block | Status | Action |
|-------|--------|--------|
| `DiffBlock` | Defined in formatting.py, never instantiated | **REMOVE** — `make_diff_lines()` is used but returns raw tuples, not DiffBlock |
| `ErrorBlock` | Defined, instantiated only in event_handlers.py | KEEP — used for error display |
| `ProxyErrorBlock` | Defined, instantiated only in event_handlers.py | KEEP — used for proxy error display |
| `LogBlock` | Defined, never instantiated | **REMOVE** — dead code |
| `ToolUseSummaryBlock` | Defined, instantiated in collapse_tool_runs | KEEP — active feature |

### Dead Functions
| Function | Location | Action |
|----------|----------|--------|
| `get_model_economics()` | db_queries.py:276-317 | **REMOVE** — never called |
| `difflib` import | formatting.py | **REMOVE** — only used by make_diff_lines which is in formatting.py but called from rendering.py (difflib imported in formatting.py but actually needed in rendering.py where make_diff_lines is called) |

### Dual Token Estimation
| System | Location | Used By |
|--------|----------|---------|
| `estimate_tokens()` heuristic (4 chars/token) | analysis.py | db_queries.py, TurnBudget computation |
| `count_tokens()` tiktoken | token_counter.py | store.py (tool invocation storage) |

**Action:** ONE SOURCE OF TRUTH violation. Pick one. tiktoken is more accurate but has a dependency. Either:
- Use tiktoken everywhere (adds ~50ms latency per call)
- Use heuristic everywhere (simpler, good enough for display)
- Keep both but document which is canonical (current state, undocumented)

### Vestigial Module
| Module | Status | Action |
|--------|--------|--------|
| `sessions.py` | 168 lines, has tests, but not wired into main app | **WIRE UP or REMOVE** — `--list` CLI arg exists and works but doesn't use sessions.py |

### Re-export Shim

_Deleted._ `tui/widgets.py` was a stale re-export shim that created stale class references after hot-reload. No code imported from it.

---

## Complexity Blockers for Expand/Collapse Feature

To implement turn-level expand/collapse (user/assistant blocks), these areas create friction:

### 1. ConversationView is Too Big (1,483 lines, 8 concerns)
The class manages: virtual rendering, turn storage, streaming, selection, navigation, per-block expand, filter-aware re-rendering, and caching. Adding turn-level collapse means touching scroll preservation, line offset calculation, render_line binary search, and cache invalidation — all interleaved in one class.

**Recommendation:** Extract at minimum:
- `TurnStore` — turn list management, offset calculation, binary search
- `ScrollManager` — anchor strategies, position preservation
- `StreamingManager` — delta buffering, stable/delta boundary

### 2. Three-Layer Expand System Would Emerge
Currently: Global expand filter → Per-block expand override
With turn collapse: Global expand → Turn expand → Per-block expand
This creates a 3-level override precedence that's hard to reason about.

**Recommendation:** Unify to one expand model: turns are the primary expandable unit. Blocks within a turn inherit the turn's state. Kill per-block expand overrides.

### 3. Scroll Anchor Complexity Compounds
Each new thing that changes line counts (filter toggle, turn collapse, block expand) needs its own scroll preservation strategy. Currently 3 strategies with fallbacks.

**Recommendation:** Single anchor strategy: "preserve the topmost visible turn at its current viewport position." This covers all cases uniformly.

### 4. Filter Name "expand" is Overloaded
Currently "expand" means "show TurnBudgetBlock analytics." Turn-level expand/collapse is a different concept entirely. Using the same filter for both would be confusing.

**Recommendation:** Rename current "expand" filter to "analytics" or "budget". Reserve "expand/collapse" for the turn-level feature.

---

## Recommended Complexity Reduction Plan

### Phase 1: Quick Wins (remove dead weight)
1. Delete `DiffBlock` class (keep `make_diff_lines` function)
2. Delete `LogBlock` class
3. Delete `get_model_economics()` from db_queries.py
4. Delete unused `difflib` import from formatting.py (verify — may be used by make_diff_lines IN formatting.py)
5. Decide on token estimation: document which is canonical, or remove one
6. Rename "expand" filter to "budget" or "analytics" to free up the name

### Phase 2: Consolidate Duplication
7. Create single filter registry (ONE SOURCE OF TRUTH) that app.py, palette.py, custom_footer.py, and rendering.py all derive from
8. Reduce scroll anchor strategies from 3 to 1 (topmost-visible-turn preservation)
9. Merge message color cycling and tool color cycling into one system, or drop message colors entirely

### Phase 3: Decompose God Module
10. Extract `TurnStore` from ConversationView (turn list, offsets, binary search)
11. Extract `ScrollManager` (anchor capture/restore)
12. Extract `StreamingManager` (delta buffering, finalization)

### Phase 4: Feature Cuts (evaluate with user)
13. **Per-block expand overrides** — remove in favor of turn-level collapse
14. **Message color cycling** — remove msg_color_idx; keep only tool correlation colors
15. **Logs Panel** — evaluate if still needed
16. **Sessions module** — wire into CLI or remove

---

## Risk Assessment for Each Cut

| Cut | Risk | Mitigation |
|-----|------|-----------|
| DiffBlock, LogBlock | Zero — never instantiated | None needed |
| get_model_economics | Zero — never called | None needed |
| Per-block expand | Low — rarely used interactively | Turn-level collapse replaces the need |
| Message colors | Low — aesthetic only | Tool colors remain for correlation |
| "expand" → "analytics" rename | Moderate — keybinding change | Update footer, docs |
| Scroll simplification | Moderate — edge case regressions | Test on long conversations with filter changes |
| ConversationView decomposition | High — large refactor | Do incrementally, test each extraction |
