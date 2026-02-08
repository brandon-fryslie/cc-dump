# Sprint: dead-code-cleanup - Remove Dead Code and Rename Expand Filter
Generated: 2026-02-06
Confidence: HIGH: 3, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Remove dead code and rename the "expand" filter to free naming space for turn-level collapse.

## Scope
**Deliverables:**
- Delete dead block types (DiffBlock, LogBlock) and dead function (get_model_economics)
- Rename "expand" filter to "budget" across all 5 duplication sites
- Document dual token estimation decision

## Work Items

### P0: Delete dead block types and dead function
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] `DiffBlock` class removed from formatting.py (keep `make_diff_lines` function)
- [ ] `LogBlock` class removed from formatting.py
- [ ] `LogBlock` import removed from rendering.py
- [ ] `LogBlock` renderer (`_render_log`) removed from rendering.py
- [ ] `LogBlock` entries removed from BLOCK_RENDERERS and BLOCK_FILTER_KEY dicts
- [ ] `get_model_economics()` removed from db_queries.py
- [ ] All tests pass

**Technical Notes:**
- `make_diff_lines()` in formatting.py is still used by rendering.py — keep it, only delete the `DiffBlock` class
- `LogsPanel` widget uses Rich Text directly, not LogBlock — no impact from deletion

### P1: Rename "expand" filter to "budget"
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] Filter key renamed from "expand" to "budget" in all 5 locations:
  1. `app.py` — reactive property `show_expand` → `show_budget`, `active_filters` dict key
  2. `palette.py` — `_FILTER_INDICATOR_INDEX` entry
  3. `custom_footer.py` — `ACTION_TO_FILTER` / `_filter_names` entry
  4. `rendering.py` — `BLOCK_FILTER_KEY` entry for `TurnBudgetBlock`
  5. `widget_factory.py` — any references in `FilterStatusBar` or `_expanded_overrides` logic
- [ ] Keybinding updated (currently `e` for expand — keep `e` or change to `b`)
- [ ] Footer label updated to show "budget" instead of "expand"
- [ ] All tests pass
- [ ] Single commit, easily revertable

**Technical Notes:**
- This is a pure rename across 5 files. No logic changes.
- The "expand" name is overloaded — it means "show TurnBudgetBlock analytics" but sounds like "expand/collapse blocks." Renaming to "budget" is precise and frees "expand/collapse" for the turn-level feature.

### P2: Document token estimation decision
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] Comment in `analysis.py:estimate_tokens()` noting that `token_counter.py:count_tokens()` exists and is the accurate version for DB storage
- [ ] Comment in `token_counter.py:count_tokens()` noting that `analysis.py:estimate_tokens()` exists and is the fast heuristic for display
- [ ] Both comments explain why both exist: heuristic for real-time display, tiktoken for accuracy-sensitive storage

**Technical Notes:**
- Not removing either. Both serve valid purposes at their callsites. The one-source-of-truth violation is resolved by documenting the intentional split.

## Dependencies
- Scroll simplification should be committed first (currently uncommitted on branch)

## Risks
- Filter rename touches 5 files — risk of missing one. Mitigation: grep for "expand" across src/ after rename to verify.
