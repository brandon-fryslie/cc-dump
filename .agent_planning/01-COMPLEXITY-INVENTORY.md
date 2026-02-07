# Complexity Assessment: cc-dump Feature Inventory

## Context

We attempted to add an assistant RoleBlock header + user/assistant message collapse feature. The implementation failed because the rendering/caching architecture couldn't accommodate context-dependent block rendering (where a `TextContentBlock`'s behavior depends on which `RoleBlock` preceded it). Before attempting this again, we need to understand where complexity lives and what can be removed to create headroom.

This is a **report only** — no code changes proposed.

---

## Feature Complexity Inventory

### Tier 1: Core Value (keep, low complexity)

These are essential to the product's purpose and are cleanly implemented.

| # | Feature | Where | Complexity | Notes |
|---|---------|-------|-----------|-------|
| 1 | **HTTP proxy interception** | `proxy.py` | Low | Clean, does one thing |
| 2 | **FormattedBlock IR** | `formatting.py` (dataclasses) | Low | 22 block types, all simple data |
| 3 | **Request formatting** (message loop) | `formatting.py:format_request()` | Medium | Content polymorphism (str vs list) is API-imposed, not our choice |
| 4 | **Streaming response formatting** | `formatting.py:format_response_event()` | Low | 5 flat if-chains, each returns quickly |
| 5 | **Complete response formatting** | `formatting.py:format_complete_response()` | Low | Stateless reconstruction |
| 6 | **Virtual line rendering** | `widget_factory.py:ConversationView` | Medium | Complex but essential for performance with large conversations |
| 7 | **HAR recording/replay** | `har_recorder.py`, `har_replayer.py` | Low | Separate subsystem, clean boundaries |
| 8 | **SQLite analytics storage** | `store.py`, `db_queries.py` | Low | Derived index, not in the rendering path |
| 9 | **Event router** | `router.py` | Low | Simple fan-out |

### Tier 2: Valuable UX (keep, moderate complexity)

These provide clear user value but carry some complexity cost.

| # | Feature | Where | Complexity | Notes |
|---|---------|-------|-----------|-------|
| 10 | **Content filter toggles** (h/t/s/m/e) | `app.py`, `rendering.py` | **Medium** | 5 orthogonal boolean filters. Each block type maps to exactly one filter via `BLOCK_FILTER_KEY`. This is clean *in principle* but see issues below. |
| 11 | **System prompt tracking & diffing** | `formatting.py:track_content()` | **Medium** | Hash-based dedup + position-based change detection. 50 lines, 3 branches. State machine but well-contained. |
| 12 | **Follow mode + turn navigation** | `widget_factory.py` | **Medium** | j/k/n/N/g/G navigation + auto-scroll. Clean, uses visible-turn filtering. |
| 13 | **Stats panel** | `widget_factory.py:StatsPanel` | Low | Simple counter display, DB refresh |
| 14 | **Tool economics panel** | `widget_factory.py:ToolEconomicsPanel` | Low | DB query + table rendering |
| 15 | **Timeline panel** | `widget_factory.py:TimelinePanel` | Low | DB query + table rendering |
| 16 | **Styled footer with filter indicators** | `custom_footer.py` | Low-Medium | Pipe-marker notation parsing, dynamic CSS. Self-contained. |

### Tier 3: UX Special Cases (complexity source, evaluate each)

These are where complexity accumulates. Each is a special-case transformation added for UX polish, and each makes the system harder to extend.

---

#### 3A. Tool-only assistant run merging ✅ DONE
- **Where:** `formatting.py:_merge_tool_only_assistant_runs()` (78 lines)
- **Complexity:** **HIGH**
- **What it does:** When Claude makes multiple consecutive assistant turns containing only tool invocations (no text response), collapses them into a single ASSISTANT header with all tool blocks underneath.
- **Why it exists:** Reduces visual noise from repeated "ASSISTANT" headers during tool-heavy sequences.
- **Complexity cost:**
    - 3-phase algorithm (segment → classify → merge)
    - Nested classification function with 4 filter conditions
    - Must account for thinking blocks (UnknownTypeBlock, TextContentBlock) mixed with tool blocks
    - Inner merge loop that strips inter-group NewlineBlocks
    - **Makes block lists non-trivially different from what the API sent** — downstream code can't assume 1:1 correspondence between API messages and RoleBlock groups
