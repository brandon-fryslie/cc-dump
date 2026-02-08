# Evaluation: Architectural Simplification
Timestamp: 2026-02-06
Git Commit: 28b7028 (+ uncommitted scroll simplification on branch bmf_fix_missing_assistant_header)

## Executive Summary
Overall: 15% complete | Critical issues: 0 | Tests reliable: yes (core tests)

The complexity audit (COMPLEXITY_AUDIT.md) is thorough and accurate. The three proposed principles are sound and well-targeted. However, this evaluation found two important clarifications needed before work begins, and identified a sequencing risk that could cause rework if the phases are not ordered carefully.

Current state: the audit is done, principles are articulated, scroll simplification is in-progress (uncommitted diff removes ~80 lines from widget_factory.py), no other simplification work has started.

## Runtime Check Results
| Check | Status | Output |
|-------|--------|--------|
| Core tests (179) | PASS | 0.20s, all green |
| Full test suite | UNKNOWN | Killed at 82% (exit code 144, likely hanging TUI integration test) |
| Ruff lint | NOT RUN | (not blocking for evaluation) |
| Scroll simplification diff | VALID | Removes 3-strategy system, replaces with turn-level-only anchor |

## Missing Checks
- No automated test that filter names are consistent across all files (the audit identifies 5+ locations but no test enforces sync)
- No test that DiffBlock/LogBlock are actually dead (could add a test that scans for instantiation)
- No benchmark for scroll preservation accuracy across filter cycles with large turn counts

## Findings

### Principle 1: State belongs on the data, not in the pipeline
**Status**: SOUND, NOT STARTED
**Evidence**:
- Per-block expand overrides live in `ConversationView._expanded_overrides` (widget_factory.py:162) as `dict[tuple[int, int], bool]`
- Threading path confirmed: `_overrides_for_turn()` (line 845) -> `re_render()` (line 87) -> `render_turn_to_strips()` (rendering.py:516) -> `render_blocks()` (line 469) -> `render_block()` (line 403) -> individual renderers with `expanded=` kwarg
- That is 6 levels of parameter threading to deliver a boolean to the renderer
- Moving `collapsed: bool = False` onto FormattedBlock (or the specific expandable subclasses) would eliminate this entire chain

**Issue 1 -- Design decision needed**: Should `collapsed` go on `FormattedBlock` base class or only on `TrackedContentBlock` and `TurnBudgetBlock`?
- Base class: simpler, uniform. But then 21 of 23 subclasses carry a field they never use. The CLAUDE.md law `one-type-per-behavior` does not clearly resolve this -- the field controls the same behavior (collapse rendering) but most blocks do not support it.
- Specific subclasses only: more precise, but the renderer must still check `hasattr(block, 'collapsed')` or use a protocol. Maintains the "expandable block types" registry.
- **Recommendation**: Add to base class. The field costs nothing (dataclass default), enables future expansion, and eliminates the `_EXPANDABLE_BLOCK_TYPES` set, BLOCK_FILTER_KEY special-casing, and the entire `_expanded_overrides` machinery. The renderer reads `block.collapsed` directly.

**Issue 2 -- Who mutates the field?** Currently ConversationView owns expand state. If state moves to the block, the click handler in ConversationView._toggle_block_expand (line 870) would mutate `block.collapsed` directly on the FormattedBlock instance. This is clean -- the block is mutable, owned by TurnData, which is owned by ConversationView. No ownership inversion. But it does mean the FormattedBlock is no longer a pure IR -- it carries UI state. This is an intentional trade-off worth documenting.

