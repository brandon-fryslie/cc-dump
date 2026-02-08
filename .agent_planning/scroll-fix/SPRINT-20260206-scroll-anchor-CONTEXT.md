# Implementation Context: scroll-anchor

## What Changed and Why

### Problem
`rerender()` in `ConversationView` had three competing scroll anchor strategies:
1. `_saved_anchor` — block-level, **persistent across toggles** (leaked state)
2. `_find_viewport_anchor()` — turn-level (correct abstraction)
3. `_compute_anchor_from_scroll()` — block-level, fresh per call

Strategy 2 and 3 both ran, with 3 overwriting 2. Strategy 3 could save `_saved_anchor`, which then hijacked the *next* unrelated filter toggle via strategy 1. This caused scroll position jumps across unrelated filter changes.

### Solution
Single strategy: turn-level anchor `(turn_index, offset_within_turn)`. Captured before re-render, restored after. Stateless — no field writes between calls.

### Architectural Properties
- **Filter-agnostic**: Anchor operates on turn geometry, not block types or filter semantics
- **Stateless**: No `_saved_anchor` persisting between `rerender()` calls
- **Feature-independent**: New block types, filters, or rendering changes cannot break scroll preservation

## Files Modified
- `src/cc_dump/tui/widget_factory.py` — removed 3 methods and 1 field, simplified `rerender()`, fixed `_deferred_offset_recalc()`
- `tests/test_widget_arch.py` — replaced `TestSavedScrollAnchor` (7 tests) with `TestScrollPreservation` (6 tests)

## Key Methods
- `_find_viewport_anchor()` (widget_factory.py:640) — captures `(turn_index, offset_within)`
- `_restore_anchor()` (widget_factory.py:631) — restores position, clamps offset, falls back to nearest visible turn
- `rerender()` (widget_factory.py:647) — single capture→re-render→restore cycle
- `_deferred_offset_recalc()` (widget_factory.py:322) — now also captures/restores anchor