- **Impact on new features:** Any feature that needs to know "which API message does this block belong to" (like user/assistant collapse) must work with merged block lists, not raw API structure. This is why adding a `RoleBlock(role="assistant")` for streaming responses interacted badly — the merge logic and the new emission were both trying to own assistant headers.
- **Verdict:** **Candidate for removal or simplification.** The UX benefit (fewer headers) is minor compared to the structural cost. Could be replaced with a simpler "hide duplicate consecutive same-role headers" at render time instead of mutating the block list.

---

#### 3B. Role rewriting: user → tool_result ✅ DONE
- **Where:** `formatting.py:format_request()` lines 398-405
- **Complexity:** **MEDIUM**
- **What it does:** When a user message contains only `tool_result` blocks, rewrites the role from "user" to "tool_result" so the header shows "TOOL RESULT" instead of "USER".
- **Why it exists:** In the Anthropic API, tool results are sent as user messages. Showing "USER" for these is misleading.
- **Complexity cost:**
    - Creates a synthetic role ("tool_result") that doesn't exist in the API
    - `_render_role()` in rendering.py must check TWO filters for RoleBlock: both `filters["system"]` and `filters["tools"]` depending on the role value
    - `BLOCK_FILTER_KEY` maps RoleBlock to "system" but the actual renderer also checks "tools" — **this is a registry lie** that breaks cache safety
    - Any new feature touching roles must know about this synthetic role
    - The `ROLE_STYLES` dict needs an entry for "tool_result" alongside the real API roles
- **Impact on new features:** Directly blocked the user/assistant collapse feature. If you want to filter by role, you need to handle "tool_result" as a third category that's neither user nor assistant. The dual-filter check in `_render_role()` means `BLOCK_FILTER_KEY` cannot accurately describe RoleBlock's filter dependency, which breaks the cache.
- **Verdict:** **Strong candidate for removal.** The UX benefit is minimal — users of this tool understand that tool results come back as user messages. Removing this eliminates: the synthetic role, the dual-filter check, the registry inconsistency, and one conditional branch in format_request.

---

#### 3C. Tool use summarization (collapsed tool runs)
- **Where:** `rendering.py:render_blocks()` lines 441-465, `_make_tool_use_summary()`
- **Complexity:** **MEDIUM-HIGH**
- **What it does:** When the tools filter is OFF, consecutive ToolUseBlocks are collapsed into a single summary line like "[used 3 tools: Bash 2x, Read 1x]".
- **Why it exists:** Shows tool activity at a glance without full detail.
- **Complexity cost:**
    - `render_blocks()` has TWO responsibilities: filter dispatch AND tool aggregation
    - Accumulates `pending_tool_uses` list with flush logic (must flush both mid-iteration and at end)
    - Summary uses the index of the first ToolUseBlock, creating non-obvious index semantics
    - The cache in `render_turn_to_strips()` sees the summary as a single entry keyed by the first block's index — but the underlying blocks haven't changed, so cache invalidation is implicit
    - **This is the pattern that makes render_blocks() hard to extend** — the failed collapse feature tried to add another accumulation pattern (role-tracking + text collapse) on top of the existing tool accumulation
- **Impact on new features:** Any new "aggregate rendering" feature (like collapsing user/assistant text) would need to add another state variable and flush mechanism to render_blocks(). The function already does too much.
- **Verdict:** **Keep but refactor.** The UX value is real (tool summary is useful). But the implementation should be separated from render_blocks() — either as a pre-pass that transforms the block list, or as a post-render aggregation step. This would make render_blocks() a clean single-responsibility dispatcher again.
- **Note:** There's also an open bug [cc-dump-1vp] about tool summaries not showing when tool view is off, suggesting this feature is already fragile.

---

#### 3D. Per-block expand/collapse (click to expand)
- **Where:** `widget_factory.py:_toggle_block_expand()`, `rendering.py:_EXPANDABLE_BLOCK_TYPES`
- **Complexity:** **MEDIUM**
- **What it does:** Clicking on a TrackedContentBlock or TurnBudgetBlock toggles its expand/collapse state independently of the global "expand" filter.
- **Why it exists:** Users want to expand one specific system prompt diff without expanding all of them.
- **Complexity cost:**
    - `_expanded_overrides` dict keyed by (turn_index, block_index) — stored in widget state
    - Must be threaded through render_blocks() → render_block() via `expanded` kwarg
    - Only 2 block types support it, but the plumbing touches every rendering call
    - Global expand toggle clears all per-block overrides (implicit state interaction)
    - Cache key includes expand_override, creating 2x cache entries per expandable block