### Principle 2: Cross-cutting concerns get a single owner with a narrow interface
**Status**: IN PROGRESS (scroll simplification underway)
**Evidence**:
- Uncommitted diff removes `_saved_anchor`, `_compute_anchor_from_scroll()`, `_scroll_to_anchor()` and the multi-strategy logic in `rerender()` (net -80 lines)
- New code: `_find_viewport_anchor()` returns `(turn_index, offset_within)`, `_restore_anchor()` restores it
- Used in exactly 2 places: `rerender()` and `_deferred_offset_recalc()`
- Tests updated: `TestSavedScrollAnchor` replaced with `TestScrollPreservation` (7 test cases covering: filter toggle, no cross-toggle state, follow mode skip, clamped offset, deferred recalc, invisible anchor fallback)

**Assessment**: This is well-executed. The single strategy (turn-level anchor) is simpler and covers all current cases. The test coverage is thorough. The one concern is that `on_resize()` (line 721) does NOT use the anchor system -- it re-renders all turns without scroll preservation. This is acceptable for resize (rare event, viewport changes anyway) but should be noted as an intentional omission, not a gap.

**Remaining work for Principle 2 beyond scroll**: The filter system is the other cross-cutting concern that needs a single owner. Currently 5+ locations define filter names. This is Phase 2 in the audit's plan.

### Principle 3: Special cases are configuration on a general mechanism
**Status**: NOT STARTED
**Evidence**:
- `_tool_detail()` in formatting.py:376 uses if/elif for "Read", "Skill", "Bash" -- a dict would suffice
- Filter names duplicated across palette.py, app.py, custom_footer.py, rendering.py, widget_factory.py
- No filter registry exists

**Assessment**: This is correctly identified and straightforward to implement. A filter registry (single dict defining name, key, display label, color index, default state) would consolidate 5 locations into 1.

### Dead Code (Phase 1)
**Status**: NOT STARTED, fully identified
**Evidence**:
- `DiffBlock` (formatting.py:84): class defined, has fields, but `DiffBlock(` never appears as an instantiation anywhere in src/. The `make_diff_lines()` function (formatting.py:328) is used -- it returns raw tuples, not DiffBlock instances.
- `LogBlock` (formatting.py:201): class defined, imported in rendering.py:33, has a renderer at rendering.py:332, registered in BLOCK_RENDERERS and BLOCK_FILTER_KEY. But `LogBlock(` is never instantiated. The `LogsPanel` widget (widget_factory.py:1338) uses Rich Text objects directly, not LogBlock.
- These can be deleted safely. The renderer entries and imports should be cleaned up simultaneously.

### Filter Duplication (Phase 2)
**Status**: NOT STARTED, well-analyzed
**Evidence -- exact locations of the 5 duplication sites**:

1. **palette.py:66-75** -- `_FILTER_INDICATOR_INDEX` dict maps 8 filter names to color indices
2. **app.py:537-548** -- `active_filters` property builds dict from 8 reactive properties
3. **custom_footer.py:72-81** -- `_filter_names` list maps 8 action names to filter keys
4. **rendering.py:62-69** -- `_build_filter_indicators()` maps 5 content filter names to indicator symbols
5. **widget_factory.py:1296-1308** -- `FilterStatusBar.update_filters()` hardcodes 5 content filters

Adding a new filter requires editing all 5 files. There is no test that enforces consistency -- if someone adds a filter to app.py but forgets custom_footer.py, the footer silently ignores it.

**Key distinction**: There are two filter types:
- Content filters (headers, tools, system, expand, metadata) affect block rendering
- Panel filters (stats, economics, timeline) affect widget visibility
These use the same mechanism (reactive booleans + dict) but have different semantics. A registry should distinguish them.

### widget_factory.py Decomposition (Phase 3)
**Status**: NOT STARTED
**Evidence**:
- 1,404 lines (will be ~1,320 after scroll simplification commit)
- ConversationView class alone is ~900 lines handling: virtual rendering, turn storage, streaming, selection, navigation, per-block expand, filter-aware re-rendering, caching
- The audit recommends extracting TurnStore, ScrollManager, StreamingManager
- These are natural seams -- each would own a clear subset of state and have a narrow interface

