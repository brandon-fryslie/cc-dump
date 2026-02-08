# Sprint: scroll-anchor - Fix Scroll Position Preservation
Generated: 2026-02-06
Confidence: HIGH: 3, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Commit the already-applied scroll position fix, clean up artifacts, and verify.

## Scope
**Deliverables:**
- Clean committed scroll fix (widget_factory.py + test_widget_arch.py)
- Formatting.py restored to clean state (remove hot-reload test artifacts)
- Temp backup file removed

## Work Items

### P0: Commit scroll position fix
**Confidence: HIGH**

**Acceptance Criteria:**
- [ ] `widget_factory.py` changes committed: removed `_saved_anchor`, `_compute_anchor_from_scroll`, `_scroll_to_anchor`; simplified `rerender()`; fixed `_deferred_offset_recalc`
- [ ] `test_widget_arch.py` changes committed: `TestSavedScrollAnchor` replaced with `TestScrollPreservation` (6 tests)
- [ ] All 37 tests in `test_widget_arch.py` pass
- [ ] Full test suite passes (excluding known-flaky PTY test)

**Technical Notes:**
- Changes are already applied in working tree. Just needs staging and committing.
- The scroll anchor is now a single turn-level `(turn_index, offset_within)` tuple — stateless, filter-agnostic.

### P1: Clean up formatting.py artifacts
**Confidence: HIGH**

**Acceptance Criteria:**
- [ ] `formatting.py` line 1-2 hot-reload test comments removed (`# Rapid change 0`, `# Hot-reload test comment`)
- [ ] `formatting.py.temp_backup` deleted
- [ ] `python -c "import cc_dump.formatting"` succeeds

**Technical Notes:**
- These are leftover from a previous hot-reload testing session, not related to the scroll fix.
- Should be committed separately or as part of the same commit with clear message.

### P2: Verify architectural soundness
**Confidence: HIGH**

**Acceptance Criteria:**
- [ ] No references to `_saved_anchor` remain in codebase
- [ ] No references to `_compute_anchor_from_scroll` remain in codebase
- [ ] No references to `_scroll_to_anchor` remain in codebase
- [ ] `rerender()` has no state that persists between calls (no field writes except `_last_filters` and `_expanded_overrides` clearing)

**Technical Notes:**
- Grep for removed identifiers to ensure no stale references.

## Dependencies
- None. All code changes are already applied.

## Risks
- None identified. Implementation is complete and tested.