- **Impact on new features:** The expanded_overrides mechanism is actually a reasonable pattern for per-block state. If we ever want per-block collapse for user/assistant text, this pattern could be extended. **Not a blocker.**
- **Verdict:** **Keep.** Complexity is contained and the UX value is clear.

---

#### 3E. Dual semantics of "expand" filter
- **Where:** `rendering.py:_render_turn_budget_block()`, `_render_tracked_content_block()`
- **Complexity:** **MEDIUM**
- **What it does:** The "expand" filter means two different things:
    - For TurnBudgetBlock: **visibility gate** (expand=off → block hidden entirely)
    - For TrackedContentBlock: **collapse toggle** (expand=off → content collapsed, expand=on → content shown)
    - But TrackedContentBlock is ALSO gated by the "system" filter (must be on to see it at all)
- **Why it exists:** Historical — TurnBudgetBlock was added later and reused the "expand" filter name.
- **Complexity cost:**
    - `BLOCK_FILTER_KEY` maps both to "expand" but they behave differently
    - TrackedContentBlock actually depends on TWO filters (system + expand) but the registry only declares "system" — **another registry lie**
    - New developers must understand that "expand" is overloaded
- **Impact on new features:** Moderate — adds confusion but doesn't directly block anything.
- **Verdict:** **Tolerable for now.** Could be split into "expand" (TrackedContent) and "context" (TurnBudget) if we need the filter namespace for user/assistant toggles.

---

#### 3F. Tool detail enrichment
- **Where:** `formatting.py:_tool_detail()` (18 lines) + `_front_ellipse_path()` (18 lines)
- **Complexity:** **LOW**
- **What it does:** Shows file paths for Read, skill names for Skill, command previews for Bash next to tool blocks.
- **Complexity cost:** 4 hardcoded tool name checks. Self-contained utility.
- **Verdict:** **Keep.** High UX value, low complexity, no structural impact.

---

#### 3G. Tool correlation coloring
- **Where:** `formatting.py:format_request()` lines 388, 436-461
- **Complexity:** **LOW-MEDIUM**
- **What it does:** Assigns matching colors to correlated tool_use and tool_result blocks via tool_use_id lookup.
- **Complexity cost:** Per-request state (tool_id_map, tool_color_counter). Clean.
- **Verdict:** **Keep.** Makes tool flows visually traceable.

---

#### 3H. First-message-only text tracking
- **Where:** `formatting.py:format_request()` line 424
- **Complexity:** **LOW**
- **What it does:** Only runs content tracking (hash + diff) on text blocks in the first message (i==0) when text > 500 chars.
- **Why it exists:** Reduces clutter — only the system-prompt-like first message is worth tracking.
- **Complexity cost:** One conditional. Minimal.
- **Verdict:** **Keep.** Negligible cost.

---

#### 3I. Viewport-only re-rendering + lazy deferred re-render
- **Where:** `widget_factory.py:rerender()` lines 665-724, `_lazy_rerender_turn()`
- **Complexity:** **MEDIUM-HIGH**
- **What it does:** When filters change, only re-renders turns in/near the viewport. Off-viewport turns store a `_pending_filter_snapshot` and re-render when scrolled into view.
- **Complexity cost:**
    - Two rendering paths for the same turns (immediate vs deferred)
    - `_pending_filter_snapshot` state on every TurnData
    - `render_line()` must check for pending re-renders on every frame
    - Scroll anchor saving/restoration for when a target block is filtered out
- **Verdict:** **Keep.** Performance optimization is essential for large conversations. The complexity is justified by measurable performance gain.

---

#### 3J. Hot-reload system
- **Where:** `hot_reload.py`, `app.py:_apply_hot_reload()`, `_replace_all_widgets()`
- **Complexity:** **MEDIUM-HIGH**
- **What it does:** Watches for file changes, reloads modules in dependency order, replaces widgets with state preservation.
- **Complexity cost:**
    - 8-module reload order with dependency tracking
    - Create-before-remove widget replacement pattern
    - All widgets must implement get_state/restore_state
    - String-based block type lookups (not class identity) throughout rendering — because class objects change on reload
    - Import discipline enforcement (stable modules use `import cc_dump.module`, not `from`)