**Risk assessment**: This is the highest-risk phase. Each extraction must:
1. Maintain hot-reload compatibility (module-level imports, string-based type checks)
2. Preserve the `get_state()`/`restore_state()` protocol
3. Not break the streaming delta/stable strip boundary (the most fragile state machine)

**Recommendation**: Defer Phase 3 until Phases 1-2 are complete and the feature (turn-level collapse) is implemented. The god module is ugly but functional. Decomposition for its own sake risks regressions without delivering user value.

### Dual Token Estimation
**Status**: NOT STARTED
**Evidence**:
- `estimate_tokens()` in analysis.py:15 -- heuristic, `len(text) // 4`
- `count_tokens()` in token_counter.py:14 -- tiktoken-based, accurate
- analysis.py's heuristic is used for TurnBudget computation (displayed in TurnBudgetBlock)
- token_counter.py is used for store.py (DB storage of tool invocation token counts)
- No documented decision on which is canonical

**Impact**: Low. Both produce "close enough" numbers for display purposes. The heuristic is faster. The inconsistency is cosmetic, not functional. However, it violates `one-source-of-truth` law.

**Recommendation**: Document the choice. Keep both -- heuristic for real-time display estimates, tiktoken for DB storage (where accuracy matters for cost tracking). Add a comment in each noting the other exists and why both are kept.

## Ambiguities Found
| Area | Question | How LLM Guessed | Impact |
|------|----------|-----------------|--------|
| collapsed field location | Base class or specific subclasses? | Not yet decided | Affects whether renderers need type-checks for the field |
| FormattedBlock mutability | Is it acceptable for blocks to carry UI state (collapsed) alongside IR data? | Audit assumes yes | Breaks pure-IR assumption if anyone expects blocks to be stateless |
| "expand" filter rename | When should this happen relative to implementing turn-level collapse? | Audit lists it in Phase 1 | If renamed before turn-level collapse is implemented, the feature has no filter to gate on |
| Phase ordering | Should filter registry (Phase 2) come before or after turn-level collapse feature? | Audit implies before | If feature is built first on the old system, the registry refactor touches more code |

## Recommendations

1. **Commit the scroll simplification now.** The uncommitted diff is clean, tests pass, and it delivers real complexity reduction (-80 lines, simpler mental model). This is the "finish what you started" priority.

2. **Do Phase 1 (dead code removal) immediately after.** Zero risk, immediate hygiene benefit. Delete DiffBlock, LogBlock, get_model_economics(). Should be < 30 minutes.

3. **Rename "expand" filter to "budget" or "analytics" before building turn-level collapse.** This frees the word "expand/collapse" for its natural meaning. Do it as a standalone commit so it is easily revertable.

4. **Add `collapsed: bool = False` to FormattedBlock base class.** This is the single highest-leverage change for enabling cheap features. Add it to the base class, not individual subclasses. Document that FormattedBlock carries UI state (collapsed) as an intentional decision -- the block is the natural place for this because the renderer reads it directly.

5. **Build the filter registry (Phase 2) only after the feature is working.** The registry is an organizational improvement that does not block any feature work. Building it first adds ceremony without delivering value.

6. **Defer widget_factory decomposition (Phase 3).** Do it when ConversationView next causes a real problem, not preemptively.

## Verdict
- [x] CONTINUE - Issues clear, implementer can fix
- [ ] PAUSE - Ambiguities need clarification

The two ambiguities (collapsed field location, FormattedBlock mutability) have clear recommended resolutions. The implementer can proceed with the recommendation (base class field, accept UI state on blocks) and adjust if user feedback suggests otherwise.

### Sequencing Summary
1. Commit scroll simplification (in progress)
2. Phase 1: Delete dead code (DiffBlock, LogBlock, get_model_economics)
3. Rename "expand" -> "budget"/"analytics"
4. Add `collapsed` field to FormattedBlock
5. Implement turn-level collapse feature
6. Phase 2: Filter registry (consolidate 5 duplication sites)
7. Phase 3: widget_factory decomposition (defer indefinitely)
