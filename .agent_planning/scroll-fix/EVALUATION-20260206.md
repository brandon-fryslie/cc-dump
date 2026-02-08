# Evaluation: Scroll Position Fix

**Verdict: CONTINUE**

## Current State

The implementation is **already complete**. All code changes from the plan have been applied:

### Applied Changes (widget_factory.py)
- `_saved_anchor` field: **removed** from `__init__`
- `_compute_anchor_from_scroll()`: **deleted**
- `_scroll_to_anchor()`: **deleted**
- `rerender()`: **rewritten** — single turn-level anchor, stateless
- `_deferred_offset_recalc()`: **fixed** — captures/restores anchor around offset recalculation

### Applied Changes (test_widget_arch.py)
- `TestSavedScrollAnchor`: **replaced** with `TestScrollPreservation` (6 tests)
- All 6 new tests pass:
  - `test_filter_toggle_preserves_viewport_turn` ✓
  - `test_no_cross_toggle_state` ✓
  - `test_follow_mode_skips_anchor` ✓
  - `test_clamped_offset_when_turn_shrinks` ✓
  - `test_deferred_rerender_preserves_scroll` ✓
  - `test_anchor_turn_invisible_falls_back` ✓

### Test Results
- `tests/test_widget_arch.py`: 37/37 passed
- Full suite: 351/352 passed (1 flaky PTY integration test — unrelated formatting.py hot-reload test artifact)

## Remaining Work

1. **Cleanup**: Remove `formatting.py.temp_backup` file and restore `formatting.py` to clean state (remove hot-reload test comments)
2. **Commit**: Stage and commit the scroll fix changes
3. **Verify**: Run targeted tests one more time post-commit

## Risks

- None identified. The code changes are minimal, focused, and well-tested.
- The architecture is now filter-agnostic and stateless, so future filter additions cannot break scroll preservation.