- **Impact on new features:** Forces all new code to use string-based type dispatch instead of isinstance. This is a pervasive constraint.
- **Verdict:** **Keep.** Development velocity benefit far outweighs the complexity cost. The constraints it imposes are well-documented.

---

#### 3K. Request header injection
- **Where:** `event_handlers.py:handle_request()` lines 53-67
- **Complexity:** **LOW-MEDIUM**
- **What it does:** Stores request headers from a separate event and injects them into the block list after MetadataBlock.
- **Complexity cost:** Searches block list for MetadataBlock position using linear scan. Stateful (pending_request_headers in app_state).
- **Verdict:** **Keep.** Minor complexity, useful feature.

---

#### 3L. Streaming turn lifecycle
- **Where:** `widget_factory.py:begin_streaming_turn()`, `append_streaming_block()`, `finalize_streaming_turn()`
- **Complexity:** **MEDIUM-HIGH**
- **What it does:** Manages incremental rendering of streaming responses — buffers TextDeltaBlocks, renders other blocks immediately, consolidates on finalization.
- **Complexity cost:**
    - TurnData has streaming-specific fields: `is_streaming`, `_text_delta_buffer`, `_stable_strip_count`
    - Delta buffer flushing creates NEW blocks (TextContentBlock from accumulated text), which changes block object identity and invalidates cache
    - Two rendering modes per streaming turn: incremental (append strips) and full (re-render on finalize)
- **Impact on new features:** New block types added to streaming must handle the delta buffer flush boundary correctly. The finalization step creates fresh block objects, which means any feature depending on block object identity across streaming → finalized transition will break.
- **Verdict:** **Keep.** Essential for live proxy use. The complexity is inherent to the problem.

---

## Summary: Complexity Budget

### Registry/Cache Integrity Issues (systemic)

These aren't features but **architectural lies** that make every new feature harder:

1. **`BLOCK_FILTER_KEY` is incomplete** — RoleBlock declares "system" but also checks "tools". TrackedContentBlock declares "system" but also uses "expand". The cache in `render_turn_to_strips()` relies on this registry to build cache keys, meaning **cache keys are wrong for these block types**.

2. **`render_blocks()` has dual responsibility** — It's both a filter-and-dispatch loop AND a tool-use aggregator. Adding any new aggregation pattern (like the failed role-tracking collapse) compounds the complexity multiplicatively.

3. **Block identity changes across streaming finalization** — Delta buffers create new TextContentBlock objects, invalidating block-identity-based cache keys. Any new cache-dependent feature must account for this.

### Recommended Removals

| Feature | Complexity freed | Risk | Recommendation |
|---------|-----------------|------|----------------|
| **3B: Role rewriting (user→tool_result)** | Medium | Low — users understand tool results | ✅ **Removed.** |
| **3A: Tool-only assistant run merging** | High | Low — repeated headers are minor noise | ✅ **Removed.** |

### Recommended Refactors (before adding user/assistant collapse)

| Feature | What to do | Why |
|---------|-----------|-----|
| **3C: Tool use summarization** | Extract from render_blocks() into a pre-pass or post-pass | Makes render_blocks() a clean single-responsibility dispatcher, allowing new aggregation patterns |
| **Registry fix** | Make BLOCK_FILTER_KEY truthful, or make renderers not check filters they don't declare | Fixes cache safety, enables reliable new filter dimensions |

### Estimated complexity freed by removals

Removing 3A + 3B eliminates:
- ~100 lines of special-case code
- 1 synthetic role ("tool_result") and its rendering/styling entries
- The dual-filter check in `_render_role()`
- The `BLOCK_FILTER_KEY` lie for RoleBlock
- The block-list mutation that breaks 1:1 API↔block correspondence
- The need to handle "what if blocks were merged?" in any new role-aware feature

This would make implementing user/assistant collapse **straightforward**: each turn's blocks would have a clear, unmutated RoleBlock → content structure, and `BLOCK_FILTER_KEY` could be extended to handle role-based filters honestly.

---

## Verification

This is a report only. No code changes to verify.
